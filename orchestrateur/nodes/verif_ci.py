"""
verif_ci.py — Nœud LangGraph, garde-fou non-IA (PONT §4.A).

Garanties portées :
  §3.1  Aucun faux vert       : statut CI lu à la source (API GitHub Actions).
                                Jamais la parole de l'agent, même pour le SHA.
  §3.2  Pas de maquette       : infra_real=True si le workflow déclare des service
        money-path             containers. False par défaut — si on ne peut pas
                                prouver, on ne prétend pas.
  §6    Couche non-IA         : code pur déterministe, aucun modèle impliqué.

Input depuis le state :
  repo   : str — "owner/repo"
  branch : str — branche à vérifier

Comportement :
  1. Lit le SHA du HEAD de la branche via l'API GitHub (branches/{branch}).
     Principe : zéro confiance vers l'agent, même sur un fait vérifiable.
  2. Cherche le workflow run le plus récent associé à ce SHA.
  3. Poll jusqu'à conclusion ou timeout.
  4. Détermine infra_real en inspectant le YAML du workflow.

Output ajouté au state :
  commit_sha : str  — SHA résolu par l'orchestrateur (jamais fourni par l'agent)
  ci_result  : dict — {status: GREEN|RED|PENDING|SKIPPED, infra_real: bool, ...}
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
from typing import Any

import httpx

from orchestrateur.state import OrchestratorState

log = logging.getLogger(__name__)

_GITHUB_API = "https://api.github.com"
_POLL_INTERVAL_S: int = 15
_MAX_POLLS: int = 24  # 6 min max (24 × 15 s)

_PENDING_STATUSES = frozenset({"queued", "in_progress", "waiting", "requested", "pending"})


# ── Nœud LangGraph ───────────────────────────────────────────────────────────

async def verif_ci(state: OrchestratorState) -> dict[str, Any]:
    repo = state.get("repo")
    branch = state.get("branch")

    if not repo or not branch:
        log.warning("verif_ci: repo ou branch absent dans le state — CI ignoré")
        return {
            "ci_result": {
                "status": "SKIPPED",
                "infra_real": False,
                "run_id": None,
                "conclusion": None,
                "run_name": None,
                "html_url": None,
            }
        }

    headers = _make_headers()

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Étape 1 : SHA résolu par l'orchestrateur lui-même
        sha = await _resolve_branch_sha(client, repo, branch, headers)

        # Étape 2 : poll jusqu'à run complété ou timeout
        for attempt in range(_MAX_POLLS):
            run = await _find_run_for_sha(client, repo, sha, headers)

            if run is None:
                log.info(
                    "verif_ci: aucun run pour %s@%s (poll %d/%d)",
                    repo, sha[:7], attempt + 1, _MAX_POLLS,
                )
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            if run["status"] in _PENDING_STATUSES:
                log.info(
                    "verif_ci: run %s (%s) pour %s@%s (poll %d/%d)",
                    run["id"], run["status"], repo, sha[:7], attempt + 1, _MAX_POLLS,
                )
                await asyncio.sleep(_POLL_INTERVAL_S)
                continue

            # Run terminé — détermine GREEN ou RED
            conclusion = run["conclusion"]
            status = "GREEN" if conclusion == "success" else "RED"
            infra_real = await _detect_infra_real(client, repo, run.get("path", ""), headers)

            log.info(
                "verif_ci: %s@%s → %s (conclusion=%s, infra_real=%s)",
                repo, sha[:7], status, conclusion, infra_real,
            )
            return {
                "commit_sha": sha,
                "ci_result": {
                    "status": status,
                    "infra_real": infra_real,
                    "run_id": run["id"],
                    "conclusion": conclusion,
                    "run_name": run.get("name", ""),
                    "html_url": run.get("html_url", ""),
                },
            }

    # Timeout — CI n'a pas convergé
    log.warning("verif_ci: timeout après %d polls pour %s@%s", _MAX_POLLS, repo, sha[:7])
    return {
        "commit_sha": sha,
        "ci_result": {
            "status": "PENDING",
            "infra_real": False,
            "run_id": None,
            "conclusion": None,
            "run_name": None,
            "html_url": None,
        },
    }


# ── Helpers (séparés pour faciliter les tests unitaires et d'intégration) ─────

def _make_headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }


async def _resolve_branch_sha(
    client: httpx.AsyncClient,
    repo: str,
    branch: str,
    headers: dict[str, str],
) -> str:
    """
    Lit le SHA du HEAD de la branche via GET /repos/{repo}/branches/{branch}.
    Endpoint non ambigu — retourne toujours un seul objet.
    """
    resp = await client.get(
        f"{_GITHUB_API}/repos/{repo}/branches/{branch}",
        headers=headers,
    )
    resp.raise_for_status()
    sha: str = resp.json()["commit"]["sha"]
    log.debug("verif_ci: %s/%s → SHA %s", repo, branch, sha[:7])
    return sha


async def _find_run_for_sha(
    client: httpx.AsyncClient,
    repo: str,
    sha: str,
    headers: dict[str, str],
) -> dict[str, Any] | None:
    """
    Retourne le workflow run le plus récent (par created_at) associé à ce SHA.
    Retourne None si aucun run n'existe encore (CI pas encore déclenché).
    """
    resp = await client.get(
        f"{_GITHUB_API}/repos/{repo}/actions/runs",
        headers=headers,
        params={"head_sha": sha, "per_page": 10},
    )
    resp.raise_for_status()
    runs: list[dict] = resp.json().get("workflow_runs", [])
    if not runs:
        return None
    return max(runs, key=lambda r: r["created_at"])


async def _detect_infra_real(
    client: httpx.AsyncClient,
    repo: str,
    workflow_path: str,
    headers: dict[str, str],
) -> bool:
    """
    Détermine si le workflow déclare des service containers réels (PostgreSQL, Redis…).
    Inspecte le YAML du workflow : cherche un bloc 'services:' non commenté.

    Garantie §3.2 : safe default à False.
    Si on ne peut pas prouver qu'il y a de l'infra réelle, on ne prétend pas.
    """
    if not workflow_path:
        return False
    try:
        resp = await client.get(
            f"{_GITHUB_API}/repos/{repo}/contents/{workflow_path}",
            headers=headers,
        )
        if resp.status_code != 200:
            return False
        raw = base64.b64decode(resp.json()["content"]).decode("utf-8")
        # Cherche un bloc indented "services:" (pas commenté, au moins 1 espace d'indentation)
        return bool(re.search(r"^[ \t]+services\s*:", raw, re.MULTILINE))
    except Exception as exc:
        log.debug("verif_ci: _detect_infra_real failed for %s — %s", workflow_path, exc)
        return False
