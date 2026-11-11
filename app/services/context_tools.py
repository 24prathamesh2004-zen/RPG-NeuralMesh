"""The generic context tools every application uses: entity, related, similar, live, and the inspection shapes.

A domain adds no tool, it adds types. role_context is related(role) with the talent rules, and the Snap and Score
inspection profile is related(asset) with the inspection rules. Every item returned is an evidence record or a
plain reference (id, type, label), and policy stays with the owning node: a live fact is looked up there with the
user's identity and never stored here.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Callable

Visible = Callable[[str], bool]  # whether one entity may be shown to this caller (services/context_catalogue.visibility)

from contracts.graph import GraphEdge, GraphNode, Provenance
from services.context_api import EndUser, NotFound
from services.mesh_runtime import MeshRuntime
from services.ontology import ontology


def _ref(rt: MeshRuntime, entity_id: str) -> dict[str, Any]:
    d = rt.mesh.graph.nodes.get(entity_id, {})
    return {"id": entity_id, "type": d.get("type"), "label": d.get("label") or entity_id, "status": "retired" if d.get("retired") else "live"}


def entity(rt: MeshRuntime, entity_id: str, visible: Visible | None = None) -> dict[str, Any]:
    g = rt.mesh.graph
    if entity_id not in g or g.nodes[entity_id].get("type") == "Unknown" or (visible and not visible(entity_id)):
        raise NotFound(entity_id)
    d = dict(g.nodes[entity_id])
    kind = d.pop("type", None)
    layer = ontology().node_types.get(kind, {}).get("domain", "core")
    return {"schema_version": "1.0", "id": entity_id, "type": kind, "label": d.pop("label", entity_id), "layer": layer,
            "owner": d.pop("owner", None) or d.get("subsidiary"), "retired": bool(d.pop("retired", False)),
            "aliases": d.pop("aliases", []) or [], "properties": {k: v for k, v in d.items() if k not in ("sensitivity",)},
            "connections": _degree(rt, entity_id, visible)}


def _degree(rt: MeshRuntime, entity_id: str, visible: Visible | None = None) -> dict[str, int]:
    """How many live links of each type the entity has, counting only links to entities this caller may see."""
    g = rt.mesh.graph
    out: dict[str, int] = {}
    for a, b, d in list(g.out_edges(entity_id, data=True)) + list(g.in_edges(entity_id, data=True)):
        other = b if a == entity_id else a
        if d["status"] in ("approved", "proposed", "computed") and not (visible and not visible(other)):
            out[d["type"]] = out.get(d["type"], 0) + 1
    return dict(sorted(out.items()))


def related(rt: MeshRuntime, entity_id: str, edge_types: list[str] | None = None, group: str | None = None, depth: int = 1,
            statuses: tuple[str, ...] = ("approved", "proposed"), visible: Visible | None = None) -> dict[str, Any]:
    """Neighbours grouped by edge type and direction. depth 2 adds the neighbours of the neighbours. With a visibility
    rule, an entity the caller may not see is neither shown nor walked through."""
    g = rt.mesh.graph
    if entity_id not in g or (visible and not visible(entity_id)):
        raise NotFound(entity_id)
    wanted = set(edge_types or [])
    if group:
        wanted |= set(ontology().group(group))
    groups: dict[str, list[dict[str, Any]]] = {}
    seen: set[str] = {entity_id}
    frontier = [entity_id]
    for _ in range(max(1, min(depth, 2))):
        next_frontier = []
        for node in frontier:
            for a, b, d in list(g.out_edges(node, data=True)) + list(g.in_edges(node, data=True)):
                if d["status"] not in statuses or (wanted and d["type"] not in wanted):
                    continue
                other = b if a == node else a
                if g.nodes[other].get("retired") or (visible and not visible(other)):
                    continue
                key = d["type"] if a == node else f"{d['type']} (incoming)"
                item = {**_ref(rt, other), "edge_status": d["status"], "via": node if node != entity_id else None,
                        **({"properties": d["properties"]} if d.get("properties") else {})}
                if other not in seen:
                    next_frontier.append(other)
                seen.add(other)
                groups.setdefault(key, []).append(item)
        frontier = next_frontier
    return {"schema_version": "1.0", "entity": _ref(rt, entity_id), "depth": depth, "related": {k: sorted(v, key=lambda x: x["id"]) for k, v in sorted(groups.items())}}


def similar(rt: MeshRuntime, entity_id: str, k: int = 5, visible: Visible | None = None) -> dict[str, Any]:
    """SIMILAR_TO neighbours from the similarity layer, each with its reason and score, marked computed."""
    g = rt.mesh.graph
    if entity_id not in g or (visible and not visible(entity_id)):
        raise NotFound(entity_id)
    out = []
    for a, b, d in list(g.out_edges(entity_id, data=True)) + list(g.in_edges(entity_id, data=True)):
        if d["type"] != "SIMILAR_TO" or d["status"] in ("retired", "rejected"):
            continue
        other = b if a == entity_id else a
        if g.nodes[other].get("retired") or (visible and not visible(other)):
            continue
        props = d.get("properties", {})
        out.append({**_ref(rt, other), "score": props.get("confidence"), "reason": props.get("reason"), "method": d.get("provenance", {}).get("method"),
                    "status": d["status"]})
    out.sort(key=lambda x: -(x["score"] or 0))
    return {"schema_version": "1.0", "entity": _ref(rt, entity_id), "similar": out[:k],
            "note": "Computed links carry their reason and are never shown as approved facts."}


# ── inspection (Snap and Score) ─────────────────────────────────────────────
def _asset_id(rt: MeshRuntime, asset: str) -> str:
    g = rt.mesh.graph
    if asset in g:
        return asset
    for n, d in g.nodes(data=True):
        if d.get("type") == "Asset" and any(r.get("uri") == asset for r in d.get("external_refs") or []):
            return n
    raise NotFound(asset)


def inspection_profile(rt: MeshRuntime, asset: str, visible: Visible | None = None) -> dict[str, Any]:
    """What Snap and Score calls get_inspection_profile: the conditions to look for, the grade scale, the views,
    the expected cover and the standards that govern the asset. The actual cover status is a live lookup."""
    aid = _asset_id(rt, asset)
    rel = related(rt, aid, group=None, depth=1, visible=visible)["related"]
    g = rt.mesh.graph

    def ids(key: str) -> list[dict[str, Any]]:
        return [{"id": x["id"], "label": x["label"], "status": x["edge_status"]} for x in rel.get(key, [])]

    scale = rel.get("GRADED_ON", [])
    grades = g.nodes[scale[0]["id"]].get("grades", []) if scale else []
    return {"schema_version": "1.0", "asset": _ref(rt, aid), "owner": g.nodes[aid].get("subsidiary"),
            "external_refs": g.nodes[aid].get("external_refs") or [], "views": ids("HAS_VIEW"), "conditions": ids("CHECKED_FOR"),
            "grade_scale": {**scale[0], "grades": grades} if scale else None, "expected_cover": ids("HAS_EXPECTED_COVER"),
            "standards": ids("GOVERNED_BY"), "family": ids("HAS_ASSET (incoming)"),
            "status": "proposed" if any(x["edge_status"] == "proposed" for v in rel.values() for x in v) else "approved",
            "live_facts": ["cover_status", "history"]}


async def live(rt: MeshRuntime, user: EndUser, entity_id: str, fact: str) -> dict[str, Any]:
    """A fact that is never stored: asked of the owning node now, with the user's identity, and returned with its time."""
    eid = _asset_id(rt, entity_id) if ":" not in entity_id or entity_id.count(".") else entity_id
    g = rt.mesh.graph
    if eid not in g:
        raise NotFound(entity_id)
    node_id = g.nodes[eid].get("subsidiary") or eid.split(":", 1)[0]
    if node_id not in rt.orchestrator.node_urls:
        return {"schema_version": "1.0", "entity": _ref(rt, eid), "fact": fact, "decision": "NODE_UNKNOWN", "value": None}
    try:
        response = await rt.orchestrator.call_node_tool(user.assertion(), node_id, "lookup", {"fact": fact, "key": eid.split(":", 1)[1], "purpose": "inspection"})
    except Exception as exc:  # noqa: BLE001
        return {"schema_version": "1.0", "entity": _ref(rt, eid), "fact": fact, "decision": "NODE_UNAVAILABLE", "reason": type(exc).__name__, "value": None}
    return {"schema_version": "1.0", "entity": _ref(rt, eid), "fact": fact, "node": node_id, **response}


def record_inspection(rt: MeshRuntime, user: EndUser, inspection: dict[str, Any]) -> dict[str, Any]:
    """An inspection becomes an Inspection event node with INSPECTION_OF, FOUND and GRADED edges, through the intake.
    Images stay with the application. The mesh keeps the event, the grade and the condition names."""
    aid = _asset_id(rt, inspection["asset"])
    g = rt.mesh.graph
    org = g.nodes[aid].get("subsidiary")
    if not org:
        return {"accepted": False, "errors": [f"{aid} has no owning company"]}
    if user.company != org:
        return {"accepted": False, "errors": [f"an inspection of a {org} asset is recorded by a {org} user, not by {user.company}"]}
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,118}", inspection["inspection_id"]):
        return {"accepted": False, "errors": ["inspection_id may hold letters, digits, dots, underscores and dashes only"]}
    iid = f"{org}:inspection/{inspection['inspection_id']}"
    when = inspection.get("inspected_at") or datetime.now(timezone.utc).isoformat()
    prov = Provenance(method="imported", by_role="Snap and Score", created_at=when[:10])
    node = GraphNode(id=iid, type="Inspection", label=f"Inspection {inspection['inspection_id']} of {g.nodes[aid].get('label')}",
                     owner=org, properties={"subsidiary": org, "asset": aid, "inspected_at": when, "inspector_company": user.company,
                                            "grade": inspection.get("grade"), "review_status": inspection.get("review_status"),
                                            "defect_area_pct": inspection.get("defect_area_pct"), "image_ref": inspection.get("image_ref")})
    edges = [GraphEdge(id=f"rel:snapscore/INSPECTION_OF/{iid}", type="INSPECTION_OF", **{"from": iid, "to": aid}, status="approved", provenance=prov)]
    for cond in inspection.get("conditions", []):
        cid = cond if ":" in cond else f"inspection:condition/{cond}"
        if cid in g:
            edges.append(GraphEdge(id=f"rel:snapscore/FOUND/{iid}/{cid.rsplit('/', 1)[-1]}", type="FOUND", **{"from": iid, "to": cid}, status="approved", provenance=prov))
    scale = [b for _, b, d in g.out_edges(aid, data=True) if d["type"] == "GRADED_ON" and d["status"] != "retired"]
    if scale:
        edges.append(GraphEdge(id=f"rel:snapscore/GRADED/{iid}", type="GRADED", **{"from": iid, "to": scale[0]}, status="approved",
                               provenance=prov, properties={"grade": inspection.get("grade")}))
    report = rt.mesh.load_records(f"app:snapscore/{org}", [node], edges, retire=False)
    if not report.ok:
        return {"accepted": False, "errors": report.errors}
    rt.mesh.rebuild()
    return {"accepted": True, "inspection": iid, "asset": aid, "edges": len(edges), "revision": rt.store.revision()}


def history(rt: MeshRuntime, asset: str, limit: int = 20) -> dict[str, Any]:
    """Past inspections of an asset held in the graph (the events Snap and Score recorded), newest first."""
    aid = _asset_id(rt, asset)
    g = rt.mesh.graph
    items = []
    for a, _, d in g.in_edges(aid, data=True):
        if d["type"] != "INSPECTION_OF" or d["status"] == "retired":
            continue
        n = g.nodes[a]
        found = [b.rsplit("/", 1)[-1] for _, b, e in g.out_edges(a, data=True) if e["type"] == "FOUND"]
        items.append({"inspection": a, "inspected_at": n.get("inspected_at"), "grade": n.get("grade"), "conditions": sorted(found),
                      "review_status": n.get("review_status"), "defect_area_pct": n.get("defect_area_pct")})
    items.sort(key=lambda x: x["inspected_at"] or "", reverse=True)
    return {"schema_version": "1.0", "asset": _ref(rt, aid), "inspections": items[:limit]}


def context_documents(rt: MeshRuntime, context: dict[str, Any]) -> tuple[set[str], set[str]]:
    """For ask with an inspection context: the governing documents of the asset and the companies that own them."""
    g = rt.mesh.graph
    docs: set[str] = set()
    try:
        aid = _asset_id(rt, context.get("asset", ""))
    except NotFound:
        return set(), set()
    for _, b, d in g.out_edges(aid, data=True):
        if d["type"] == "GOVERNED_BY" and d["status"] != "retired":
            docs.add(b)
    for cond in context.get("conditions", []):
        cid = cond if ":" in cond else f"inspection:condition/{cond}"
        for _, b, d in g.out_edges(cid, data=True):
            if d["type"] == "GOVERNED_BY" and d["status"] != "retired":
                docs.add(b)
    owners = {g.nodes[x].get("subsidiary") for x in docs if x in g and g.nodes[x].get("subsidiary")}
    return docs, owners
