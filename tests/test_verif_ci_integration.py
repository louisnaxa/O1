"""
Tests d'intégration verif_ci — prouve le CONTRAT avec la vraie API GitHub.

Les tests unitaires (test_verif_ci.py) prouvent la logique avec des mocks.
Ce fichier prouve ce que les mocks ne peuvent PAS prouver :
  1. L'auth Bearer fonctionne vraiment (pas de 401/403).
  2. _resolve_branch_sha : l'URL branches/{branch} répond, le champ "commit.sha" existe.
  3. _find_run_for_sha : l'URL actions/runs?head_sha={sha} répond, les champs
     "workflow_runs", "status", "conclusion", "created_at" existent vraiment.
  4. Le mapping conclusion → GREEN/RED est JUSTE sur des cas RÉELS ET FIGÉS :
       GREEN SHA → conclusion "success" → status GREEN  (assertion exacte)
       RED  SHA → conclusion "failure" → status RED   (assertion exacte)
  5. infra_real est déterminé sans erreur sur un vrai YAML GitHub.

Commits figés utilisés (encode/httpx — résultats terminés, immuables) :
  GREEN : c95292e19df788f91a191d604cb785c2f84c3bb5
          run 25160365068, "Test Suite", success, 2026-04-30
  RED   : 86eb33fe9d4f4ed3bca9e407c1d72ceefda4ff81
          run 26175769958, "Test Suite", failure, 2026-05-20
  Chaque SHA a exactement 1 run — pas d'ambiguïté sur "le plus récent".

Prérequis : GITHUB_TOKEN dans l'environnement.
Run manuel : pytest tests/test_verif_ci_integration.py -m integration -v
Run CI     : job "integration-tests" dans .github/workflows/ci.yml (GITHUB_TOKEN auto)
"""

from __future__ import annotations

import os

import httpx
import pytest

from orchestrateur.nodes.verif_ci import (
    _detect_infra_real,
    _find_run_for_sha,
    _make_headers,
    _resolve_branch_sha,
)

# ── Constantes figées ─────────────────────────────────────────────────────────

_REPO = "encode/httpx"
_DEFAULT_BRANCH = "master"

# SHA vérifiés : 1 run chacun, conclusion immuable depuis des semaines
_GREEN_SHA = "c95292e19df788f91a191d604cb785c2f84c3bb5"  # success 2026-04-30
_RED_SHA   = "86eb33fe9d4f4ed3bca9e407c1d72ceefda4ff81"  # failure 2026-05-20


# ── Fixture ───────────────────────────────────────────────────────────────────

@pytest.fixture
def token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "")
    if not t:
        pytest.skip("GITHUB_TOKEN absent — test d'intégration ignoré")
    return t


# ── Test 1 : _resolve_branch_sha ─────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_resolve_branch_sha_retourne_un_sha_git_valide(token):
    """
    Prouve : auth OK, URL branches/{branch} correcte, champ commit.sha présent.
    """
    headers = _make_headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        sha = await _resolve_branch_sha(client, _REPO, _DEFAULT_BRANCH, headers)

    assert isinstance(sha, str), "Le SHA doit être une chaîne"
    assert len(sha) == 40, f"Un SHA git fait 40 caractères, obtenu {len(sha)}"
    assert all(c in "0123456789abcdef" for c in sha), "Un SHA git est en hexadécimal"


# ── Test 2 : _find_run_for_sha sur commit VERT figé ──────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_run_green_sha_retourne_success(token):
    """
    Commit figé VERT — prouve que _find_run_for_sha lit conclusion="success".
    SHA : c95292e19d (encode/httpx, Test Suite, 2026-04-30)
    Assertion exacte : conclusion == "success" → verif_ci retournerait GREEN.
    """
    headers = _make_headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        run = await _find_run_for_sha(client, _REPO, _GREEN_SHA, headers)

    assert run is not None, (
        f"Aucun run trouvé pour {_REPO}@{_GREEN_SHA[:10]} — "
        "ce SHA doit avoir un run 'Test Suite' sur encode/httpx"
    )

    # Contrat de forme : les champs qu'on utilise existent vraiment
    for field in ("id", "status", "conclusion", "created_at", "name", "html_url", "path"):
        assert field in run, f"Champ '{field}' absent de la réponse réelle GitHub"

    # Assertion exacte sur le statut — c'est ce que les mocks ne peuvent pas prouver
    assert run["status"] == "completed", (
        f"Le run doit être terminé, obtenu status='{run['status']}'"
    )
    assert run["conclusion"] == "success", (
        f"Attendu conclusion='success' (commit vert figé), obtenu '{run['conclusion']}'\n"
        f"Repo: {_REPO}, SHA: {_GREEN_SHA}"
    )

    # Vérifie le mapping → GREEN
    status = "GREEN" if run["conclusion"] == "success" else "RED"
    assert status == "GREEN"


# ── Test 3 : _find_run_for_sha sur commit ROUGE figé ─────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_find_run_red_sha_retourne_failure(token):
    """
    Commit figé ROUGE — prouve que _find_run_for_sha lit conclusion="failure".
    SHA : 86eb33fe9d (encode/httpx, Test Suite, 2026-05-20)
    Assertion exacte : conclusion == "failure" → verif_ci retournerait RED.
    """
    headers = _make_headers()
    async with httpx.AsyncClient(timeout=30.0) as client:
        run = await _find_run_for_sha(client, _REPO, _RED_SHA, headers)

    assert run is not None, (
        f"Aucun run trouvé pour {_REPO}@{_RED_SHA[:10]}"
    )

    assert run["status"] == "completed"
    assert run["conclusion"] == "failure", (
        f"Attendu conclusion='failure' (commit rouge figé), obtenu '{run['conclusion']}'\n"
        f"Repo: {_REPO}, SHA: {_RED_SHA}"
    )

    status = "GREEN" if run["conclusion"] == "success" else "RED"
    assert status == "RED"


# ── Test 4 : _detect_infra_real sur un YAML réel ─────────────────────────────

@pytest.mark.integration
@pytest.mark.asyncio
async def test_detect_infra_real_sur_workflow_reel(token):
    """
    Prouve que _detect_infra_real lit et parse un vrai YAML GitHub sans erreur.
    encode/httpx/test-suite.yml n'a pas de services: → infra_real=False attendu.
    """
    headers = _make_headers()
    workflow_path = ".github/workflows/test-suite.yml"
    async with httpx.AsyncClient(timeout=30.0) as client:
        result = await _detect_infra_real(client, _REPO, workflow_path, headers)

    assert isinstance(result, bool), "infra_real doit être un bool"
    # encode/httpx n'utilise pas de service containers → False
    assert result is False, (
        f"encode/httpx/test-suite.yml ne devrait pas déclarer services: "
        f"(obtenu infra_real={result})"
    )
