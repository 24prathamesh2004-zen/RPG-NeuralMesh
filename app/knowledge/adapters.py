"""Adapters: from an input format to graph records. An adapter changes shape only, it never validates or loads.

Formats: a knowledge pack (group or subsidiary), a node export (the export_graph tool), a CSV pair (nodes.csv and
edges.csv), JSON Lines (one node or edge per line), and an application ontology such as the Snap and Score draft.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from contracts.graph import GraphEdge, GraphNode, Provenance
from services.ontology import ontology

_NODE_KEYS = {"id", "type", "label", "aliases", "description", "external_refs"}


def _node(e: dict[str, Any], owner: str | None = None) -> GraphNode:
    props = {k: v for k, v in e.items() if k not in _NODE_KEYS and k != "owner" and k != "sensitivity"}
    return GraphNode(id=e["id"], type=e["type"], label=e["label"], aliases=list(e.get("aliases") or []), description=e.get("description"),
                     owner=e.get("owner", owner), sensitivity=e.get("sensitivity"), properties=props, external_refs=list(e.get("external_refs") or []))


def _edge(r: dict[str, Any], default_role: str) -> GraphEdge:
    prov = dict(r.get("provenance") or {})
    prov.setdefault("method", "imported")
    prov.setdefault("by_role", default_role)
    return GraphEdge(id=r["id"], type=r["type"], **{"from": r["from"], "to": r["to"]}, status=r.get("status", "approved"),
                     provenance=Provenance(**prov), properties=dict(r.get("properties") or {}), confidence=r.get("confidence"),
                     approvals=list(r.get("approvals") or []))


def derived_edges(nodes: list[GraphNode], source_tag: str) -> list[GraphEdge]:
    """The structural edges the rules derive from node fields (OWNED_BY, ROLE_AT, IN_DOMAIN)."""
    out: list[GraphEdge] = []
    for rule in ontology().derived_edges:
        for n in nodes:
            if n.type != rule["from_type"]:
                continue
            try:
                target = rule["to"].format(**n.properties)
            except KeyError:
                continue
            if "{" in target or target.endswith(":None") or target.endswith(":"):
                continue
            edge_id = f"rel:{rule['type'].lower().replace('_', '-')}/{n.id}" if rule["type"] == "ROLE_AT" else f"rel:{source_tag}/{rule['type']}/{n.id}->{target}"
            out.append(GraphEdge(id=edge_id, type=rule["type"], **{"from": n.id, "to": target}, status="approved",
                                 provenance=Provenance(method="imported", by_role="Mesh knowledge curator")))
    return out


# ── knowledge pack (group or subsidiary) ────────────────────────────────────
def from_pack(pack: dict[str, Any]) -> tuple[list[GraphNode], list[GraphEdge]]:
    owner = pack["pack"]["owner_role"]
    nodes = []
    for e in pack.get("entities", []):
        n = _node(e, owner)
        if n.type == "Subsidiary":
            n.aliases = n.aliases or [n.id.split(":", 1)[1]]
        nodes.append(n)
    edges = [_edge(r, owner) for r in pack.get("relationships", [])]
    if pack["pack"].get("scope") == "subsidiary":
        edges += [d for d in derived_edges(nodes, pack["pack"]["pack_id"]) if d.type == "ROLE_AT"]
    return nodes, edges


# ── node export (the export_graph tool) ─────────────────────────────────────
def from_node_export(export: dict[str, Any]) -> tuple[list[GraphNode], list[GraphEdge]]:
    node = export["node_id"]
    tag = f"{node}.export"
    by_role = "Node export"
    nodes: list[GraphNode] = [GraphNode(id=f"org:{node}", type="Subsidiary", label=export.get("display", node), owner="Mesh team",
                                        aliases=[node, export.get("display", node)],
                                        properties={"level": export.get("level"), "profile": export.get("profile", "")})]
    edges: list[GraphEdge] = []

    def rel(rtype: str, a: str, b: str, props: dict | None = None) -> None:
        edges.append(GraphEdge(id=f"rel:{tag}/{rtype}/{a}->{b}", type=rtype, **{"from": a, "to": b}, status="approved",
                               properties=props or {}, provenance=Provenance(method="imported", by_role=by_role)))

    for dp in export.get("datapoints", []):
        nodes.append(GraphNode(id=dp["id"], type="Datapoint", label=dp["title"], owner=dp.get("owner_role"), sensitivity=dp.get("sensitivity"),
                               properties={"subsidiary": node, "code": dp["catalogue_id"], "ceiling": dp.get("ceiling"), "domain": dp.get("domain"),
                                           "purposes_allowed": dp.get("purposes_allowed", []), "never_leave": dp.get("never_leave", False)}))
        if dp.get("domain"):
            rel("IN_DOMAIN", dp["id"], f"domain:{dp['domain']}")
        rel("OWNED_BY", dp["id"], f"org:{node}")
    for doc in export.get("documents", []):
        nodes.append(GraphNode(id=doc["id"], type="Document", label=doc["title"],
                               properties={"subsidiary": node, "datapoint": doc["datapoint"], "version": doc.get("version"),
                                           "kind": doc.get("kind"), "tags": doc.get("tags", [])}))
        rel("IN_DATAPOINT", doc["id"], doc["datapoint"])
        for c in doc.get("concepts", []):
            rel("MENTIONS", doc["id"], c)
        for s in doc.get("skills", []):
            rel("EXPLAINS_SKILL", doc["id"], s["skill"], {"level": s["level"]})
        if doc.get("supersedes"):
            rel("SUPERSEDES", doc["id"], doc["supersedes"])
    for ex in export.get("experts", []):
        nodes.append(GraphNode(id=ex["id"], type="Expert", label=ex["role"],
                               properties={"subsidiary": node, "consent": True, "keywords": ex.get("keywords", [])}))
        for s in ex.get("skills", []):
            rel("HAS_SKILL", ex["id"], s["skill"], {"level": s.get("level")})
        for ev in ex.get("evidence", []):
            rel("EVIDENCED_BY", ex["id"], ev)
    for e in export.get("entities", []):
        nodes.append(_node(e))
    edges += [d for d in derived_edges([n for n in nodes if n.type == "Role"], tag)]
    edges += [_edge(r, by_role) for r in export.get("relationships", [])]
    return nodes, edges


# ── CSV pair ────────────────────────────────────────────────────────────────
def from_csv(nodes_path: Path, edges_path: Path, by_role: str = "CSV sender") -> tuple[list[GraphNode], list[GraphEdge]]:
    """nodes.csv: id,type,label,aliases (separated by |),properties (JSON). edges.csv: id,type,from,to,status,confidence,note."""
    nodes, edges = [], []
    with nodes_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            props = json.loads(row.get("properties") or "{}")
            nodes.append(GraphNode(id=row["id"], type=row["type"], label=row["label"],
                                   aliases=[a for a in (row.get("aliases") or "").split("|") if a], properties=props))
    with edges_path.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            props = {"note": row["note"]} if row.get("note") else {}
            edges.append(GraphEdge(id=row["id"], type=row["type"], **{"from": row["from"], "to": row["to"]}, status=row.get("status") or "approved",
                                   confidence=float(row["confidence"]) if row.get("confidence") else None, properties=props,
                                   provenance=Provenance(method="authored", by_role=by_role)))
    return nodes, edges


# ── JSON Lines ──────────────────────────────────────────────────────────────
def from_jsonl(path: Path, by_role: str = "JSON Lines sender") -> tuple[list[GraphNode], list[GraphEdge]]:
    nodes, edges = [], []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        kind = rec.pop("kind", None)
        rec.pop("source", None)
        if kind == "node":
            nodes.append(GraphNode(**rec))
        elif kind == "edge":
            rec.setdefault("provenance", {"method": "imported", "by_role": by_role})
            edges.append(GraphEdge(**rec))
    return nodes, edges


# ── application ontology (the Snap and Score draft) ─────────────────────────
def from_inspection_ontology(onto: dict[str, Any], app: str = "snapscore") -> tuple[list[GraphNode], list[GraphEdge]]:
    """Condition families and conditions become concepts of the inspection domain, grade scales, cover types and
    review statuses become standards, and each asset gets its views, conditions, scale and cover as edges.
    Everything enters as proposed until each subsidiary approves its own entries."""
    role = f"{app} ontology"
    prov = Provenance(method="imported", by_role=role)
    nodes: list[GraphNode] = []
    edges: list[GraphEdge] = []
    ns = "inspection"
    for fam in onto.get("condition_families", []):
        nodes.append(GraphNode(id=f"{ns}:condition-family/{fam['id']}", type="ConditionFamily", label=fam["name"]))
    for c in onto.get("conditions", []):
        cid = f"{ns}:condition/{c['id']}"
        nodes.append(GraphNode(id=cid, type="Condition", label=c["id"].replace("_", " "), aliases=[c["id"]]))
        edges.append(GraphEdge(id=f"rel:{app}/BELONGS_TO/{c['id']}", type="BELONGS_TO", **{"from": cid, "to": f"{ns}:condition-family/{c['family']}"},
                               status="proposed", provenance=prov))
    for scale in onto.get("grade_scales", []):
        nodes.append(GraphNode(id=f"{ns}:grade-scale/{scale['id']}", type="GradeScale", label=scale["id"].replace("_", " "), properties={"grades": scale["grades"]}))
    for cover in onto.get("cover_types", []):
        nodes.append(GraphNode(id=f"{ns}:cover-type/{cover}", type="CoverType", label=cover.replace("_", " ")))
    for status in onto.get("review_status", []):
        nodes.append(GraphNode(id=f"{ns}:review-status/{status}", type="ReviewStatus", label=status.replace("_", " ")))
    views: set[str] = set()
    for sub in onto.get("subsidiaries", []):
        org = sub["id"]
        nodes.append(GraphNode(id=f"org:{org}", type="Subsidiary", label=sub.get("name", org), owner="Mesh team", aliases=[org, sub.get("name", org)],
                               properties={"level": None, "profile": f"Named by {app}. No node yet." , "sector": sub.get("sector")}))
        for fam in sub.get("families", []):
            fid = f"{org}:asset-family/{fam['id'].split('.', 1)[-1]}"
            nodes.append(GraphNode(id=fid, type="AssetFamily", label=fam["name"], properties={"subsidiary": org}))
            edges.append(GraphEdge(id=f"rel:{app}/OWNED_BY/{fid}", type="OWNED_BY", **{"from": fid, "to": f"org:{org}"}, status="proposed", provenance=prov))
            for asset in fam.get("assets", []):
                aid = f"{org}:asset/{asset['id'].split('.', 1)[-1]}"
                nodes.append(GraphNode(id=aid, type="Asset", label=asset["name"], properties={"subsidiary": org, "scan": asset.get("scan")},
                                       external_refs=[{"scheme": "SnapScore", "uri": asset["id"]}]))
                edges.append(GraphEdge(id=f"rel:{app}/HAS_ASSET/{aid}", type="HAS_ASSET", **{"from": fid, "to": aid}, status="proposed", provenance=prov))
                edges.append(GraphEdge(id=f"rel:{app}/OWNED_BY/{aid}", type="OWNED_BY", **{"from": aid, "to": f"org:{org}"}, status="proposed", provenance=prov))
                for view in asset.get("views", []):
                    vid = f"{ns}:view/{view}"
                    if vid not in views:
                        views.add(vid)
                        nodes.append(GraphNode(id=vid, type="View", label=view.replace("_", " ")))
                    edges.append(GraphEdge(id=f"rel:{app}/HAS_VIEW/{aid}/{view}", type="HAS_VIEW", **{"from": aid, "to": vid}, status="proposed", provenance=prov))
                for cond in asset.get("conditions", []):
                    edges.append(GraphEdge(id=f"rel:{app}/CHECKED_FOR/{aid}/{cond}", type="CHECKED_FOR", **{"from": aid, "to": f"{ns}:condition/{cond}"},
                                           status="proposed", provenance=prov))
                if asset.get("scale"):
                    edges.append(GraphEdge(id=f"rel:{app}/GRADED_ON/{aid}", type="GRADED_ON", **{"from": aid, "to": f"{ns}:grade-scale/{asset['scale']}"},
                                           status="proposed", provenance=prov))
                if asset.get("cover"):
                    edges.append(GraphEdge(id=f"rel:{app}/HAS_EXPECTED_COVER/{aid}", type="HAS_EXPECTED_COVER",
                                           **{"from": aid, "to": f"{ns}:cover-type/{asset['cover']}"}, status="proposed", provenance=prov))
    return nodes, edges
