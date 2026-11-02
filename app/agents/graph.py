"""LangGraph supervisor graph — accelerator baseline.

Flow: guardrails -> supervisor -> (conditional) specialist -> supervisor -> ...
until a terminal node (respond_and_wait / human_review complete / error).

Add a specialist by: (1) writing a node in agents/nodes/, (2) registering it
below with add_node, (3) adding it to the supervisor's next_agent() router and
the conditional-edge map, and (4) looping it back to the supervisor.
"""
from __future__ import annotations

from langgraph.graph import END, StateGraph

from agents.guardrails import guardrails_node
from agents.human_in_loop import human_review_node
from agents.nodes.example_agent import example_agent_node
from agents.nodes.supervisor import next_agent, supervisor_node
from agents.state import AgentState


def _respond_and_wait_node(state: AgentState) -> AgentState:
    """Terminal: the turn is done — return control to the user."""
    return state


def _error_node(state: AgentState) -> AgentState:
    state["step_status"] = "failed"
    return state


def build_graph() -> StateGraph:
    g = StateGraph(AgentState)

    # ── Register nodes ────────────────────────────────────────────────────────
    g.add_node("guardrails", guardrails_node)
    g.add_node("supervisor", supervisor_node)
    g.add_node("example_agent", example_agent_node)
    g.add_node("human_review", human_review_node)
    g.add_node("respond_and_wait", _respond_and_wait_node)
    g.add_node("error_handler", _error_node)

    # ── Entry ─────────────────────────────────────────────────────────────────
    g.set_entry_point("guardrails")
    g.add_edge("guardrails", "supervisor")

    # ── Supervisor conditional routing ────────────────────────────────────────
    g.add_conditional_edges(
        "supervisor",
        next_agent,
        {
            "example_agent": "example_agent",
            "human_review": "human_review",
            "respond_and_wait": "respond_and_wait",
            "error_handler": "error_handler",
        },
    )

    # ── Specialists loop back to the supervisor ───────────────────────────────
    for node in ("example_agent", "error_handler"):
        g.add_edge(node, "supervisor")

    # ── Terminal nodes ────────────────────────────────────────────────────────
    g.add_edge("human_review", END)
    g.add_edge("respond_and_wait", END)
    return g


compiled_graph = build_graph().compile()
