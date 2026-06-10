"""
Squelette du graphe LangGraph.
Seul check_ci est implémenté en V1 — les autres nœuds lèvent NotImplementedError.
"""

from __future__ import annotations

import os
from typing import Any

from langgraph.graph import END, START, StateGraph

from orchestrateur.nodes.verif_ci import verif_ci
from orchestrateur.state import OrchestratorState

MAX_TURNS: int = int(os.getenv("MAX_TURNS", "10"))


# ── Stubs (briques 2, 3, 4) ──────────────────────────────────────────────────

async def run_agent(state: OrchestratorState) -> dict[str, Any]:
    """
    Brique 2 — à implémenter avec claude-agent-sdk.
    Lance Claude Code sur la tâche, capture la sortie + commit_sha après push.
    """
    raise NotImplementedError("run_agent — à implémenter (Agent SDK)")


async def run_supervisor(state: OrchestratorState) -> dict[str, Any]:
    """
    Brique 3 — à implémenter avec l'API Anthropic classique (pas l'Agent SDK).
    Reçoit agent_output + ci_status, retourne supervisor_decision JSON typé.
    """
    raise NotImplementedError("run_supervisor — à implémenter (API Anthropic classique)")


async def human_review(state: OrchestratorState) -> dict[str, Any]:
    """
    Brique 4 — à implémenter avec Twilio WhatsApp.
    Ce nœud est précédé d'un interrupt : le graph se fige avant d'y entrer.
    L'orchestrateur envoie le ping, attend la réponse, puis reprend via Command(resume=...).
    """
    raise NotImplementedError("human_review — à implémenter (WhatsApp + interrupt)")


# ── Routage conditionnel ─────────────────────────────────────────────────────

def route_decision(state: OrchestratorState) -> str:
    """
    Lit la décision typée du superviseur et route vers le nœud suivant.
    Anti-dérive : si turn_count ≥ MAX_TURNS, force PAUSE_HUMAN même sans blocage formel.
    """
    if (state.get("turn_count") or 0) >= MAX_TURNS:
        return "human_review"

    decision = (state.get("supervisor_decision") or {}).get("decision", "STOP")
    return {
        "CONTINUE": "run_agent",
        "PAUSE_HUMAN": "human_review",
        "STOP": END,
    }.get(decision, END)


# ── Construction du graphe ───────────────────────────────────────────────────

def build_graph(checkpointer=None):
    """
    Construit et compile le graphe.

    Checkpointer recommandé :
      dev  → AsyncSqliteSaver.from_conn_string("checkpoints.db")
      prod → AsyncPostgresSaver(conn_string)

    Interrupt : le graphe se fige AVANT human_review.
    Reprise : graph.ainvoke(Command(resume=human_response), config={"configurable": {"thread_id": ...}})
    """
    g = StateGraph(OrchestratorState)

    g.add_node("run_agent", run_agent)
    g.add_node("verif_ci", verif_ci)
    g.add_node("run_supervisor", run_supervisor)
    g.add_node("human_review", human_review)

    g.add_edge(START, "run_agent")
    g.add_edge("run_agent", "verif_ci")
    g.add_edge("verif_ci", "run_supervisor")
    g.add_conditional_edges("run_supervisor", route_decision)
    # human_review → run_agent après réponse humaine (ou END si l'humain dit stop)
    g.add_edge("human_review", "run_agent")

    return g.compile(
        checkpointer=checkpointer,
        interrupt_before=["human_review"],  # garde-fou : jamais franchi sans OK humain
    )
