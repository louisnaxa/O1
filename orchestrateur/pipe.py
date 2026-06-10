"""
pipe.py — V0 Tuyau agent↔superviseur.

Automatise la boucle : agent → verif_ci → superviseur → décision.
Par défaut : mode automatique (pas d'Entrée humaine entre les tours).
step=True : mode débogage, pause après chaque tour.

Bornage V0 :
  - MAX_TURNS = 10 (anti-dérive)
  - PAUSE_HUMAN : log + arrêt (pas de WhatsApp en V0)
  - inject.txt : injection humaine en mode auto via fichier
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Any

import anthropic

log = logging.getLogger(__name__)

MAX_TURNS: int = int(os.getenv("MAX_TURNS", "10"))

# ── Superviseur : outil forcé (température 0, sortie typée) ──────────────────

_DECISION_TOOL: dict[str, Any] = {
    "name": "render_decision",
    "description": "Émet la décision de supervision en sortie structurée.",
    "input_schema": {
        "type": "object",
        "properties": {
            "decision": {
                "type": "string",
                "enum": ["CONTINUE", "STOP", "PAUSE_HUMAN"],
                "description": (
                    "CONTINUE : l'agent doit continuer. "
                    "STOP : tâche terminée. "
                    "PAUSE_HUMAN : bloqué, humain requis."
                ),
            },
            "reason": {
                "type": "string",
                "description": "Justification en une phrase.",
            },
            "message_to_agent": {
                "type": "string",
                "description": "Feedback transmis à l'agent pour le prochain tour. Vide si STOP.",
            },
        },
        "required": ["decision", "reason", "message_to_agent"],
    },
}

_SUPERVISOR_SYSTEM = """\
Tu es un superviseur d'agent de codage IA. Évalue la sortie de l'agent et décide :

- STOP        : la tâche est terminée de façon satisfaisante
- CONTINUE    : l'agent a progressé mais n'a pas fini — fournis du feedback ciblé
- PAUSE_HUMAN : l'agent est bloqué ou boucle — un humain doit intervenir

Règles :
1. Si CI=GREEN et la tâche est accomplie → STOP.
2. Si CI=RED → CONTINUE avec feedback sur l'échec.
3. Si turn >= 8 → préférer STOP ou PAUSE_HUMAN pour éviter la dérive.
4. Toujours appeler render_decision — jamais de prose seule.
"""


# ── Agent subprocess ──────────────────────────────────────────────────────────

def _build_agent_prompt(
    task: str,
    turn: int,
    agent_outputs: list[str],
    supervisor_message: str | None,
) -> str:
    """Construit le prompt pour l'agent selon le numéro de tour."""
    if turn == 1:
        return task

    history_parts = []
    for i, output in enumerate(agent_outputs, 1):
        excerpt = output[:500] + ("…" if len(output) > 500 else "")
        history_parts.append(f"Tour {i} — sortie agent :\n{excerpt}")

    history = "\n\n".join(history_parts)
    feedback = supervisor_message or "(aucun feedback)"

    return (
        f"Tâche originale : {task}\n\n"
        f"Historique :\n{history}\n\n"
        f"Feedback du superviseur :\n{feedback}\n\n"
        "Continue la tâche en tenant compte du feedback ci-dessus."
    )


def _call_agent(
    prompt: str,
    workdir: str | None = None,
    max_budget_usd: float = 2.0,
    timeout_s: int = 300,
) -> str:
    """
    Appelle le CLI claude en subprocess.
    Désactive CLAUDECODE pour éviter l'erreur de session imbriquée.
    Retourne le texte de sortie de l'agent.
    """
    env = os.environ.copy()
    env.pop("CLAUDECODE", None)             # anti-nested session
    env.pop("CLAUDE_CODE_ENTRYPOINT", None)

    cmd = [
        "claude",
        "-p", prompt,
        "--output-format", "json",
        "--max-budget-usd", str(max_budget_usd),
    ]

    cwd = workdir or os.getcwd()
    log.debug("_call_agent: %s … (cwd=%s)", " ".join(cmd[:3]), cwd)

    result = subprocess.run(
        cmd,
        env=env,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout_s,
    )

    if result.returncode != 0:
        raise RuntimeError(
            f"claude CLI exit {result.returncode}: {result.stderr.strip()[:400]}"
        )

    # Tente de parser le JSON ; fallback vers le texte brut
    try:
        data = json.loads(result.stdout)
        return str(data.get("result", "") or "")
    except json.JSONDecodeError:
        return result.stdout.strip()


# ── Superviseur ───────────────────────────────────────────────────────────────

def _call_supervisor(
    client: anthropic.Anthropic,
    task: str,
    turn: int,
    agent_output: str,
    ci_result: dict[str, Any] | None,
) -> dict[str, Any]:
    """
    Appelle le superviseur via l'API Anthropic (temperature=0, outil forcé).
    Retourne {decision, reason, message_to_agent}.
    """
    ci_section = ""
    if ci_result:
        status = ci_result.get("status", "SKIPPED")
        ci_section = f"\nCI : {status}"
        if status in ("GREEN", "RED"):
            ci_section += (
                f" | conclusion={ci_result.get('conclusion')}"
                f" | infra_real={ci_result.get('infra_real')}"
            )

    user_msg = (
        f"Tâche : {task}\n"
        f"Tour : {turn}{ci_section}\n\n"
        f"Sortie de l'agent ce tour :\n---\n{agent_output}\n---\n\n"
        "Appelle render_decision."
    )

    response = client.messages.create(
        model="claude-opus-4-6",
        max_tokens=512,
        temperature=0,
        system=_SUPERVISOR_SYSTEM,
        tools=[_DECISION_TOOL],
        tool_choice={"type": "any"},
        messages=[{"role": "user", "content": user_msg}],
    )

    for block in response.content:
        if getattr(block, "type", None) == "tool_use" and block.name == "render_decision":
            return dict(block.input)

    raise RuntimeError(f"Superviseur n'a pas appelé render_decision : {response.content}")


# ── inject.txt ────────────────────────────────────────────────────────────────

def _drain_inject(inject_path: Path) -> str | None:
    """Lit inject.txt, retourne le contenu s'il est non vide, puis efface le fichier."""
    if not inject_path.exists():
        return None
    content = inject_path.read_text().strip()
    if content:
        inject_path.write_text("")
        return content
    return None


# ── Boucle principale ─────────────────────────────────────────────────────────

async def run_pipe(
    task: str,
    repo: str | None = None,
    branch: str | None = None,
    step: bool = False,
    workdir: str | None = None,
    log_file: Path | None = None,
    max_turns: int = MAX_TURNS,
    max_budget_usd: float = 2.0,
) -> dict[str, Any]:
    """
    Boucle principale du tuyau V0.

    Par défaut : automatique (pas d'Entrée humaine entre les tours).
    step=True  : pause après chaque tour pour validation humaine.

    Retourne un dict résumé :
      {turns, final_decision, agent_outputs, supervisor_decisions}
    """
    from orchestrateur.nodes.verif_ci import verif_ci as _verif_ci

    client = anthropic.Anthropic()
    inject_path = Path(workdir or ".") / "inject.txt"

    agent_outputs: list[str] = []
    supervisor_decisions: list[dict[str, Any]] = []
    supervisor_message: str | None = None
    final_decision = "STOP"

    def emit(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line, flush=True)
        if log_file:
            with open(log_file, "a") as fh:
                fh.write(line + "\n")

    emit(
        f"=== PIPE START | task={task[:60]!r} | repo={repo} | "
        f"max_turns={max_turns} | step={step} ==="
    )

    for turn in range(1, max_turns + 1):
        emit(f"── Tour {turn}/{max_turns} ──────────────────────────────────────")

        # 0. Inject humain (lecture de inject.txt)
        inject = _drain_inject(inject_path)
        if inject:
            emit(f"[INJECT] {inject[:200]}")

        # 1. Prompt agent
        prompt = _build_agent_prompt(task, turn, agent_outputs, supervisor_message)
        if inject:
            prompt = f"[HUMAN INJECT] {inject}\n\n{prompt}"

        # 2. Appel agent
        emit(f"[AGENT →] {prompt[:120]}{'…' if len(prompt) > 120 else ''}")
        try:
            agent_output = _call_agent(prompt, workdir=workdir, max_budget_usd=max_budget_usd)
        except Exception as exc:
            emit(f"[AGENT ERROR] {exc}")
            final_decision = "PAUSE_HUMAN"
            break

        emit(f"[AGENT ←] {agent_output[:300]}{'…' if len(agent_output) > 300 else ''}")
        agent_outputs.append(agent_output)

        if step:
            input(f"\n[STEP] Tour {turn} — agent terminé. Entrée pour continuer…")

        # 3. verif_ci
        if repo and branch:
            emit(f"[CI] Vérification {repo}@{branch}…")
            try:
                ci_state = await _verif_ci({"repo": repo, "branch": branch})
                ci_result: dict[str, Any] = ci_state.get("ci_result", {"status": "SKIPPED"})
            except Exception as exc:
                emit(f"[CI ERROR] {exc}")
                ci_result = {"status": "SKIPPED", "infra_real": False}
            emit(f"[CI] {ci_result.get('status')}")
        else:
            ci_result = {"status": "SKIPPED", "infra_real": False}
            emit("[CI] SKIPPED")

        # 4. Superviseur
        emit("[SUPERVISOR →] Évaluation…")
        try:
            decision = _call_supervisor(client, task, turn, agent_output, ci_result)
        except Exception as exc:
            emit(f"[SUPERVISOR ERROR] {exc}")
            final_decision = "PAUSE_HUMAN"
            break

        d = decision.get("decision", "STOP")
        emit(f"[SUPERVISOR ←] {d} — {decision.get('reason', '')[:150]}")
        supervisor_decisions.append(decision)
        final_decision = d

        if step:
            input(f"[STEP] Tour {turn} — superviseur : {d}. Entrée pour continuer…")

        # 5. Route
        if d == "STOP":
            emit(f"=== STOP au tour {turn} ===")
            break
        elif d == "PAUSE_HUMAN":
            emit(f"=== PAUSE_HUMAN au tour {turn} — {decision.get('reason', '')} ===")
            emit("[V0] WhatsApp non implémenté — arrêt manuel requis.")
            break
        elif d == "CONTINUE":
            supervisor_message = decision.get("message_to_agent", "")
        else:
            emit(f"[WARN] Décision inconnue '{d}' — STOP forcé")
            final_decision = "STOP"
            break

    else:
        emit(f"=== MAX_TURNS ({max_turns}) atteint — arrêt forcé ===")
        final_decision = "PAUSE_HUMAN"

    summary: dict[str, Any] = {
        "turns": len(agent_outputs),
        "final_decision": final_decision,
        "agent_outputs": agent_outputs,
        "supervisor_decisions": supervisor_decisions,
    }
    emit(f"=== PIPE END | turns={summary['turns']} | decision={final_decision} ===")
    return summary
