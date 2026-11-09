"""Authenticated cross-subsidiary query endpoint."""
from __future__ import annotations

import asyncio
import json
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
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
    from services.ontology import ontology

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
                "owner": "Subsidiary operated",
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
    }