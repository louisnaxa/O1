"""
State partagé du graphe LangGraph.
Chaque nœud retourne un dict partiel qui écrase les champs concernés.
"""

from __future__ import annotations

from typing import Any, TypedDict


class OrchestratorState(TypedDict, total=False):
    # ── Contexte de tâche ────────────────────────────────────────────────────
    task: str           # consigne courante à envoyer à l'agent
    repo: str           # "owner/repo" sur GitHub
    branch: str         # branche de travail
    commit_sha: str     # SHA résolu par verif_ci lui-même (jamais fourni par l'agent)

    # ── Contrôle de boucle ───────────────────────────────────────────────────
    turn_count: int     # nombre d'allers-retours agent↔superviseur sur la tâche courante
    total_tokens: int   # tokens cumulés (in + out) — garde-fou plafond de dépense

    # ── Sorties des nœuds ────────────────────────────────────────────────────
    agent_output: str            # texte produit par l'agent (rapport + résumé)
    ci_result: dict[str, Any]   # résultat CI vérifié par verif_ci : {status: GREEN|RED|PENDING|SKIPPED, infra_real: bool, ...}
    supervisor_decision: dict[str, Any]  # JSON typé : decision / reason / message_to_agent / ...
    human_response: str         # réponse humaine reçue après PAUSE_HUMAN
