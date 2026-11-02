"""Authenticated cross-subsidiary query endpoint."""
from __future__ import annotations

import asyncio
import json
from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth import require_user
from api.schemas.mesh import MeshQueryRequest, MeshQueryResponse
from mcp_nodes.access_store import AccessStore
from mcp_nodes.server import load_node_config
from services.neuralmesh import NODE_IDS, MeshOrchestrator, build_mesh_graph, create_orchestrator
from shared.config import get_settings

router = APIRouter()
_bearer = HTTPBearer(auto_error=True)


@lru_cache
def _graph():
    return build_mesh_graph(create_orchestrator(get_settings()))


@lru_cache
def _orchestrator() -> MeshOrchestrator:
    return create_orchestrator(get_settings())


class ExpertSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    purpose: Literal["problem_solving", "compliance", "bid_support"] = "problem_solving"
    nodes: list[str] = Field(default_factory=lambda: list(NODE_IDS), min_length=1, max_length=4)


class IntroRequest(BaseModel):
    expert_id: str
    purpose: Literal["problem_solving", "compliance", "bid_support"] = "problem_solving"
    justification: str = Field(min_length=10, max_length=500)


class ApprovalReviewRequest(BaseModel):
    decision: Literal["approve", "deny"]
    hours: int = Field(default=24, ge=1, le=168)


@router.post("/query", response_model=MeshQueryResponse)
async def query_mesh(
    request: MeshQueryRequest,
    user: dict = Depends(require_user),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> MeshQueryResponse:
    if not set(request.nodes).issubset(NODE_IDS):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown subsidiary node")
    try:
        result = await _graph().ainvoke(
            {
                "question": request.question,
                "nodes": request.nodes,
                "purpose": request.purpose,
                "mode": request.mode,
                "as_of": request.as_of.isoformat() if request.as_of else None,
                "user_assertion": credentials.credentials,
            }
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return MeshQueryResponse(
        question=request.question,
        purpose=request.purpose,
        status=result.get("status", "partial"),
        node_results=result.get("node_results", []),
        sources=result.get("sources", []),
        withheld=result.get("withheld", []),
    )


@router.get("/nodes")
async def list_mesh_nodes(
    user: dict = Depends(require_user),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    purpose = "problem_solving"

    async def inspect_node(node_id: str) -> dict:
        try:
            health, capabilities = await asyncio.gather(
                _orchestrator().call_node_tool(credentials.credentials, node_id, "health", {}),
                _orchestrator().call_node_tool(
                    credentials.credentials,
                    node_id,
                    "describe_capabilities",
                    {"purpose": purpose},
                ),
            )
            config = load_node_config(node_id)
            return {
                "node_id": node_id,
                "company": config.display,
                "status": health.get("status", "unknown"),
                "level": config.level,
                "port": config.port,
                "schema_version": capabilities.get("schema_version", config.schema_version),
                "datapoint_count": len(capabilities.get("datapoints", [])),
                "datapoints": capabilities.get("datapoints", []),
                "owner": "Subsidiary operated",
            }
        except Exception as exc:
            config = load_node_config(node_id)
            return {
                "node_id": node_id,
                "company": config.display,
                "status": "unavailable",
                "level": config.level,
                "port": config.port,
                "schema_version": config.schema_version,
                "datapoint_count": len(config.datapoints),
                "datapoints": [],
                "owner": "Subsidiary operated",
                "error": str(exc),
            }

    nodes = await asyncio.gather(*(inspect_node(node_id) for node_id in NODE_IDS))
    return {"nodes": nodes}


@router.post("/experts/search")
async def search_experts(
    request: ExpertSearchRequest,
    user: dict = Depends(require_user),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    if not set(request.nodes).issubset(NODE_IDS) or len(set(request.nodes)) != len(request.nodes):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid or duplicate subsidiary node")

    async def search_node(node_id: str) -> dict:
        try:
            result = await _orchestrator().call_node_tool(
                credentials.credentials,
                node_id,
                "find_experts",
                {"query": request.query, "purpose": request.purpose},
            )
            return {"node_id": node_id, "status": "ok", "experts": result.get("experts", [])}
        except Exception:
            return {"node_id": node_id, "status": "unavailable", "experts": []}

    nodes = await asyncio.gather(*(search_node(node_id) for node_id in request.nodes))
    experts = [
        {**expert, "node_id": result["node_id"]}
        for result in nodes
        for expert in result["experts"]
    ]
    experts.sort(key=lambda expert: (-int(expert.get("match_score", 0)), str(expert.get("company", ""))))
    return {"nodes": nodes, "experts": experts}


@router.post("/experts/{node_id}/intro")
async def request_expert_intro(
    node_id: str,
    request: IntroRequest,
    user: dict = Depends(require_user),
    credentials: HTTPAuthorizationCredentials = Depends(_bearer),
) -> dict:
    if node_id not in NODE_IDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown subsidiary node")
    try:
        return await _orchestrator().call_node_tool(
            credentials.credentials,
            node_id,
            "request_access",
            {
                "datapoint_id": "F-04",
                "mode": "INTRO",
                "purpose": request.purpose,
                "justification": request.justification,
                "kind": "intro",
                "expert_id": request.expert_id,
            },
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "The subsidiary node is unavailable") from exc


def _node_stores() -> list[tuple[str, AccessStore]]:
    return [
        (node_id, AccessStore(config.grants_path, config.audit_path, config))
        for node_id in NODE_IDS
        for config in [load_node_config(node_id)]
    ]


@router.get("/governance")
async def governance_snapshot(user: dict = Depends(require_user)) -> dict:
    nodes = []
    recent_audit = []
    for node_id, store in _node_stores():
        config = load_node_config(node_id)
        for request in store.pending():
            datapoint = config.datapoints.get(request["datapoint_id"], {})
            nodes.append({
                **request,
                "node_id": node_id,
                "company": config.display,
                "title": datapoint.get("title", request["datapoint_id"]),
                "owner_role": datapoint.get("owner_role", "Node owner"),
            })
        if store.audit_path.exists():
            try:
                lines = store.audit_path.read_text(encoding="utf-8").splitlines()
                for line in lines[-40:]:
                    entry = json.loads(line)
                    recent_audit.append({
                        "timestamp": entry.get("timestamp"),
                        "trace_id": entry.get("trace_id"),
                        "node_id": node_id,
                        "caller_sub": entry.get("caller_sub"),
                        "caller_company": entry.get("caller_company"),
                        "action": entry.get("action"),
                        "datapoint_id": entry.get("datapoint_id"),
                        "decision": entry.get("decision"),
                        "rule_id": entry.get("rule_id"),
                        "request_id": entry.get("request_id"),
                        "grant_id": entry.get("grant_id"),
                    })
            except (OSError, ValueError, json.JSONDecodeError):
                continue
    nodes.sort(key=lambda item: item["requested_at"])
    recent_audit.sort(key=lambda item: item.get("timestamp") or "", reverse=True)
    return {"pending": nodes, "audit": recent_audit[:100], "mode": "development_poc"}


@router.post("/governance/{node_id}/requests/{request_id}/review")
async def review_access_request(
    node_id: str,
    request_id: str,
    request: ApprovalReviewRequest,
    user: dict = Depends(require_user),
) -> dict:
    settings = get_settings()
    email = str(user.get("email", ""))
    if settings.app_env != "development" or not email.endswith("@neuralmesh.local"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "POC owner review is restricted to local demo accounts")
    if node_id not in NODE_IDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown subsidiary node")

    config = load_node_config(node_id)
    store = AccessStore(config.grants_path, config.audit_path, config)
    pending = next((item for item in store.pending() if item["request_id"] == request_id), None)
    if pending is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pending request not found")
    datapoint = config.datapoints.get(pending["datapoint_id"], {})
    owner_role = str(datapoint.get("owner_role", ""))
    try:
        result = store.review(request_id, owner_role, request.decision, hours=request.hours)
        audit_event = result.pop("audit_event", None)
        if audit_event:
            store.append_event(audit_event)
        return {**result, "reviewed_by": email, "simulated_owner_role": owner_role}
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.get("/admin")
async def admin_snapshot(user: dict = Depends(require_user), credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    nodes = await list_mesh_nodes(user, credentials)
    settings = get_settings()
    return {
        "registry": nodes["nodes"],
        "ontology": [
            {"concept": "Root-cause analysis", "aliases": ["RCA", "8D", "CAPA", "post-mortem"]},
            {"concept": "Integration lessons", "aliases": ["playbook", "day-100 review", "post-mortem"]},
            {"concept": "Materials handling", "aliases": ["storage", "lot acceptance", "traceability"]},
        ],
        "guardrails": [
            {"id": "node_policy", "label": "Node-side policy enforcement", "enabled": True},
            {"id": "citation_required", "label": "Citations on returned evidence", "enabled": True},
            {"id": "prompt_injection_flag", "label": "Flag instruction-like source text", "enabled": True},
            {"id": "source_migration", "label": "Source record migration", "enabled": False},
        ],
        "model": settings.neuralmesh_groq_model,
        "groq_configured": bool(settings.neuralmesh_groq_api_key),
        "orchestrator_stage": "parallel_mcp_evidence_fanout",
    }


@router.get("/dashboard")
async def dashboard_snapshot(user: dict = Depends(require_user), credentials: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    nodes = await list_mesh_nodes(user, credentials)
    governance = await governance_snapshot(user)
    audit = governance["audit"]
    searches = [entry for entry in audit if entry.get("action") == "search"]
    allowed = sum(entry.get("decision") in {"ALLOWED", "ALLOWED_SUMMARY_ONLY"} for entry in searches)
    blocked = sum(entry.get("decision") == "BLOCKED_BY_POLICY" for entry in searches)
    activity_by_node = {
        node_id: sum(entry.get("node_id") == node_id and entry.get("action") == "search" for entry in audit)
        for node_id in NODE_IDS
    }
    return {
        "nodes": nodes["nodes"],
        "connected_nodes": sum(node["status"] == "healthy" for node in nodes["nodes"]),
        "total_nodes": len(nodes["nodes"]),
        "search_decisions": len(searches),
        "allowed_decisions": allowed,
        "blocked_decisions": blocked,
        "pending_approvals": len(governance["pending"]),
        "activity_by_node": activity_by_node,
        "recent_activity": audit[:8],
        "synthetic": True,
    }