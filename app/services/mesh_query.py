"""Run the mesh query flow and shape its response. Used by /api/v1/mesh/query, /api/v1/context/ask and the MCP gateway."""
from __future__ import annotations

from contracts.evidence import SCHEMA_VERSION
from services.neuralmesh import MeshOrchestrator, build_mesh_graph, new_trace_id

_COMPILED: dict[int, tuple[MeshOrchestrator, object]] = {}


def graph_for(orchestrator: MeshOrchestrator):
    """The compiled LangGraph flow for one orchestrator, built once."""
    entry = _COMPILED.get(id(orchestrator))
    if entry is None or entry[0] is not orchestrator:
        entry = (orchestrator, build_mesh_graph(orchestrator))
        _COMPILED[id(orchestrator)] = entry
    return entry[1]


graph_for.cache_clear = _COMPILED.clear  # type: ignore[attr-defined]


async def run_query(graph, *, question: str, purpose: str, nodes: list[str] | None, mode: str | None, as_of: str | None,
                    user_assertion: str, company: str, roles: list[str]) -> dict:
    """Run the full flow and shape the response. Shared by /mesh/query and the SkillForge context API.
    evidence, also_found and withheld are evidence records, relationships have the RelationshipRef shape.
    node_results and sources are the nodes' own search output, kept for the Ask page."""
    trace_id = new_trace_id()
    result = await graph.ainvoke({
        "question": question, "nodes": nodes, "purpose": purpose, "mode": mode, "as_of": as_of,
        "user_assertion": user_assertion, "company": company, "roles": roles, "trace_id": trace_id,
    })
    answer = result.get("answer", {})
    links = result.get("relationships", {})
    return {
        "schema_version": SCHEMA_VERSION,
        "question": result.get("question", question),
        "purpose": purpose,
        "status": result.get("status", "partial"),
        "answer": answer.get("text"),
        "answer_status": answer.get("status", "evidence_only"),
        "answer_reason": answer.get("reason"),
        "citations": answer.get("citations", []),
        "checks": answer.get("checks", []),
        "cached": answer.get("cached", False),
        "routing": result.get("routing", {}),
        "evidence": result.get("records", []),
        "also_found": result.get("scope", {}).get("also_found", []),
        "relationships": links.get("used", []),
        "proposed_relationships": links.get("proposed", []),
        "omitted": result.get("context", {}).get("omitted", 0),
        "model_calls": result.get("model_calls", []),
        "trace_id": trace_id,
        "node_results": result.get("node_results", []),
        "sources": result.get("sources", []),
        "withheld": result.get("withheld_records", []),
    }


