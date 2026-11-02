"""Supervisor node — decides which specialist agent runs next.

The accelerator uses a supervisor-loop: every specialist node returns to the
supervisor, which picks the next node (or a terminal node) until the turn is
done. This baseline uses a simple rule; swap in an LLM router for real apps
(see ``get_system_prompt("supervisor")``).
"""
from __future__ import annotations

from agents.state import AgentState

# Per-turn step budget — prevents infinite supervisor loops.
_MAX_STEPS_PER_TURN = 6


def supervisor_node(state: AgentState) -> AgentState:
    """Increment the turn budget and record intent. Real apps call the LLM here."""
    state["turn_count"] = state.get("turn_count", 0) + 1
    state.setdefault("current_step", "supervisor")
    return state


def next_agent(state: AgentState) -> str:
    """Conditional-edge router. Returns the name of the next node."""
    # Escalation short-circuits everything.
    if state.get("human_review_reason"):
        return "human_review"

    # Stop after the step budget to hand control back to the user.
    if state.get("turn_count", 0) >= _MAX_STEPS_PER_TURN:
        return "respond_and_wait"

    # Baseline: run the example agent once, then respond.
    if state.get("step_status") == "completed":
        return "respond_and_wait"

    return "example_agent"
