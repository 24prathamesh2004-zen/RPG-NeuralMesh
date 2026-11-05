"""Authenticated cross-subsidiary query endpoint."""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth import require_user
from api.schemas.mesh import MeshQueryRequest, MeshQueryResponse
from mcp_nodes.access_store import AccessStore
from mcp_nodes.server import load_node_config
from api.schemas.mesh import check_node_list
from services import mesh_query
from services.mesh_runtime import runtime
from services.neuralmesh import NODE_IDS, MeshOrchestrator
from shared.config import get_settings
from shared.registry import registered_nodes

router = APIRouter()
_bearer = HTTPBearer(auto_error=True)


Purpose = Literal["problem_solving", "compliance", "bid_support", "learning", "career_mobility"]


def _graph():
    return mesh_query.graph_for(runtime().orchestrator)


def _orchestrator() -> MeshOrchestrator:
    return runtime().orchestrator


_graph.cache_clear = mesh_query.graph_for.cache_clear  # tests reset the compiled graph through the router


async def run_query(**kwargs) -> dict:
    return await mesh_query.run_query(_graph(), **kwargs)


class ExpertSearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=500)
    purpose: Purpose = "problem_solving"
    nodes: list[str] = Field(default_factory=lambda: list(NODE_IDS), min_length=1, max_length=16)


class IntroRequest(BaseModel):
    expert_id: str
    purpose: Purpose = "problem_solving"
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
    try:
        result = await run_query(
            question=request.question, purpose=request.purpose, nodes=request.nodes, mode=request.mode,
            as_of=request.as_of.isoformat() if request.as_of else None, user_assertion=credentials.credentials,
            company=str(user.get("company", "")), roles=list(user.get("roles", [])),
        )
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return MeshQueryResponse(**result)


@router.get("/routing")
async def preview_routing(q: str, user: dict = Depends(require_user)) -> dict:
    """Resolve and route a question on the graph only, without calling any node."""
    mesh = runtime().mesh
    resolved = mesh.resolve(q)
    route = mesh.route(set(resolved["concepts"]), set(resolved["named_subsidiaries"]))
    return {
        "concepts": [{"id": c, "label": mesh.label(c), "matched": m} for c, m in resolved["concepts"].items()],
        "fallback": "none" if (resolved["concepts"] or resolved["named_subsidiaries"]) else "classifier, then the user's own choice",
        "named_subsidiaries": resolved["named_subsidiaries"],
        "subsidiaries": sorted(route["subsidiaries"]),
        "narrowed_out": sorted(route["narrowed_out"]),
        "datapoints": sorted(route["datapoints"]),
        "documents": sorted(route["docs"]),
    }


@router.get("/graph")
async def graph_view(user: dict = Depends(require_user)) -> dict:
    rt = runtime()
    return {**rt.mesh.view(), "store": rt.store.counts(), "exports": rt.export_status, "group_packs": rt.group_packs}


@router.post("/graph/refresh")
async def graph_refresh(user: dict = Depends(require_user)) -> dict:
    rt = runtime()
    exports = await rt.refresh_from_nodes()
    return {"exports": exports, "store": rt.store.counts(), "counts": rt.mesh.view()["counts"]}


@router.get("/graph/links")
async def graph_links(user: dict = Depends(require_user)) -> dict:
    return {"links": runtime().mesh.links()}


class LinkReviewRequest(BaseModel):
    subsidiary: str
    decision: Literal["approve", "reject"]


@router.post("/graph/links/{rel_id:path}/review")
async def review_link(rel_id: str, request: LinkReviewRequest, user: dict = Depends(require_user)) -> dict:
    """Owner-side review of a link between subsidiaries. POC: simulated for local demo accounts only."""
    settings = get_settings()
    email = str(user.get("email", ""))
    if settings.app_env != "development" or not email.endswith("@neuralmesh.local"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "POC owner review is restricted to local demo accounts")
    rt = runtime()
    link = next((item for item in rt.mesh.links() if item["id"] == rel_id), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    if request.subsidiary not in link["sides"]:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "That subsidiary is not a side of this link")
    end = link["source"] if link["source"].startswith(request.subsidiary + ":") else link["target"]
    owner_role = (rt.mesh.graph.nodes.get(rt.mesh.graph.nodes[end].get("datapoint", ""), {}) or {}).get("owner") or "Datapoint owner"
    rt.store.review_link(rel_id, request.subsidiary, owner_role, request.decision, email)
    rt.mesh.rebuild()
    updated = next(item for item in rt.mesh.links() if item["id"] == rel_id)
    return {**updated, "simulated_owner_role": owner_role}


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
                "packs": capabilities.get("packs", []),
                "profile": capabilities.get("profile", ""),
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
    try:
        check_node_list(request.nodes)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid or duplicate subsidiary node") from exc

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
    graph = _graph_for_admin()
    return {
        "registry": nodes["nodes"],
        "ontology": graph["ontology"],
        "graph_counts": graph["counts"],
        "guardrails": [
            {"id": "node_policy", "label": "Node-side policy enforcement", "enabled": True},
            {"id": "citation_required", "label": "Citations on returned evidence", "enabled": True},
            {"id": "prompt_injection_flag", "label": "Flag instruction-like source text", "enabled": True},
            {"id": "source_migration", "label": "Source record migration", "enabled": False},
        ],
        "model": settings.neuralmesh_groq_model,
        "groq_configured": bool(settings.neuralmesh_groq_api_key),
        "orchestrator_stage": "resolve_route_fanout_scope_expand_build_answer_check",
        "model_policy": _model_policy_summary(settings.app_env),
    }


def _graph_for_admin() -> dict:
    try:
        mesh = runtime().mesh
    except Exception:  # noqa: BLE001 - the admin page still shows the registry
        return {"ontology": [], "counts": {}}
    ontology = [
        {"concept": data.get("label"), "id": n, "aliases": data.get("aliases") or []}
        for n, data in mesh.graph.nodes(data=True) if data.get("type") == "Concept"
    ]
    return {"ontology": sorted(ontology, key=lambda o: o["concept"] or ""), "counts": mesh.view()["counts"]}


def _model_policy_summary(app_env: str) -> dict:
    from services.context import policy as model_policy

    steps = {}
    for step in ("answer", "rerank", "classify"):
        choice = model_policy.choice_for(step)
        steps[step] = {"model": choice.model, "tier": choice.tier, "max_input_tokens": choice.max_input_tokens}
    return {"strict_mode": model_policy.strict_mode(app_env), "steps": steps,
            "answer_model_ready": runtime().orchestrator.backend is not None}


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