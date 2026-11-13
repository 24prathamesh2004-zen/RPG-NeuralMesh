"""Authenticated cross-subsidiary query endpoint."""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api.auth import require_role, require_user
from api.schemas.mesh import MeshQueryRequest, MeshQueryResponse
from mcp_nodes.access_store import AccessStore
from mcp_nodes.server import load_node_config
from api.schemas.mesh import check_node_list
from services import mesh_query
from services.mesh_runtime import runtime
from services.neuralmesh import NODE_IDS, MeshOrchestrator
from shared.config import get_settings
from shared.registry import node as registered_node, node_ids
from services import export_formats

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
    mesh = (await asyncio.to_thread(runtime)).mesh
    resolved = await asyncio.to_thread(mesh.resolve, q)
    route = mesh.route(set(resolved["concepts"]), set(resolved["named_subsidiaries"]))
    return {
        "concepts": [{"id": c, "label": mesh.label(c), "matched": m} for c, m in resolved["concepts"].items()],
        "fallback": "none" if (resolved["concepts"] or resolved["named_subsidiaries"]) else "classifier, then the asker's own company, then the asker's own choice",
        "named_subsidiaries": resolved["named_subsidiaries"],
        "subsidiaries": sorted(route["subsidiaries"]),
        "narrowed_out": sorted(route["narrowed_out"]),
        "datapoints": sorted(route["datapoints"]),
        "documents": sorted(route["docs"]),
    }


@router.get("/graph")
async def graph_view(user: dict = Depends(require_user)) -> dict:
    rt = await asyncio.to_thread(runtime)
    reports = {s: {"nodes": r.nodes, "edges": r.edges, "warnings": len(r.warnings), "retired_edges": r.retired_edges,
                   "retired_nodes": r.retired_nodes} for s, r in rt.mesh.last_reports.items()}
    return {**_view_for(rt, user), "store": rt.store.counts(), "exports": rt.export_status, "group_packs": rt.group_packs,
            "revision": rt.store.revision(), "checks": rt.mesh.checks, "reports": reports}


def _person(user: dict) -> tuple[str, list[str]]:
    return str(user.get("company", "")), list(user.get("roles", []))


def _view_for(rt, user: dict) -> dict:
    """The graph view without the entities of never-leave datapoints of other companies (mesh admins see all)."""
    company, roles = _person(user)
    view = rt.mesh.view()
    nodes = [n for n in view["nodes"] if rt.mesh.shown_to(n["id"], company, roles)]
    shown = {n["id"] for n in nodes}
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    return {"nodes": nodes, "edges": [e for e in view["edges"] if e["source"] in shown and e["target"] in shown], "counts": counts}


@router.post("/graph/refresh")
async def graph_refresh(user: dict = Depends(require_role("mesh_admin"))) -> dict:
    rt = await asyncio.to_thread(runtime)
    exports = await rt.refresh_from_nodes()
    return {"exports": exports, "store": rt.store.counts(), "counts": rt.mesh.view()["counts"], "revision": rt.store.revision(),
            "checks": rt.mesh.checks}


@router.get("/domains")
async def graph_domains(user: dict = Depends(require_user)) -> dict:
    """The layers of the graph: each domain's node types and edge types with live counts and link statuses."""
    rt = await asyncio.to_thread(runtime)
    revision = rt.mesh.loaded_revision  # the revision of the graph the view reads, not of the store
    cached = _DOMAINS_CACHE.get("value")
    if cached and cached[0] == revision:
        return cached[1]
    result = await asyncio.to_thread(_domains_view, rt)
    _DOMAINS_CACHE["value"] = (revision, result)
    return result


_DOMAINS_CACHE: dict[str, tuple] = {}


def _domains_view(rt) -> dict:
    from services.ontology import ontology

    g = rt.mesh.graph
    rules = ontology()
    node_counts: dict[str, int] = {}
    for _, d in g.nodes(data=True):
        if not d.get("retired") and d.get("type") != "Unknown":
            node_counts[d["type"]] = node_counts.get(d["type"], 0) + 1
    edge_counts: dict[str, dict[str, int]] = {}
    for _, _, d in g.edges(data=True):
        if d["status"] != "retired":
            edge_counts.setdefault(d["type"], {}).setdefault(d["status"], 0)
            edge_counts[d["type"]][d["status"]] += 1
    domains = []
    for name in rules.domains:
        nts = [{"type": t, "count": node_counts.get(t, 0), "description": spec.get("description", "")}
               for t, spec in rules.node_types.items() if spec.get("domain") == name]
        ets = [{"type": et.name, "from": sorted(et.from_types), "to": sorted(et.to_types), "group": et.group, "symmetric": et.symmetric,
                "counts": edge_counts.get(et.name, {})} for et in rules.edge_types.values() if et.domain == name]
        domains.append({"domain": name, "node_types": nts, "edge_types": ets,
                        "entities": sum(n["count"] for n in nts), "links": sum(sum(c.values()) for e in ets for c in [e["counts"]])})
    sources = {s: {"nodes": r.nodes, "edges": r.edges, "warnings": len(r.warnings)} for s, r in rt.mesh.last_reports.items()}
    return {"domains": domains, "groups": {k: sorted(v) for k, v in rules.groups.items()}, "sources": sources, "revision": rt.store.revision(), "checks": rt.mesh.checks}


@router.get("/applications")
async def applications(user: dict = Depends(require_user)) -> dict:
    """The applications connected to the mesh, read from their registry files (config/applications): what each may
    call, what it loaded into the graph and the numbers its file asks for."""
    from services import applications as registry
    from services.context_import import _read_log
    from services import context_api
    rt = await asyncio.to_thread(runtime)
    g = rt.mesh.graph
    reports = rt.mesh.last_reports
    kept = _read_log(context_api.TALENT_IMPORT)

    def matches(source: str, pattern: str) -> bool:
        return source == pattern or source.startswith(pattern if pattern.endswith(":") else pattern + "/")

    def loaded(app) -> dict:
        items = {s: r for s, r in reports.items() if any(matches(s, p) for p in app.graph_sources)}
        return {"sources": sorted(items), "entities": sum(r.nodes for r in items.values()), "links": sum(r.edges for r in items.values()),
                "warnings": sum(len(r.warnings) for r in items.values())}

    def fact(spec: dict):
        if "count" in spec:
            return sum(1 for _, d in g.nodes(data=True) if d.get("type") == spec["count"] and not d.get("retired"))
        if "edges" in spec:
            return sum(1 for _, _, d in g.edges(data=True) if d["type"] == spec["edges"] and d["status"] != "retired")
        if "latest" in spec:
            return max((d.get(spec.get("field", "at")) or "" for _, d in g.nodes(data=True)
                        if d.get("type") == spec["latest"] and not d.get("retired")), default=None) or None
        if "proposed_from" in spec:
            return sum(1 for _, _, d in g.edges(data=True) if d["status"] == "proposed" and d.get("source", "").startswith(spec["proposed_from"]))
        return None

    sends = rt.store.sends()

    def imports(app) -> dict:
        """The packs the application sends: how many are kept, when one last changed the graph, its latest send (the
        packs of the newest time) and every pack whose latest result is a refusal, with the reason."""
        mine = [v for v in kept.values() if v.get("by") == app.id]
        rows = sends.get(app.id, [])
        latest = max((r["at"] for r in rows), default=None)
        last = [r for r in rows if r["at"] == latest]
        return {"kept": len(mine), "last_loaded_at": max((v.get("at") or "" for v in mine), default="") or None,
                "last_send": {"at": latest, **{word: sum(1 for r in last if r["result"] == word) for word in ("loaded", "unchanged", "refused")}}
                if latest else None,
                "refused": [{"pack_id": r["pack_id"], "at": r["at"], "reason": r["reason"]} for r in rows if r["result"] == "refused"]}

    out = []
    for app in registry.applications().values():
        facts = {name: fact(spec) for name, spec in app.facts.items()}
        out.append({**app.card(), "loaded": loaded(app), "facts": facts, **({"imports": imports(app)} if app.imports else {})})
    return {"applications": out, "revision": rt.store.revision()}


@router.get("/graph/links")
async def graph_links(user: dict = Depends(require_user)) -> dict:
    mesh_graph = (await asyncio.to_thread(runtime)).mesh
    company, roles = _person(user)
    return {"links": [link for link in mesh_graph.links()
                      if mesh_graph.shown_to(link["source"], company, roles) and mesh_graph.shown_to(link["target"], company, roles)]}


class LinkReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    subsidiary: str | None = None  # ignored: the side is the reviewer's own company, from the token


@router.post("/graph/links/{rel_id:path}/review")
async def review_link(rel_id: str, request: LinkReviewRequest, user: dict = Depends(require_user)) -> dict:
    """Owner-side review of a link between subsidiaries. POC: simulated for local demo accounts only."""
    settings = get_settings()
    email = str(user.get("email", ""))
    if settings.app_env != "development" or not email.endswith("@neuralmesh.local"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "POC owner review is restricted to local demo accounts")
    rt = await asyncio.to_thread(runtime)
    link = next((item for item in rt.mesh.links() if item["id"] == rel_id), None)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Link not found")
    side = str(user.get("company", ""))
    if side not in link["sides"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, f"Only an owner of a side may review this link, and {side} is not a side of it")
    end = link["source"] if link["source"].startswith(side + ":") else link["target"]
    owner_role = (rt.mesh.graph.nodes.get(rt.mesh.graph.nodes[end].get("datapoint", ""), {}) or {}).get("owner") or "Datapoint owner"
    rt.store.review_link(rel_id, side, owner_role, request.decision, email)
    await asyncio.to_thread(rt.mesh.rebuild)
    updated = next(item for item in rt.mesh.links() if item["id"] == rel_id)
    return {**updated, "simulated_owner_role": owner_role}


@router.get("/proposals")
async def application_proposals(user: dict = Depends(require_user)) -> dict:
    """The entries applications proposed for the graph, grouped by application and link type. Each entry names the
    sides that approve it: a company for its own entities, the group for the application's own vocabulary (a mesh admin
    approves as curator). An entry is approved when every side approved it, and rejected when one side rejected it."""
    from services import applications as registry
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    yours = _sides_of(company, roles)
    names = {a.id: a.name for a in registry.applications().values()}
    groups: dict[tuple[str, str], dict] = {}
    for p in rt.mesh.proposals():
        if not (rt.mesh.shown_to(p["source"], company, roles) and rt.mesh.shown_to(p["target"], company, roles)):
            continue
        group = groups.setdefault((p["application"], p["type"]), {
            "application": p["application"], "name": names.get(p["application"], p["application"]), "type": p["type"],
            "counts": {"proposed": 0, "approved": 0, "rejected": 0}, "sides": set(), "pending_for_you": 0, "entries": [],
            "from_types": set(), "to_types": set()})
        group["counts"][p["status"]] = group["counts"].get(p["status"], 0) + 1
        group["sides"] |= set(p["sides"])
        group["from_types"].add(p.get("source_type") or "Unknown")
        group["to_types"].add(p.get("target_type") or "Unknown")
        mine = sorted((set(p["sides"]) & yours) - set(p["reviewed_by"])) if p["status"] == "proposed" else []
        group["pending_for_you"] += 1 if mine else 0
        group["entries"].append({k: p[k] for k in ("id", "source", "target", "source_title", "target_title", "status", "sides", "reviewed_by")}
                                | {"you_review": mine})
    out = [{**g, "sides": sorted(g["sides"]), "from_types": sorted(g["from_types"]), "to_types": sorted(g["to_types"])} for g in groups.values()]
    return {"groups": sorted(out, key=lambda g: (g["name"], g["type"])), "your_sides": sorted(yours)}


def _sides_of(company: str, roles: list[str]) -> set[str]:
    from services.graph_store import GROUP_SIDE
    return {company} | ({GROUP_SIDE} if "mesh_admin" in roles else set())


class ProposalReviewRequest(BaseModel):
    decision: Literal["approve", "reject"]
    ids: list[str] = Field(default_factory=list, max_length=2000)  # these entries, or
    application: str | None = None                                 # every pending entry of one application
    type: str | None = None                                        # and one link type


@router.post("/proposals/review")
async def review_proposals(request: ProposalReviewRequest, user: dict = Depends(require_user)) -> dict:
    """Approve or reject application entries for the reviewer's own sides only: their company, and the group when they are
    a mesh admin. POC: simulated for local demo accounts only, like the review of a link between companies."""
    from services.graph_store import GROUP_SIDE, company_of
    settings = get_settings()
    email = str(user.get("email", ""))
    if settings.app_env != "development" or not email.endswith("@neuralmesh.local"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "POC owner review is restricted to local demo accounts")
    if not request.ids and not (request.application and request.type):
        raise HTTPException(422, "Name the entries, or an application and a link type")
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    yours = _sides_of(company, roles)
    wanted = set(request.ids)
    g = rt.mesh.graph
    items: list[tuple[str, str, str]] = []
    for p in rt.mesh.proposals():
        if p["status"] != "proposed" or not (p["id"] in wanted if wanted else (p["application"] == request.application and p["type"] == request.type)):
            continue
        for side in sorted((set(p["sides"]) & yours) - set(p["reviewed_by"])):
            if side == GROUP_SIDE:
                role = "Mesh knowledge curator"
            else:
                end = p["source"] if company_of(g, p["source"]) == side else p["target"]
                data = g.nodes.get(end, {})
                role = (g.nodes.get(data.get("datapoint") or "", {}) or {}).get("owner") or data.get("owner") or "Company reviewer"
            items.append((p["id"], side, role))
    reviewed = rt.store.review_links(items, request.decision, email)
    await asyncio.to_thread(rt.mesh.rebuild)
    return {"reviewed": reviewed, "decision": request.decision}


def _owner_words(node_id: str) -> str:
    return "Shared inputs, read by every connected company" if registered_node(node_id).shared else "Subsidiary operated"


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
                "tone": registered_node(node_id).tone,
                "status": health.get("status", "unknown"),
                "level": config.level,
                "port": config.port,
                "schema_version": capabilities.get("schema_version", config.schema_version),
                "datapoint_count": len(capabilities.get("datapoints", [])),
                "datapoints": capabilities.get("datapoints", []),
                "packs": capabilities.get("packs", []),
                "profile": capabilities.get("profile", ""),
                "owner": _owner_words(node_id),
                "shared": registered_node(node_id).shared,
            }
        except Exception as exc:
            config = load_node_config(node_id)
            return {
                "node_id": node_id,
                "company": config.display,
                "tone": registered_node(node_id).tone,
                "status": "unavailable",
                "level": config.level,
                "port": config.port,
                "schema_version": config.schema_version,
                "datapoint_count": len(config.datapoints),
                "datapoints": [],
                "owner": _owner_words(node_id),
                "shared": registered_node(node_id).shared,
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

    # The concepts of the question, as the mesh resolves them for routing: a node adds them to an expert's score when
    # the expert's evidence covers them, so a question in other words still finds the expert. Resolving may embed the
    # question, so it runs off the event loop.
    mesh = (await asyncio.to_thread(runtime)).mesh
    concepts = sorted((await asyncio.to_thread(mesh.resolve, request.query)).get("concepts", {}))
    company, roles = _person(user)

    async def search_node(node_id: str) -> dict:
        try:
            result = await _orchestrator().call_node_tool(
                credentials.credentials,
                node_id,
                "find_experts",
                {"query": request.query, "purpose": request.purpose, "concepts": concepts},
            )
            return {"node_id": node_id, "status": "ok", "experts": result.get("experts", [])}
        except Exception:
            return {"node_id": node_id, "status": "unavailable", "experts": []}

    def shown(expert: dict) -> dict:
        # evidence is listed by title, and a never-leave document of another company is left out, as in the graph
        evidence = [doc for doc in expert.get("evidence", []) if mesh.shown_to(doc, company, roles)]
        return {**expert, "evidence": evidence, "evidence_titles": [mesh.label(doc) for doc in evidence]}

    # Every expert of the answer passes shown(), in the list of each node as in the flat list, so no never-leave
    # evidence of another company reaches the page by either way.
    nodes = [{**result, "experts": [shown(expert) for expert in result["experts"]]}
             for result in await asyncio.gather(*(search_node(node_id) for node_id in request.nodes))]
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
    company, roles = _person(user)
    for node_id, store in _node_stores():
        config = load_node_config(node_id)

        def datapoint_title(dp_id: str | None, config=config, node_id=node_id) -> str | None:
            # the title of a datapoint in the ledger, except a never-leave one of another company (as in the graph)
            dp = config.datapoints.get(dp_id or "", {})
            if not dp or (dp.get("never_leave") and company != node_id and "mesh_admin" not in roles):
                return None
            return dp.get("title")
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
                        "datapoint_title": datapoint_title(entry.get("datapoint_id")),
                        "datapoint_hidden": bool(config.datapoints.get(entry.get("datapoint_id") or "", {}).get("never_leave"))
                        and datapoint_title(entry.get("datapoint_id")) is None,
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


@router.get("/governance/audit/verify")
async def verify_audit_chains(user: dict = Depends(require_user)) -> dict:
    """Recompute the hash chain of every node's decision ledger. Each entry holds the hash of the one before it, so an
    entry that was changed, added in between or removed breaks the chain from that point on."""
    from mcp_nodes.access_store import verify_audit

    def check(node_id: str) -> dict:
        try:
            config = load_node_config(node_id)
        except Exception:  # noqa: BLE001 - a node whose configuration does not load shows as not checked
            return {"node_id": node_id, "company": registered_node(node_id).display, "entries": 0, "valid": False}
        path = config.audit_path
        try:
            entries = sum(1 for line in path.open(encoding="utf-8") if line.strip()) if path.exists() else 0
            valid = verify_audit(path)
        except (OSError, ValueError, KeyError):
            entries, valid = 0, False
        return {"node_id": node_id, "company": config.display, "entries": entries, "valid": valid}

    company, roles = _person(user)
    visible = list(node_ids()) if "mesh_admin" in roles else [n for n in node_ids() if n == company]  # a ledger's size is the company's own
    nodes = list(await asyncio.gather(*(asyncio.to_thread(check, node_id) for node_id in visible)))
    return {"nodes": nodes, "valid": all(n["valid"] for n in nodes)}


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
    company, roles = _person(user)
    if company != node_id and "mesh_admin" not in roles:
        # A company's owner reviews its own requests. The mesh admin runs the demo and may act for any owner.
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the owning company reviews this request")

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
    graph = await asyncio.to_thread(_graph_for_admin)
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
        "model_policy": await asyncio.to_thread(_model_policy_summary, settings.app_env),
        "orchestrator_stage": "resolve_route_fanout_scope_expand_build_answer_check",
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
        "ingested_graphs": len(await asyncio.to_thread(_ingested_records)),  # graphs a person wrote as JSON, kept by the central service
    }


def _ingested_records() -> list:
    from services import context_graph_ingest
    return context_graph_ingest.records()

# ── Uploaded inputs and graph search (plan: RPG_NeuralMesh_Knowledge_Contribution_and_Graph_Search_Plan.md) ──────────


@router.get("/uploads")
async def list_uploads(user: dict = Depends(require_user)) -> dict:
    """The uploaded documents the person may see, newest first, each with its item's sharing rule, its context graph and
    whether it is in the graph now, and the context graphs they form. A mesh admin sees every company's, anyone else
    their own company's and the shared node's."""
    from services import uploads
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    items = await asyncio.to_thread(uploads.list_uploads, rt, company, roles)
    return {"uploads": items, "graphs": uploads.graphs_of(items), "kinds": uploads.KINDS, "formats": sorted(uploads.FORMATS),
            "export_formats": export_formats.ids(), "export_format_list": export_formats.listing()}


@router.get("/uploads/json-templates")
async def json_template_of_graph(graph_id: str = "", user: dict = Depends(require_user)) -> dict:
    """The output template of a context graph: its own when one was kept with it, else the suggested one. Without
    ``graph_id`` the suggested template, for a graph that does not exist yet. ``fields`` are the values a template may use."""
    from services import json_templates, uploads
    if graph_id:
        rt = await asyncio.to_thread(runtime)
        company, roles = _person(user)
        try:
            await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
        except KeyError:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No input of this context graph is shown to you") from None
    template, own = json_templates.of_graph(graph_id)
    return {"template": template, "own": own, "suggested": json_templates.DEFAULT, "fields": json_templates.FIELDS,
            "can_change": json_templates.per_graph()}  # false: the standard structure for every graph, shown read-only on the form


@router.put("/uploads/graphs/{graph_id}/template")
async def set_json_template_of_graph(graph_id: str, body: dict, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Keep an output template with a context graph. Every later output of the graph follows it. The reason is returned
    when the template is refused."""
    from services import json_templates, uploads
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    try:
        await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
        template, own = await asyncio.to_thread(json_templates.set_for_graph, graph_id, body.get("template"), str(user.get("email") or user.get("sub") or ""))
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No input of this context graph is shown to you") from None
    except json_templates.TemplateRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"template": template, "own": own}


@router.post("/uploads/json-templates/render")
async def json_templates_render(body: dict, user: dict = Depends(require_user)) -> dict:
    """A context graph in a structured JSON template, as the person may see it. With ``template`` for the preview of an
    edited one, without it in the template kept with the graph."""
    from services import json_templates
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    graph_id = str(body.get("graph_id", ""))
    try:
        data = await asyncio.to_thread(json_templates.data_of, rt, graph_id, company, roles)
        template = body["template"] if body.get("template") is not None else json_templates.of_graph(graph_id)[0]
        return {"output": json_templates.render(template, data)}
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No input of this context graph is shown to you") from None
    except json_templates.TemplateRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/uploads/suggest")
async def suggest_upload(file: UploadFile = File(...), node_id: str = Form(""), datapoint: str = Form(""),
                         user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Read a file without keeping it and return what the Add input form fills in: title, tags, kind, concepts and the
    context graph it fits (append to an existing one, or a new one with a name)."""
    from services import uploads
    rt = await asyncio.to_thread(runtime)
    data = await file.read()
    try:
        return await asyncio.to_thread(uploads.suggest, rt, file.filename or "upload.txt", data, node_id or None, datapoint or None)
    except uploads.UploadRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc


@router.post("/uploads/formats", status_code=status.HTTP_201_CREATED)
async def add_export_format(body: dict, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Keep a download format a mesh admin wrote: a name, a file extension, the escaping, and a header, a line for each
    entity, a line for each link and a footer with placeholders in braces. The reason is returned when it is refused."""
    try:
        item = await asyncio.to_thread(export_formats.save, body, str(user.get("email") or user.get("sub") or ""))
    except export_formats.FormatRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"format": item, "export_format_list": export_formats.listing()}


@router.post("/uploads/formats/file", status_code=status.HTTP_201_CREATED)
async def add_export_format_file(file: UploadFile = File(...), user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Keep an output template a mesh admin uploaded as a text file, read by export_formats.from_text."""
    data = await file.read()
    if len(data) > 20_000:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A template file has at most 20,000 bytes.")
    try:
        text = data.decode("utf-8")
        item = await asyncio.to_thread(export_formats.from_text, file.filename or "template.txt", text, str(user.get("email") or user.get("sub") or ""))
    except UnicodeDecodeError:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A template is a text file in UTF-8.") from None
    except export_formats.FormatRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return {"format": item, "export_format_list": export_formats.listing()}


@router.delete("/uploads/formats/{format_id}")
async def remove_export_format(format_id: str, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Remove a download format a mesh admin added. The built-in formats stay."""
    try:
        await asyncio.to_thread(export_formats.remove, format_id)
    except export_formats.FormatRefused as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    return {"removed": format_id, "export_format_list": export_formats.listing()}


@router.get("/uploads/items/{node_id}")
async def upload_items(node_id: str, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """The catalogue items of a company an upload can go under, with each one's sharing rule."""
    from services import uploads
    if node_id not in NODE_IDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown subsidiary node")
    items = await asyncio.to_thread(uploads.datapoints_of, node_id)
    return {"node_id": node_id, "items": [{"code": code, "title": dp["title"], "ceiling": dp["ceiling"], "never_leave": bool(dp.get("never_leave")),
                                           "owner_role": dp.get("owner_role"), "domain": dp["domain"]} for code, dp in sorted(items.items())],
            "new_item_areas": await asyncio.to_thread(uploads.new_item_areas, node_id)}


@router.post("/uploads", status_code=status.HTTP_201_CREATED)
async def add_upload(
    file: UploadFile = File(...),
    node_id: str = Form(...),
    datapoint: str = Form(...),
    kind: str = Form("auto"),
    title: str = Form(""),
    tags: str = Form(""),
    version: str = Form(""),
    graph_id: str = Form(""),
    graph_name: str = Form(""),
    kind_label: str = Form(""),
    new_item_title: str = Form(""),
    new_item_area: str = Form(""),
    output_template: str = Form(""),
    synthetic: bool = Form(False),
    user: dict = Depends(require_role("mesh_admin")),
) -> dict:
    """Keep one uploaded file as a document of the company's catalogue item in a context graph (``graph_id`` of an
    existing one, or ``graph_name`` of a new one), rebuild the pack of its domain, and refresh the central graph from
    the node export. ``output_template`` (JSON text) is kept with the context graph as its output template, and is
    checked before anything is kept. ``synthetic=true`` marks the file as invented data. Without it the record says
    the file is real. The reason is returned when nothing was kept."""
    from services import json_templates, uploads
    rt = await asyncio.to_thread(runtime)
    template = None
    if output_template.strip():
        if not json_templates.per_graph():
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, json_templates.STANDARD_ONLY + " Nothing was kept.")
        try:
            template = json.loads(output_template)
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The output template is not valid JSON. Nothing was kept.") from None
        problems = json_templates.check(template)
        if problems:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "The output template was refused, and nothing was kept. " + "; ".join(problems))
    data = await file.read()
    try:
        record = await asyncio.to_thread(uploads.add_upload, rt, user, node_id, datapoint, kind, title, file.filename or "upload.txt", data, tags,
                                         version or None, True, graph_id or None, graph_name or None, kind_label or None,
                                         new_item_title or None, new_item_area or None, synthetic=synthetic)
    except uploads.UploadRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if template is not None:
        await asyncio.to_thread(json_templates.set_for_graph, record["context_graph"]["id"], template, str(user.get("email") or user.get("sub") or ""))
    refreshed = await rt.refresh_from_nodes()
    await _describe_again(rt, [record["context_graph"]["id"]])
    company, roles = _person(user)
    graph = None
    try:
        graph = await asyncio.to_thread(uploads.graph_of, rt, record["document"]["id"], company, roles)
    except KeyError:
        pass
    return {**record, "refresh": refreshed.get(node_id, ""), "graph": graph}


@router.post("/uploads/batch")
async def add_uploads(
    files: list[UploadFile] = File(...),
    paths: list[str] = Form([]),
    node_id: str = Form(...),
    datapoint: str = Form(...),
    check: bool = Form(False),
    new_item_title: str = Form(""),
    new_item_area: str = Form(""),
    graph_name: str = Form(""),
    user: dict = Depends(require_role("mesh_admin")),
) -> dict:
    """Many inputs at once: several files, the files of a folder with their paths in ``paths``, or one .zip of a folder
    (services.upload_batch). Each subfolder becomes one context graph. ``check=true`` reads every file and keeps
    nothing: the answer says for each file its graph, title and kind, or why it is refused. Without it the files that
    can be kept are kept one after the other, and the central graph is refreshed once at the end. ``new_item_title`` and
    ``new_item_area`` put the files under a new catalogue item, and ``graph_name`` names the graph of the files that are
    in no subfolder."""
    from services import upload_batch, uploads
    rt = await asyncio.to_thread(runtime)
    if node_id not in NODE_IDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown subsidiary node")
    if len(files) > upload_batch.MAX_FILES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"At most {upload_batch.MAX_FILES} files are taken at once.")
    given, total = [], 0
    for i, file in enumerate(files):
        data = await file.read(upload_batch.MAX_TOTAL_BYTES + 1 - total)
        total += len(data)
        if total > upload_batch.MAX_TOTAL_BYTES:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"The files have more than {upload_batch.MAX_TOTAL_BYTES // 1_000_000} MB together.")
        given.append((paths[i] if i < len(paths) and paths[i] else file.filename or f"file_{i + 1}", data))
    try:
        planned = await asyncio.to_thread(upload_batch.plan, rt, given, node_id, datapoint, new_item_title=new_item_title,
                                          new_item_area=new_item_area, graph_name=graph_name)
    except upload_batch.BatchRefused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    if check:
        return {**planned, "entries": [upload_batch.public(x) for x in planned["entries"]], "checked_only": True}
    result = await asyncio.to_thread(upload_batch.save, rt, user, planned)
    refreshed = await rt.refresh_from_nodes() if result["saved"] else {}
    await _describe_again(rt, [g["id"] for g in result["graphs"]])
    return {**result, "refresh": {node: refreshed.get(node, "") for node in sorted({r["node_id"] for r in result["saved"]})}}


@router.get("/uploads/graphs/{graph_id}")
async def context_graph(graph_id: str, format: str | None = None, user: dict = Depends(require_user)):
    """One context graph: every input in it the person may see, with the items, the companies and the entities one link
    away, and the links among them. With ``format`` (json, graphml, csv or pack) the same as a file to download."""
    from services import uploads
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    try:
        view = await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No input of this context graph is in the graph, or none is shown to you") from None
    if not format:
        return view
    if format not in export_formats.ids():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"format is one of {', '.join(export_formats.ids())}")
    documents = None
    if format == "pack":
        records = [uploads.record_of(doc_id.split(":", 1)[0], doc_id) for doc_id in view["documents"]]
        documents = uploads.pack_documents([r for r in records if r], company, roles)
    content, media, ext = uploads.export(view, format, documents)
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="context_graph_{uploads.file_name(view["name"])}.{ext}"'})


@router.delete("/uploads/graphs/{graph_id}")
async def drop_context_graph(graph_id: str, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Take every input of a context graph out of the packs, the indexes and the graph. The records stay, marked removed.
    ``failed`` names a pack whose rebuild failed, and a second call rebuilds it again. A correction loaded from the
    graph's JSON is dropped with it and named in ``corrections_dropped``."""
    from services import context_graph_ingest as ingested, uploads
    rt = await asyncio.to_thread(runtime)
    try:
        result = await asyncio.to_thread(uploads.drop_graph, graph_id, user)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No context graph with this id") from None
    corrections = [r["id"] for r in ingested.records() if r.get("corrects") == graph_id]
    for correction in corrections:
        await asyncio.to_thread(ingested.drop, correction, user)
    refreshed = await rt.refresh_from_nodes()
    return {**result, "corrections_dropped": corrections, "refresh": {node: refreshed.get(node, "") for node in sorted({r["node_id"] for r in result["removed"]})}}


@router.post("/uploads/graphs/{graph_id}/clear")
async def clear_context_graph(graph_id: str, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Take a context graph whose inputs were all removed off the list. The removed records stay on disk, marked
    cleared, and are no longer listed. 409 while the graph still has an input."""
    from services import uploads
    try:
        return await asyncio.to_thread(uploads.clear_graph, graph_id, user)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No context graph with this id has removed inputs") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from None


@router.get("/uploads/{doc_id}/graph")
async def upload_graph(doc_id: str, format: str | None = None, user: dict = Depends(require_user)):
    """The part of the graph around one uploaded document. With ``format`` (json, graphml, csv or pack) the same part as
    a file to download."""
    from services import uploads
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    try:
        view = await asyncio.to_thread(uploads.graph_of, rt, doc_id, company, roles)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This document is not in the graph, or is not shown to you") from None
    if not format:
        return view
    if format not in export_formats.ids():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"format is one of {', '.join(export_formats.ids())}")
    node = doc_id.split(":", 1)[0]
    record = uploads.record_of(node, doc_id) if format == "pack" else None
    if format == "pack" and record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload record for this document")
    content, media, ext = uploads.export(view, format, uploads.pack_documents([record], company, roles) if record else None)
    name = doc_id.replace(":", "_").replace("/", "_")
    return Response(content, media_type=media, headers={"Content-Disposition": f'attachment; filename="{name}.{ext}"'})


@router.delete("/uploads/{doc_id}")
async def remove_upload(doc_id: str, user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Take an uploaded document out of the pack, the index and the graph. The record stays, marked removed."""
    from services import uploads
    rt = await asyncio.to_thread(runtime)
    node = doc_id.split(":", 1)[0]
    if node not in NODE_IDS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown subsidiary node")
    try:
        record = await asyncio.to_thread(uploads.remove_upload, node, doc_id, user)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload record for this document") from None
    refreshed = await rt.refresh_from_nodes()
    return {**record, "refresh": refreshed.get(node, "")}


@router.post("/uploads/{doc_id}/links/{link_id}")
async def decide_link(doc_id: str, link_id: str, body: dict, user: dict = Depends(require_user)) -> dict:
    """Approve or reject a link taken from the text of an upload (services.graph_extract), with {"status": "approved"}
    or {"status": "rejected"}. A mesh admin or a person of the company that keeps the upload decides."""
    from services import graph_extract, uploads
    node = doc_id.split(":", 1)[0]
    company, roles = _person(user)
    if node not in NODE_IDS or uploads.record_of(node, doc_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload record for this document")
    if "mesh_admin" not in roles and company != node:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A mesh admin or the company that keeps the upload decides on its links")
    try:
        return await asyncio.to_thread(graph_extract.decide, doc_id, link_id, str(body.get("status", "")), user)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No link with this id was taken from the text of this document") from None
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None


async def _describe_again(rt, graph_ids: list[str]) -> int:
    """Have the model write the description of each graph again, after its inputs or their extractions changed. A graph
    the model may not read, or a reply that is not usable, keeps the description made by code. Never fails the request."""
    from services import graph_describe
    written = 0
    for graph_id in graph_ids:
        try:
            written += 1 if await asyncio.to_thread(graph_describe.refresh, rt, graph_id) else 0
        except Exception:  # noqa: BLE001 - the description is an addition to the upload, never a reason to fail it
            pass
    return written


@router.post("/uploads/graphs/{graph_id}/description/generate")
async def generate_description(graph_id: str, user: dict = Depends(require_user)) -> dict:
    """Have the model write the description of a context graph again from what its inputs name and state. It does not
    replace a description a person wrote. A mesh admin, or a person of a company that keeps an input in the graph."""
    from services import uploads
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    try:
        view = await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No input of this context graph is in the graph, or none is shown to you") from None
    if not view["description"]["can_write"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A mesh admin or a company that keeps an input in the graph writes its description")
    made = await _describe_again(rt, [graph_id])
    view = await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
    return {"id": graph_id, "written": bool(made), "description": view["description"]}


@router.put("/uploads/graphs/{graph_id}/description")
async def describe_context_graph(graph_id: str, body: dict, user: dict = Depends(require_user)) -> dict:
    """Write what a context graph is about, with {"text": "..."} of 20 to 1,000 characters. An empty text takes the
    written description away, and the one made by code from the inputs shows again. A mesh admin, or a person of a
    company that keeps an input in the graph, writes it."""
    from services import graph_describe, uploads
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    try:
        view = await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No input of this context graph is in the graph, or none is shown to you") from None
    if not view["description"]["can_write"]:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A mesh admin or a company that keeps an input in the graph writes its description")
    try:
        await asyncio.to_thread(graph_describe.write, graph_id, str(body.get("text") or ""), user)
    except graph_describe.Refused as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from None
    view = await asyncio.to_thread(uploads.context_graph_view, rt, graph_id, company, roles)
    return {"id": graph_id, "description": view["description"]}


@router.post("/uploads/{doc_id}/keep")
async def keep_input(doc_id: str, user: dict = Depends(require_user)) -> dict:
    """Say that an input listed for review belongs to its context graph, so it is no longer listed. A mesh admin or a
    person of the company that keeps the upload decides."""
    from services import uploads
    node = doc_id.split(":", 1)[0]
    company, roles = _person(user)
    if node not in NODE_IDS or uploads.record_of(node, doc_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload record for this document")
    if "mesh_admin" not in roles and company != node:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "A mesh admin or the company that keeps the upload decides on its inputs")
    try:
        return await asyncio.to_thread(uploads.keep_input, node, doc_id, user)
    except KeyError:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No upload record for this document") from None


@router.post("/uploads/extractions")
async def extract_uploads(write: bool = False, refresh: bool = False, document: str | None = None, check_only: bool = False,
                          user: dict = Depends(require_role("mesh_admin"))) -> dict:
    """Take entities and links from the text of every accepted upload that has none yet, or of every accepted upload
    with ``refresh``, which keeps each decision a person made on a link. Without ``write`` nothing is kept and the
    answer gives what the code part would find for each input (the model part runs only with ``write``). ``document``
    limits the run to the input with that id. ``check_only`` with ``write`` keeps every extraction as it is and only has
    the model check the links it has not checked yet (graph_extract.verify)."""
    from services import graph_extract, uploads
    rt = await asyncio.to_thread(runtime)
    out = []
    touched: set[str] = set()
    for node, record in uploads._all_records():
        doc = record["document"]
        if document and doc["id"] != document:
            continue
        if graph_extract.read(doc["id"]) is not None and not refresh and not check_only:
            continue
        if write and check_only:
            dp = uploads.datapoints_of(node).get(doc["datapoint"].split(":", 1)[1], {})
            call = uploads._extract_caller(rt, dp.get("sensitivity"), record.get("synthetic") is True)
            asked = await asyncio.to_thread(graph_extract.verify, rt, doc["id"], call)
            made = {**(graph_extract.summary(graph_extract.read(doc["id"])) or {}), "asked": asked}
        elif write:
            made = await asyncio.to_thread(uploads.extract_record, rt, node, record)
        else:
            links = graph_extract.code_links(rt, doc.get("body") or "", list(doc.get("concepts") or []))
            stated, stated_links = graph_extract.code_statements(rt, node, doc["id"], doc.get("body") or "", list(doc.get("concepts") or []))
            made = {"links": len(links) + len(stated_links), "entities": len(stated), "model": "not run without write"}
        out.append({"document": doc["id"], "title": doc["title"], **(made or {})})
        touched.add(uploads.graph_ref(record)["id"])
    if write and any((d.get("topics_set_aside") or 0) for d in out):
        await rt.refresh_from_nodes()  # topics taken off a document change the central graph
    described = await _describe_again(rt, sorted(touched)) if write else 0
    return {"written": write, "documents": out, "descriptions_written": described}


@router.get("/graph/search")
async def graph_search(q: str = "", user: dict = Depends(require_user)) -> dict:
    """Entities of the context graph that match a word or phrase, with the owning company, the sharing rule and the
    number of links of each. Entities of never-leave items of another company are left out."""
    from services import graph_search
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    return await asyncio.to_thread(graph_search.search, rt, q[:300], company, roles)


@router.get("/graph/entity/{entity_id:path}")
async def graph_entity(entity_id: str, user: dict = Depends(require_user)) -> dict:
    """One entity with its neighbours by link type, one hop, as the person may see them."""
    from services import graph_search
    from services.context_tools import NotFound
    rt = await asyncio.to_thread(runtime)
    company, roles = _person(user)
    try:
        return await asyncio.to_thread(graph_search.entity, rt, entity_id, company, roles)
    except NotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "This entity is not in the graph, or is not shown to you") from None
