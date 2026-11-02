"""Example specialist node — copy this to build real agents.

Pattern: read state -> (optionally) call the LLM with a YAML-sourced system
prompt -> write results back into state -> return. The node never decides
routing; it just does its job and returns to the supervisor.
"""
from __future__ import annotations

from agents.state import AgentState
from shared.logger import get_logger
from shared.prompt_loader import get_system_prompt

log = get_logger("agents.example_agent")


def example_agent_node(state: AgentState) -> AgentState:
    user_msg = ""
    for m in reversed(state.get("messages", [])):
        if m.get("role") == "user":
            user_msg = m.get("content", "")
            break

    # ── Real apps: call the LLM ──────────────────────────────────────────────────
    # from langchain_core.messages import SystemMessage, HumanMessage
    # from shared.llm import get_llm
    # system = get_system_prompt("example_agent")
    # reply = get_llm(max_tokens=512).invoke(
    #     [SystemMessage(content=system), HumanMessage(content=user_msg)]
    # ).content
    system = get_system_prompt("example_agent") or "You are a helpful assistant."
    reply = f"[example_agent] received: {user_msg!r}. (System prompt loaded: {bool(system)})"

    state.setdefault("collected", {})["example_result"] = reply
    state.setdefault("messages", []).append(
        {"role": "assistant", "agent": "example_agent", "content": reply}
    )
    state["current_step"] = "example_agent"
    state["step_status"] = "completed"
    log.info("example_agent.done", session_id=state.get("session_id"))
    return state
