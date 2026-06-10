"""
Tests E2E du tuyau pipe.py — prouve le transport agent↔superviseur.

Ce que les tests unitaires ne peuvent PAS prouver :
  1. Le CLI claude tourne en subprocess sans nested-session error.
  2. L'agent produit une sortie réelle (pas mockée).
  3. Le superviseur reçoit cette sortie et retourne une décision typée.
  4. Le tuyau enchaîne les deux sans Entrée humaine (mode automatique).

Tâche figée : écrire greet(name) dans scratch/hello.py + test pytest.
Prérequis   : ANTHROPIC_API_KEY dans l'environnement, claude CLI installé.

Run manuel : pytest tests/test_pipe_e2e.py -m e2e -v
Run CI     : job "e2e-tests" dans .github/workflows/ci.yml
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import pytest

from orchestrateur.pipe import run_pipe

_WORKDIR = Path(__file__).parent.parent
_SCRATCH = _WORKDIR / "scratch"

_TASK = (
    "Write a Python function `greet(name: str) -> str` in the file `scratch/hello.py` "
    "that returns `f'Hello, {name}!'`. "
    "Also write a pytest test for it in `scratch/test_hello.py` "
    "that asserts `greet('World') == 'Hello, World!'`. "
    "Run the test with `python -m pytest scratch/test_hello.py -v` to confirm it passes."
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_scratch():
    """Supprime les fichiers générés avant chaque test E2E."""
    _SCRATCH.mkdir(exist_ok=True)
    for name in ("hello.py", "test_hello.py"):
        (_SCRATCH / name).unlink(missing_ok=True)
    yield


def _skip_if_missing():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY absent — test E2E ignoré")
    if not shutil.which("claude"):
        pytest.skip("claude CLI non installé — test E2E ignoré")


# ── Test 1 : transport en mode automatique ────────────────────────────────────

@pytest.mark.e2e
@pytest.mark.asyncio
async def test_pipe_greet_auto():
    """
    Mode automatique (défaut) — prouve le transport complet sans Entrée humaine.

    Assertions :
      Transport : au moins 1 tour complété, agent a produit une sortie,
                  superviseur a rendu une décision valide.
      Fonctionnel : scratch/hello.py créé avec la fonction greet.
    """
    _skip_if_missing()

    summary = await run_pipe(
        task=_TASK,
        repo=None,
        branch=None,
        step=False,
        workdir=str(_WORKDIR),
        max_turns=5,
        max_budget_usd=1.0,
    )

    # ── Preuve du transport ────────────────────────────────────────────────
    assert summary["turns"] >= 1, "Aucun tour complété"
    assert summary["agent_outputs"], "L'agent n'a produit aucune sortie"
    assert summary["supervisor_decisions"], "Le superviseur n'a pris aucune décision"

    d0 = summary["supervisor_decisions"][0]
    assert d0["decision"] in ("CONTINUE", "STOP", "PAUSE_HUMAN"), (
        f"Décision invalide : {d0['decision']}"
    )
    assert d0.get("reason"), "Champ 'reason' absent de la décision"

    # ── Preuve fonctionnelle ───────────────────────────────────────────────
    hello_py = _SCRATCH / "hello.py"
    assert hello_py.exists(), (
        f"scratch/hello.py non créé — agent_output[0][:300] = "
        f"{summary['agent_outputs'][0][:300]!r}"
    )
    assert "greet" in hello_py.read_text(), "Fonction greet absente de scratch/hello.py"
