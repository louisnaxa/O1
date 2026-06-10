"""
Tests unitaires de verif_ci — 12 cas.

Stratégie :
- Les 6 premiers testent les helpers isolément (client httpx mocké).
- Les 6 suivants testent le nœud verif_ci avec les helpers mockés,
  pour valider la logique de poll, le mapping GREEN/RED, et les cas limites.
Aucun appel réseau réel. Pour le contrat avec l'API GitHub, voir test_verif_ci_integration.py.
"""

from __future__ import annotations

import base64
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from orchestrateur.nodes.verif_ci import (
    _detect_infra_real,
    _find_run_for_sha,
    _resolve_branch_sha,
    verif_ci,
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _run(
    status: str,
    conclusion: str | None,
    created_at: str = "2026-01-01T00:00:00Z",
    run_id: int = 12345,
) -> dict:
    return {
        "id": run_id,
        "status": status,
        "conclusion": conclusion,
        "name": "Test Suite",
        "html_url": f"https://github.com/ci/run/{run_id}",
        "path": ".github/workflows/ci.yml",
        "created_at": created_at,
    }


def _http(data: dict, status_code: int = 200) -> MagicMock:
    r = MagicMock(spec=httpx.Response)
    r.status_code = status_code
    r.json.return_value = data
    r.raise_for_status.return_value = None
    return r


def _yaml(content: bytes) -> MagicMock:
    return _http({"content": base64.b64encode(content).decode()})


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 1–6 : helpers
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_1_resolve_branch_sha_extrait_le_sha():
    """_resolve_branch_sha retourne le SHA du commit HEAD depuis la réponse branches API."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_http({"commit": {"sha": "deadbeef1234567890"}}))
    sha = await _resolve_branch_sha(client, "owner/repo", "main", {})
    assert sha == "deadbeef1234567890"
    client.get.assert_awaited_once()
    # Vérifie que l'URL correcte est appelée
    url = client.get.call_args.args[0]
    assert "branches/main" in url


@pytest.mark.asyncio
async def test_2_find_run_none_quand_pas_de_runs():
    """_find_run_for_sha → None si aucun run associé au SHA (CI pas encore déclenché)."""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_http({"workflow_runs": []}))
    result = await _find_run_for_sha(client, "owner/repo", "abc123", {})
    assert result is None


@pytest.mark.asyncio
async def test_3_find_run_prend_le_plus_recent():
    """Plusieurs runs pour un SHA → retourne celui avec le created_at le plus récent."""
    runs = [
        _run("completed", "success", "2026-01-01T10:00:00Z", run_id=1),
        _run("completed", "failure", "2026-01-01T12:00:00Z", run_id=2),  # ← plus récent
        _run("completed", "success", "2026-01-01T09:00:00Z", run_id=3),
    ]
    client = AsyncMock()
    client.get = AsyncMock(return_value=_http({"workflow_runs": runs}))
    result = await _find_run_for_sha(client, "owner/repo", "abc123", {})
    assert result["id"] == 2
    assert result["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_4_detect_infra_real_true_si_services_dans_yaml():
    """YAML avec bloc indented 'services:' → infra_real=True."""
    yaml = b"""
jobs:
  test:
    services:
      postgres:
        image: postgres:15
        env:
          POSTGRES_PASSWORD: test
    steps:
      - run: pytest
"""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_yaml(yaml))
    result = await _detect_infra_real(client, "owner/repo", ".github/workflows/ci.yml", {})
    assert result is True


@pytest.mark.asyncio
async def test_5_detect_infra_real_false_sans_services():
    """YAML sans services: → infra_real=False."""
    yaml = b"""
jobs:
  test:
    steps:
      - run: pytest --tb=short
"""
    client = AsyncMock()
    client.get = AsyncMock(return_value=_yaml(yaml))
    result = await _detect_infra_real(client, "owner/repo", ".github/workflows/ci.yml", {})
    assert result is False


@pytest.mark.asyncio
async def test_6_detect_infra_real_false_sur_erreur_api():
    """Erreur réseau ou API → False (safe default — on ne prétend pas ce qu'on ne prouve pas)."""
    client = AsyncMock()
    client.get = AsyncMock(side_effect=Exception("connection refused"))
    result = await _detect_infra_real(client, "owner/repo", ".github/workflows/ci.yml", {})
    assert result is False


# ═══════════════════════════════════════════════════════════════════════════════
# Tests 7–12 : nœud verif_ci
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_7_branch_absent_retourne_skipped(monkeypatch):
    """Sans branch dans le state → SKIPPED immédiat, aucun appel réseau."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    result = await verif_ci({"repo": "owner/repo"})
    assert result["ci_result"]["status"] == "SKIPPED"
    assert result["ci_result"]["infra_real"] is False


@pytest.mark.asyncio
async def test_8_green_avec_infra_real_true(monkeypatch):
    """Run success + YAML avec services → GREEN, infra_real=True, commit_sha dans state."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    with patch("orchestrateur.nodes.verif_ci._resolve_branch_sha", new_callable=AsyncMock) as p_sha, \
         patch("orchestrateur.nodes.verif_ci._find_run_for_sha", new_callable=AsyncMock) as p_run, \
         patch("orchestrateur.nodes.verif_ci._detect_infra_real", new_callable=AsyncMock) as p_infra:
        p_sha.return_value = "sha_abc"
        p_run.return_value = _run("completed", "success")
        p_infra.return_value = True
        result = await verif_ci({"repo": "owner/repo", "branch": "main"})

    assert result["commit_sha"] == "sha_abc"
    assert result["ci_result"]["status"] == "GREEN"
    assert result["ci_result"]["infra_real"] is True
    assert result["ci_result"]["conclusion"] == "success"


@pytest.mark.asyncio
async def test_9_red_infra_real_false(monkeypatch):
    """Run failure + pas de services → RED, infra_real=False."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    with patch("orchestrateur.nodes.verif_ci._resolve_branch_sha", new_callable=AsyncMock) as p_sha, \
         patch("orchestrateur.nodes.verif_ci._find_run_for_sha", new_callable=AsyncMock) as p_run, \
         patch("orchestrateur.nodes.verif_ci._detect_infra_real", new_callable=AsyncMock) as p_infra:
        p_sha.return_value = "sha_xyz"
        p_run.return_value = _run("completed", "failure")
        p_infra.return_value = False
        result = await verif_ci({"repo": "owner/repo", "branch": "main"})

    assert result["ci_result"]["status"] == "RED"
    assert result["ci_result"]["infra_real"] is False
    assert result["ci_result"]["conclusion"] == "failure"


@pytest.mark.asyncio
async def test_10_cancelled_mappe_sur_red(monkeypatch):
    """Toute conclusion non-success (cancelled, timed_out…) → RED."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    with patch("orchestrateur.nodes.verif_ci._resolve_branch_sha", new_callable=AsyncMock) as p_sha, \
         patch("orchestrateur.nodes.verif_ci._find_run_for_sha", new_callable=AsyncMock) as p_run, \
         patch("orchestrateur.nodes.verif_ci._detect_infra_real", new_callable=AsyncMock) as p_infra:
        p_sha.return_value = "sha_xyz"
        p_run.return_value = _run("completed", "cancelled")
        p_infra.return_value = False
        result = await verif_ci({"repo": "owner/repo", "branch": "main"})

    assert result["ci_result"]["status"] == "RED"
    assert result["ci_result"]["conclusion"] == "cancelled"


@pytest.mark.asyncio
async def test_11_poll_sequence_aucun_run_puis_en_cours_puis_vert(monkeypatch):
    """Séquence réaliste : aucun run → in_progress → success → GREEN en 3 polls."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    with patch("orchestrateur.nodes.verif_ci._resolve_branch_sha", new_callable=AsyncMock) as p_sha, \
         patch("orchestrateur.nodes.verif_ci._find_run_for_sha", new_callable=AsyncMock) as p_run, \
         patch("orchestrateur.nodes.verif_ci._detect_infra_real", new_callable=AsyncMock) as p_infra, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        p_sha.return_value = "sha_abc"
        p_run.side_effect = [
            None,                               # poll 1 : CI pas encore déclenché
            _run("in_progress", None),          # poll 2 : en cours
            _run("completed", "success"),        # poll 3 : terminé vert
        ]
        p_infra.return_value = False
        result = await verif_ci({"repo": "owner/repo", "branch": "main"})

    assert result["ci_result"]["status"] == "GREEN"
    assert p_run.await_count == 3


@pytest.mark.asyncio
async def test_12_timeout_apres_max_polls(monkeypatch):
    """Toujours en cours après MAX_POLLS → status=PENDING, commit_sha présent."""
    monkeypatch.setenv("GITHUB_TOKEN", "fake")
    monkeypatch.setattr("orchestrateur.nodes.verif_ci._MAX_POLLS", 2)
    with patch("orchestrateur.nodes.verif_ci._resolve_branch_sha", new_callable=AsyncMock) as p_sha, \
         patch("orchestrateur.nodes.verif_ci._find_run_for_sha", new_callable=AsyncMock) as p_run, \
         patch("asyncio.sleep", new_callable=AsyncMock):
        p_sha.return_value = "sha_abc"
        p_run.return_value = _run("in_progress", None)
        result = await verif_ci({"repo": "owner/repo", "branch": "main"})

    assert result["ci_result"]["status"] == "PENDING"
    assert result["commit_sha"] == "sha_abc"
    assert p_run.await_count == 2  # exactement MAX_POLLS polls
