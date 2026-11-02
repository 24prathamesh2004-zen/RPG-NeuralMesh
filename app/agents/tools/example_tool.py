"""Example tool — wrap external calls / deterministic logic as LangChain tools.

Tools keep side-effects and I/O out of agent nodes and make them testable and
traceable. Register real tools with your LLM via ``.bind_tools([...])``.
"""
from __future__ import annotations

from langchain_core.tools import tool


@tool
def example_lookup(query: str) -> str:
    """Look up a value for the given query. Replace with a real integration
    (DB query, REST call, vector search, ...)."""
    return f"result-for:{query}"
