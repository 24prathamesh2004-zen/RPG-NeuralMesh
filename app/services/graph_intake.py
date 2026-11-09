"""Intake of graph records: validate against the graph rules, sort, write the normalised file, load, check.

Every input, whatever its format, becomes GraphNode and GraphEdge records through an adapter (knowledge/adapters.py),
then passes here. The six checks: shape, type, signature, reference, duplicate, ownership. Any failure stops the
load and names the record. The sorted records are written to one normalised file, so two runs on the same input
give the same file and a diff of two files is the change report. After every refresh the graph checks run on the
whole graph and their results are shown on the Mesh Nodes page.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import networkx as nx

from contracts.graph import GraphEdge, GraphNode
from services.graph_store import GraphStore
from services.ontology import Ontology, ontology


@dataclass
class IntakeReport:
    source: str
    nodes: int = 0
    edges: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retired_edges: int = 0
    retired_nodes: int = 0

    @property
    def ok(self) -> bool:
        return not self.errors


def validate(nodes: list[GraphNode], edges: list[GraphEdge], source: str, known_ids: set[str] | None = None,
             known_types: dict[str, str] | None = None, rules: Ontology | None = None, warnings: list[str] | None = None) -> list[str]:
    """The six checks. known_ids and known_types describe entities already in the store, for edges that point there.
    An end that is in neither is a warning, not an error: a group pack may link documents a node exports later, and
    the dangling-link check after every refresh reports one that never arrives."""
    rules = rules or ontology()
    known_ids = known_ids or set()
    known_types = known_types or {}
    errors: list[str] = []
    warnings = warnings if warnings is not None else []
    types = {n.id: n.type for n in nodes}
    seen: set[str] = set()
    owned = rules.owned_namespaces(source)
    node_company = source.split(":", 1)[1] if source.startswith("node:") else None
    for n in nodes:
        reserved = {"type", "label", "owner", "sensitivity", "id"} & set(n.properties)
        if reserved:
            errors.append(f"node {n.id}: properties may not use the reserved keys {sorted(reserved)}")
        if node_company and n.type == "Subsidiary" and n.id != f"org:{node_company}":
            errors.append(f"node {n.id}: {source} may only write its own company entry org:{node_company}")
        if node_company and n.properties.get("subsidiary") not in (None, node_company):
            errors.append(f"node {n.id}: {source} may not mark an entity as belonging to {n.properties.get('subsidiary')}")
        if n.type not in rules.node_types:
            errors.append(f"node {n.id}: type {n.type} is not in the graph rules")
        for prop in rules.required_properties(n.type):
            if prop not in n.properties:
                errors.append(f"node {n.id}: {n.type} needs property {prop}")
        if n.id in seen:
            errors.append(f"node {n.id} is given twice")
        seen.add(n.id)
        if not rules.may_write(source, n.namespace):
            errors.append(f"node {n.id}: {source} may not write namespace {n.namespace}")
    pairs: set[tuple[str, str, str]] = set()
    seen_edges: set[str] = set()
    for e in edges:
        if e.id in seen_edges:
            errors.append(f"edge {e.id} is given twice")
        seen_edges.add(e.id)
        for end in (e.from_id, e.to_id):
            if end not in types and end not in known_ids:
                warnings.append(f"edge {e.id} points to {end}, which is not in this load or in the store yet")
        ok, why = rules.allows(e.type, types.get(e.from_id) or known_types.get(e.from_id), types.get(e.to_id) or known_types.get(e.to_id))
        if not ok:
            errors.append(f"edge {e.id}: {why}")
        et = rules.edge_types.get(e.type)
        if et is not None and et.group in ("judgement", "similarity"):
            ends = {e.from_id.split(":", 1)[0], e.to_id.split(":", 1)[0]}
            approved_by = {a.get("subsidiary") for a in e.approvals}
            if e.status == "approved" and not (owned is not None and ends <= owned) and not ends <= approved_by:
                errors.append(f"edge {e.id}: a {e.type} link between companies is proposed until both owners approve it")
        elif owned is not None and e.from_id.split(":", 1)[0] not in owned:
            # a pure link pack (ownership []) may propose links between other owners' entities, never approve them
            if not (owned == set() and e.status == "proposed"):
                errors.append(f"edge {e.id}: {source} may not write a {e.type} link from {e.from_id.split(':', 1)[0]}")
        key = (e.type, *sorted((e.from_id, e.to_id))) if et and et.symmetric else (e.type, e.from_id, e.to_id)
        if key in pairs:
            errors.append(f"edge {e.id}: {e.type} between {e.from_id} and {e.to_id} is given twice")
        pairs.add(key)
    return errors


def normalise(nodes: list[GraphNode], edges: list[GraphEdge]) -> tuple[list[GraphNode], list[GraphEdge]]:
    return (sorted(nodes, key=lambda n: (n.type, n.id)), sorted(edges, key=lambda e: (e.type, e.from_id, e.to_id, e.id)))


def write_normalised(path: Path, source: str, nodes: list[GraphNode], edges: list[GraphEdge]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for n in nodes:
            fh.write(json.dumps({"kind": "node", "source": source, **n.model_dump(exclude_defaults=True)}, sort_keys=True) + "\n")
        for e in edges:
            fh.write(json.dumps({"kind": "edge", "source": source, **e.model_dump(by_alias=True, exclude_none=True)}, sort_keys=True) + "\n")


NODE_EXPORT_TYPES = frozenset({"Subsidiary", "Datapoint", "Document", "Expert", "Role"})


def load(store: GraphStore, source: str, nodes: list[GraphNode], edges: list[GraphEdge], *, retire_nodes_of: str | None = None,
         keep_existing_nodes: set[str] | None = None, normalised_dir: Path | None = None, retire: bool = True) -> IntakeReport:
    """Validate, sort, write the normalised file, upsert, retire what the source stopped sending.

    retire=False is for incremental sources (one inspection at a time): nothing of the source is retired and no
    normalised file is written, because the load is not a snapshot of the source.
    keep_existing_nodes: IDs that this source may add but never overwrite (a company entry owned by its own node).
    retire_nodes_of: a subsidiary whose entities not in this load are retired (node exports only)."""
    report = IntakeReport(source)
    known_ids, known_types = store.entity_types()
    report.errors = validate(nodes, edges, source, set(known_ids), known_types, warnings=report.warnings)
    foreign = store.edge_sources({e.id for e in edges})
    rules = ontology()
    mine = rules.owned_namespaces(source) or set()
    by_id = {e.id: e for e in edges}
    for eid, src in sorted(foreign.items()):
        if src == source:
            continue
        # two sources that both own the from-end (a node export and that company's talent pack) may write the same link
        theirs = rules.owned_namespaces(src) or set()
        ns = by_id[eid].from_id.split(":", 1)[0]
        if ns in mine and ns in theirs:
            continue
        report.errors.append(f"edge {eid} belongs to {src}, not to {source}")
    if report.errors:
        return report
    nodes, edges = normalise(nodes, edges)
    if normalised_dir is not None and retire:
        write_normalised(normalised_dir / f"{source.replace(':', '_').replace('/', '_')}.jsonl", source, nodes, edges)
    rows = [{"id": n.id, "type": n.type, "label": n.label, "owner": n.owner, "sensitivity": n.sensitivity,
             "properties": {**n.properties, **({"aliases": n.aliases} if n.aliases else {}),
                            **({"description": n.description} if n.description else {}),
                            **({"external_refs": n.external_refs} if n.external_refs else {})}} for n in nodes]
    keep = keep_existing_nodes or set()
    store.upsert_entities([r for r in rows if r["id"] not in keep])
    store.insert_missing_entities([r for r in rows if r["id"] in keep])
    store.upsert_relationships([e.as_store_row() for e in edges], source)
    if retire:
        report.retired_edges = store.retire_missing(source, {e.id for e in edges})
    if retire_nodes_of:
        report.retired_nodes = store.retire_entities(retire_nodes_of, {n.id for n in nodes}, set(NODE_EXPORT_TYPES))
    store.bump_revision()
    report.nodes, report.edges = len(nodes), len(edges)
    return report


# ── graph checks after every refresh ────────────────────────────────────────
def graph_checks(graph: nx.MultiDiGraph, rules: Ontology | None = None) -> list[dict[str, Any]]:
    """Six rules over the whole graph. Each result names the rule, the count of failures and the first IDs."""
    rules = rules or ontology()
    live = {n for n, d in graph.nodes(data=True) if not d.get("retired") and d.get("type") != "Unknown"}
    live_edges = [(a, b, d) for a, b, d in graph.edges(data=True) if d["status"] not in ("retired", "rejected")]
    dangling = [d["id"] for a, b, d in live_edges if a not in live or b not in live]
    bad_sig = [f"{d['id']} ({d['type']} {graph.nodes[a].get('type')}->{graph.nodes[b].get('type')})"
               for a, b, d in live_edges if a in live and b in live and not rules.allows(d["type"], graph.nodes[a].get("type"), graph.nodes[b].get("type"))[0]]
    degree = {n: 0 for n in live}
    for a, b, _ in live_edges:
        if a in degree: degree[a] += 1
        if b in degree: degree[b] += 1
    touchable = {t for et in rules.edge_types.values() for t in et.from_types | et.to_types}
    isolated = [n for n, k in degree.items() if k == 0 and graph.nodes[n].get("type") in touchable]
    mentioned = {b for a, b, d in live_edges if d["type"] == "MENTIONS"}
    concept_no_doc = [n for n in live if graph.nodes[n].get("type") == "Concept" and n not in mentioned]
    role_links: dict[str, int] = {}
    for a, b, d in live_edges:
        if d["type"] == "ROLE_AT" and d["status"] == "approved":
            role_links[a] = role_links.get(a, 0) + 1
    bad_roles = [n for n in live if graph.nodes[n].get("type") == "Role" and role_links.get(n, 0) != 1]
    retired = {n for n, d in graph.nodes(data=True) if d.get("retired")}
    live_on_retired = [d["id"] for a, b, d in live_edges if d["status"] == "approved" and (a in retired or b in retired)]

    # What a finding asks of the people who own the packs: an entry nobody links to yet is a gap to review, a broken
    # link is an error to fix before the next load.
    review = "To review: the pack owners add a link or remove the entry. Answers still work."
    fix = "To fix in the packs: the next load keeps it until it is corrected."
    actions = {"dangling_link": fix, "type_signature": fix, "isolated_entity": review,
               "concept_without_document": review, "one_company_link_per_role": fix, "live_link_on_retired_entity": fix}

    def row(rule: str, meaning: str, items: list[str]) -> dict[str, Any]:
        return {"rule": rule, "meaning": meaning, "failures": len(items), "examples": sorted(items)[:5], "ok": not items,
                "action": actions.get(rule, "")}

    return [
        row("dangling_link", "Both ends of every live link are live entities", dangling),
        row("type_signature", "Each link type joins only the entity types its rules allow", bad_sig),
        row("isolated_entity", "Every live entity has at least one live link", isolated),
        row("concept_without_document", "Every concept is mentioned by at least one document", concept_no_doc),
        row("one_company_link_per_role", "Each live role has exactly one approved ROLE_AT link", bad_roles),
        row("live_link_on_retired_entity", "No approved link touches a retired entity", live_on_retired),
    ]
