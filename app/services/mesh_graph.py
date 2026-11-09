"""Central mesh graph: load, resolve, route, narrow and expand.

Metadata only. Filled from the group packs and from each node's export_graph tool. Routing walks from the
concepts and skills a question resolves to, through one neighbour step, to documents, datapoints and
subsidiaries, without any model call. The same steps were checked on the ten golden scenarios in
planning_docs/graph_check (10 of 10 routed with aliases).
"""
from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np

from knowledge import adapters, embedder
from services import graph_intake
from knowledge.validator import GROUP_NAMESPACES
from services.graph_store import GraphStore, review_sides
from services.ontology import ontology



def HOP_TYPES() -> frozenset[str]:  # noqa: N802 - read at use, so a rules reload takes effect
    return ontology().group("hop")


def JUDGEMENT_TYPES() -> frozenset[str]:  # noqa: N802
    return ontology().group("judgement")
DOMAIN_OF_LETTER = {"E": "engineering", "O": "operations", "C": "commercial", "R": "research",
                    "F": "corporate", "L": "lessons", "M": "mesh", "T": "talent"}
# Tuned on paraphrased questions: the right concept scores about 0.5, an unrelated one under 0.3.
VOCABULARY_MIN_SCORE = 0.45


def norm_tokens(text: str) -> list[str]:
    text = text.lower().replace("/", " ").replace("-", " ")
    out = []
    for t in re.findall(r"[a-z0-9]+", text):
        if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
            t = t[:-1]
        out.append(t)
    return out


def _phrase_in(phrase: list[str], tokens: list[str]) -> bool:
    n = len(phrase)
    return n > 0 and any(tokens[i:i + n] == phrase for i in range(len(tokens) - n + 1))




class MeshGraph:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._vocab_ids: list[str] = []
        self._vocab_vectors: np.ndarray | None = None
        self._lock = threading.Lock()
        self.last_reports: dict[str, graph_intake.IntakeReport] = {}
        self.loaded_revision = -1
        self.checks: list[dict] = []

    # ── loading: adapter, then intake (validate, sort, normalised file, upsert, retire) ──
    NORMALISED_DIR: Path | None = None

    def load_group_pack(self, pack: dict, source: str | None = None) -> graph_intake.IntakeReport:
        """A company (Subsidiary) entry belongs to that company's node export: a pack adds it only while the
        node has not exported yet, and never replaces the aliases, level and profile the node gave it."""
        source = source or f"pack:{pack['pack']['pack_id']}"
        nodes, edges = adapters.from_pack(pack)
        companies = {n.id for n in nodes if n.type == "Subsidiary"}
        report = graph_intake.load(self.store, source, nodes, edges, keep_existing_nodes=companies, normalised_dir=self.NORMALISED_DIR)
        if report.errors:
            raise ValueError(f"{source}: " + "; ".join(report.errors[:5]))
        self.last_reports[source] = report
        return report

    def load_node_export(self, export: dict) -> dict[str, int]:
        node = export["node_id"]
        source = f"node:{node}"
        nodes, edges = adapters.from_node_export(export)
        report = graph_intake.load(self.store, source, nodes, edges, retire_nodes_of=node, normalised_dir=self.NORMALISED_DIR)
        if report.errors:
            raise ValueError(f"{source}: " + "; ".join(report.errors[:5]))
        self.last_reports[source] = report
        return {"entities": report.nodes, "relationships": report.edges, "retired": report.retired_edges, "retired_entities": report.retired_nodes}

    def load_records(self, source: str, nodes: list, edges: list, retire: bool = True) -> graph_intake.IntakeReport:
        """Any adapter's output (CSV, JSON Lines, an application ontology) through the same intake. A company entry
        is never overwritten: it belongs to the company's own node export. retire=False for one event at a time."""
        companies = {n.id for n in nodes if n.type == "Subsidiary"}
        report = graph_intake.load(self.store, source, nodes, edges, keep_existing_nodes=companies, normalised_dir=self.NORMALISED_DIR, retire=retire)
        self.last_reports[source] = report
        return report

    def rebuild(self) -> None:
        graph, revision = self.store.to_networkx()
        ids, texts = [], []
        for n, data in graph.nodes(data=True):
            if data.get("type") in ("Concept", "Skill") and not data.get("retired"):
                aliases = data.get("aliases") or []
                ids.append(n)
                texts.append(". ".join([data.get("label") or n, *aliases, data.get("description") or ""]))
        vectors = embedder.embed(texts) if (texts and embedder.available()) else None
        checks = graph_intake.graph_checks(graph)
        with self._lock:
            self.graph = graph
            self._vocab_ids, self._vocab_vectors = ids, vectors
            self.loaded_revision = revision
            self.checks = checks

    def refresh_if_stale(self) -> bool:
        """Rebuild the in-memory copy when another process wrote the store since this one loaded it."""
        if self.store.revision() != self.loaded_revision:
            self.rebuild()
            return True
        return False

    # ── query steps ──────────────────────────────────────────────────────────
    def label(self, entity_id: str) -> str:
        return (self.graph.nodes[entity_id].get("label") if entity_id in self.graph else None) or entity_id

    def resolve(self, question: str) -> dict[str, Any]:
        """Concepts and skills by label and alias (whole phrase), then by the vocabulary index. Named subsidiaries."""
        tokens = norm_tokens(question)
        concepts: dict[str, str] = {}
        orgs: set[str] = set()
        for n, data in self.graph.nodes(data=True):
            kind = data.get("type")
            if kind not in ("Concept", "Skill", "Subsidiary") or data.get("retired"):
                continue
            for name in [data.get("label") or "", *(data.get("aliases") or [])]:
                if _phrase_in(norm_tokens(name), tokens):
                    if kind == "Subsidiary":
                        orgs.add(n.split(":", 1)[1])
                    else:
                        concepts.setdefault(n, name)
                    break
        by_vector: dict[str, float] = {}
        with self._lock:
            vocab_ids, vocab_vectors = self._vocab_ids, self._vocab_vectors
        if not concepts and vocab_vectors is not None:
            q = embedder.embed([question])[0]
            scores = vocab_vectors @ q
            for i in np.argsort(-scores)[:3]:
                if scores[i] >= VOCABULARY_MIN_SCORE:
                    concepts[vocab_ids[i]] = f"meaning match {scores[i]:.2f}"
                    by_vector[vocab_ids[i]] = float(scores[i])
        return {"concepts": concepts, "named_subsidiaries": sorted(orgs), "vector_matches": by_vector}

    def route(self, concepts: set[str], named: set[str]) -> dict[str, Any]:
        g = self.graph
        hop: set[str] = set()
        for c in concepts:
            if c not in g:
                continue
            for a, b, data in list(g.out_edges(c, data=True)) + list(g.in_edges(c, data=True)):
                if data["type"] in HOP_TYPES() and data["status"] == "approved":
                    hop.add(b if a == c else a)
        hop -= concepts

        def docs_of(entities: set[str]) -> set[str]:
            out = set()
            for c in entities:
                if c not in g:
                    continue
                for a, _, d in g.in_edges(c, data=True):
                    if d["type"] in ("MENTIONS", "EXPLAINS_SKILL") and d["status"] == "approved" and g.nodes[a].get("type") == "Document":
                        out.add(a)
                if g.nodes[c].get("type") == "Skill":  # concepts that are part of the skill
                    for a, _, d in g.in_edges(c, data=True):
                        if d["type"] == "PART_OF_SKILL" and d["status"] == "approved" and not g.nodes[a].get("retired"):
                            out |= {x for x, _, e in g.in_edges(a, data=True)
                                    if e["type"] == "MENTIONS" and e["status"] == "approved" and g.nodes[x].get("type") == "Document" and not g.nodes[x].get("retired")}
            return out

        direct = docs_of(concepts)
        via_hop = docs_of(hop) - direct
        result = self._summarise(direct, via_hop, hop)
        if named:
            self._narrow(result, set(named))
        return result

    def _summarise(self, direct: set[str], via_hop: set[str], hop: set[str]) -> dict[str, Any]:
        g = self.graph
        docs = direct | via_hop
        datapoints = {g.nodes[d].get("datapoint") for d in docs if g.nodes[d].get("datapoint")}
        orgs = {g.nodes[d].get("subsidiary") for d in docs if g.nodes[d].get("subsidiary")}
        domains: dict[str, set[str]] = {}
        for dp in datapoints:
            node, code = dp.split(":", 1)
            domain = (g.nodes[dp].get("domain") if dp in g else None) or DOMAIN_OF_LETTER.get(code[0], "corporate")
            domains.setdefault(node, set()).add(domain)
        experts = sorted({a for d in docs for a, _, e in g.in_edges(d, data=True)
                          if e["type"] == "EVIDENCED_BY" and e["status"] == "approved" and g.nodes[a].get("type") == "Expert" and not g.nodes[a].get("retired")})
        return {"hop_concepts": hop, "direct_docs": direct, "hop_docs": via_hop, "docs": docs, "datapoints": datapoints,
                "subsidiaries": orgs, "domains": domains, "experts": experts, "narrowed_out": set()}

    def _narrow(self, r: dict[str, Any], named: set[str]) -> None:
        """Keep the named subsidiaries, plus any routed subsidiary that an approved cross-subsidiary link joins
        to a document in a routed datapoint of a named one."""
        g = self.graph
        keep = set(named)
        for a, b, data in g.edges(data=True):
            if data["type"] not in JUDGEMENT_TYPES() or data["status"] != "approved":
                continue
            if g.nodes[a].get("type") != "Document" or g.nodes[b].get("type") != "Document":
                continue
            for x, y in ((a, b), (b, a)):
                sx, sy = g.nodes[x].get("subsidiary"), g.nodes[y].get("subsidiary")
                if x in r["docs"] and sx not in named and sy in named and g.nodes[y].get("datapoint") in r["datapoints"]:
                    keep.add(sx)
        kept_docs = {d for d in r["docs"] if g.nodes[d].get("subsidiary") in keep}
        narrowed = self._summarise(r["direct_docs"] & kept_docs, r["hop_docs"] & kept_docs, r["hop_concepts"])
        narrowed["narrowed_out"] = r["subsidiaries"] - keep
        narrowed["subsidiaries"] |= named & keep
        r.clear()
        r.update(narrowed)

    def expand(self, documents: set[str], blocked_subsidiaries: set[str] = frozenset(),
               only: set[str] | None = None) -> dict[str, list[dict]]:
        """Approved judgement relationships between the given documents and anything they link to.
        A relationship with an end at a subsidiary that blocked the caller is hidden, and so is one with an end outside
        ``only``, the companies the person chose to ask."""
        g = self.graph
        used, proposed, hidden = [], [], []
        seen = set()
        for d in documents:
            if d not in g:
                continue
            for a, b, data in list(g.out_edges(d, data=True)) + list(g.in_edges(d, data=True)):
                if data["type"] not in JUDGEMENT_TYPES() or data["id"] in seen:
                    continue
                seen.add(data["id"])
                item = {"id": data["id"], "type": data["type"], "source": a, "target": b,
                        "source_title": self.label(a), "target_title": self.label(b),
                        "note": data["properties"].get("note"), "approvals": data.get("approvals", []),
                        "status": data["status"]}
                ends = {g.nodes[a].get("subsidiary") or a.split(":", 1)[0], g.nodes[b].get("subsidiary") or b.split(":", 1)[0]}
                if data["status"] not in ("proposed", "approved"):
                    continue
                # an end of shared vocabulary (a skill, a concept) belongs to no company, so a choice never hides it
                if ends & set(blocked_subsidiaries) or (only is not None and not (ends - GROUP_NAMESPACES) <= only):
                    hidden.append(item)
                elif data["status"] == "proposed":
                    proposed.append(item)
                else:
                    used.append(item)
        key = lambda x: x["id"]  # noqa: E731
        return {"used": sorted(used, key=key), "proposed": sorted(proposed, key=key), "hidden": sorted(hidden, key=key)}

    # ── reads for the context API and the screens ────────────────────────────
    def neighbours(self, entity_id: str, rtype: str, direction: str = "out") -> list[tuple[str, dict]]:
        g = self.graph
        if entity_id not in g:
            return []
        edges = g.out_edges(entity_id, data=True) if direction == "out" else g.in_edges(entity_id, data=True)
        out = []
        for a, b, data in edges:
            if data["type"] == rtype and data["status"] == "approved":
                out.append((b if direction == "out" else a, data))
        return out

    def view(self) -> dict[str, Any]:
        g = self.graph
        nodes = [{"id": n, "type": d.get("type"), "label": d.get("label") or n, "subsidiary": d.get("subsidiary")}
                 for n, d in g.nodes(data=True) if not d.get("retired")]
        live = {n["id"] for n in nodes}
        edges = [{"id": d["id"], "type": d["type"], "source": a, "target": b, "status": d["status"]}
                 for a, b, d in g.edges(data=True) if d["status"] != "retired" and a in live and b in live]
        counts: dict[str, int] = {}
        for n in nodes:
            counts[n["type"]] = counts.get(n["type"], 0) + 1
        return {"nodes": nodes, "edges": edges, "counts": counts}

    # ── who may see an entity of the central graph ──────────────────────────────
    def never_leave_owner(self, entity_id: str) -> str | None:
        """The company of an entity of a never-leave datapoint: the datapoint itself, or a document in it. The central
        graph keeps the metadata of such an entity, but shows it only to that company and to mesh admins. Anyone else
        learns of it only when the owning node reports it as withheld in an answer, which the node decides per question
        and audits."""
        d = self.graph.nodes.get(entity_id) or {}
        kind = d.get("type")
        datapoint = d if kind == "Datapoint" else (self.graph.nodes.get(d.get("datapoint") or "") or {}) if kind == "Document" else {}
        if not datapoint.get("never_leave"):
            return None
        return str(d.get("subsidiary") or entity_id.split(":", 1)[0])

    def shown_to(self, entity_id: str, company: str | None, roles: list[str] | tuple[str, ...] = ()) -> bool:
        owner = self.never_leave_owner(entity_id)
        return owner is None or owner == company or "mesh_admin" in roles

    def proposals(self) -> list[dict[str, Any]]:
        """The links an application proposed (source app:<id>) that were loaded as proposed, with their status now and the
        sides that approve them: the company of each end that has a Mesh Node, or the group for the application's own
        vocabulary, which a mesh admin approves as curator."""
        g = self.graph
        out = []
        for a, b, d in g.edges(data=True):
            source = d.get("source") or ""
            if not source.startswith("app:") or not d.get("proposed") or d["status"] == "retired":
                continue
            reviewed = {v.get("subsidiary") for v in d.get("approvals", []) if v.get("decision")}
            out.append({"id": d["id"], "type": d["type"], "source": a, "target": b, "source_title": self.label(a),
                        "target_title": self.label(b), "source_type": g.nodes[a].get("type"), "target_type": g.nodes[b].get("type"),
                        "status": d["status"], "application": source.split(":", 1)[1].split("/", 1)[0],
                        "sides": sorted(review_sides(g, a, b)), "reviewed_by": sorted(s for s in reviewed if s),
                        "approvals": d.get("approvals", [])})
        return sorted(out, key=lambda x: (x["application"], x["type"], x["id"]))

    def links(self) -> list[dict[str, Any]]:
        g = self.graph
        out = []
        for a, b, d in g.edges(data=True):
            if d["type"] in JUDGEMENT_TYPES() and d["source"].startswith("pack:group"):
                out.append({"id": d["id"], "type": d["type"], "source": a, "target": b, "source_title": self.label(a),
                            "target_title": self.label(b), "status": d["status"], "note": d["properties"].get("note"),
                            "confidence": d["properties"].get("confidence"), "provenance": d["provenance"], "approvals": d["approvals"],
                            "sides": sorted({a.split(":", 1)[0], b.split(":", 1)[0]})})
        return sorted(out, key=lambda x: x["id"])


def load_group_pack_files(graph: MeshGraph, folders: list[Path]) -> list[str]:
    loaded = []
    for folder in folders:
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("group.*.pack.json")):
            pack = json.loads(path.read_text(encoding="utf-8"))
            graph.load_group_pack(pack)
            loaded.append(pack["pack"]["pack_id"])
    return loaded
