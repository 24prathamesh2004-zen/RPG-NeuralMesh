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

from knowledge import embedder
from services.graph_store import GraphStore

HOP_TYPES = {"RELATED_TO", "BROADER", "SAME_AS"}
JUDGEMENT_TYPES = {"CORROBORATES", "CONFLICTS_WITH", "ADDRESSES_GAP", "SUPERSEDES"}
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


def _rel_id(node: str, rtype: str, a: str, b: str) -> str:
    return f"rel:{node}.export/{rtype}/{a}->{b}"


def role_at(role_id: str) -> dict[str, Any]:
    """The one link from a role to its company. The node export and a talent pack write the same ID, so a role has
    one ROLE_AT link, and it is retired with the last source that still lists the role."""
    node = role_id.split(":", 1)[0]
    return {"id": f"rel:role-at/{role_id}", "type": "ROLE_AT", "from": role_id, "to": f"org:{node}", "status": "approved",
            "properties": {}, "provenance": {"method": "imported", "by_role": "Mesh knowledge curator"}}


class MeshGraph:
    def __init__(self, store: GraphStore) -> None:
        self.store = store
        self.graph: nx.MultiDiGraph = nx.MultiDiGraph()
        self._vocab_ids: list[str] = []
        self._vocab_vectors: np.ndarray | None = None
        self._lock = threading.Lock()

    # ── loading ──────────────────────────────────────────────────────────────
    def load_group_pack(self, pack: dict, source: str | None = None) -> None:
        """A company (Subsidiary) entry belongs to that company's node export: a pack adds it only while the
        node has not exported yet, and never replaces the aliases, level and profile the node gave it."""
        source = source or f"pack:{pack['pack']['pack_id']}"
        entities, companies = [], []
        for e in pack.get("entities", []):
            props = {k: v for k, v in e.items() if k not in ("id", "type", "label")}
            if e["type"] == "Subsidiary":
                props.setdefault("aliases", [e["id"].split(":", 1)[1]])
            item = {"id": e["id"], "type": e["type"], "label": e["label"], "owner": pack["pack"]["owner_role"], "properties": props}
            (companies if e["type"] == "Subsidiary" else entities).append(item)
        self.store.upsert_entities(entities)
        self.store.insert_missing_entities(companies)
        rels = [{**r, "properties": {**r.get("properties", {}), "confidence": r.get("confidence", 1)}}
                for r in pack.get("relationships", [])]
        if pack["pack"].get("scope") == "subsidiary":
            rels += [role_at(e["id"]) for e in pack.get("entities", []) if e["type"] == "Role" and ":" in e["id"]]
        self.store.upsert_relationships(rels, source)
        self.store.retire_missing(source, {r["id"] for r in rels})

    def load_node_export(self, export: dict) -> dict[str, int]:
        node = export["node_id"]
        source = f"node:{node}"
        entities: list[dict] = [{"id": f"org:{node}", "type": "Subsidiary", "label": export.get("display", node),
                                 "owner": "Mesh team", "properties": {"aliases": [node, export.get("display", node)],
                                                                      "level": export.get("level"),
                                                                      "profile": export.get("profile", "")}}]
        rels: list[dict] = []

        def rel(rtype: str, a: str, b: str, props: dict | None = None) -> None:
            rels.append({"id": _rel_id(node, rtype, a, b), "type": rtype, "from": a, "to": b, "status": "approved",
                         "properties": props or {}, "provenance": {"method": "imported", "by_role": "Node export"}})

        for dp in export.get("datapoints", []):
            entities.append({"id": dp["id"], "type": "Datapoint", "label": dp["title"], "owner": dp.get("owner_role"),
                             "sensitivity": dp.get("sensitivity"),
                             "properties": {"subsidiary": node, "code": dp["catalogue_id"], "ceiling": dp.get("ceiling"),
                                            "domain": dp.get("domain"), "purposes_allowed": dp.get("purposes_allowed", []),
                                            "never_leave": dp.get("never_leave", False)}})
            rel("IN_DOMAIN", dp["id"], f"domain:{dp.get('domain')}")
            rel("OWNED_BY", dp["id"], f"org:{node}")
        for doc in export.get("documents", []):
            entities.append({"id": doc["id"], "type": "Document", "label": doc["title"],
                             "properties": {"subsidiary": node, "datapoint": doc["datapoint"], "version": doc.get("version"),
                                            "kind": doc.get("kind"), "tags": doc.get("tags", [])}})
            rel("IN_DATAPOINT", doc["id"], doc["datapoint"])
            for c in doc.get("concepts", []):
                rel("MENTIONS", doc["id"], c)
            for s in doc.get("skills", []):
                rel("EXPLAINS_SKILL", doc["id"], s["skill"], {"level": s["level"]})
            if doc.get("supersedes"):
                rel("SUPERSEDES", doc["id"], doc["supersedes"])
        for ex in export.get("experts", []):
            entities.append({"id": ex["id"], "type": "Expert", "label": ex["role"],
                             "properties": {"subsidiary": node, "consent": True, "keywords": ex.get("keywords", [])}})
            for s in ex.get("skills", []):
                rel("HAS_SKILL", ex["id"], s["skill"], {"level": s.get("level")})
            for ev in ex.get("evidence", []):
                rel("EVIDENCED_BY", ex["id"], ev)
        for e in export.get("entities", []):
            props = {k: v for k, v in e.items() if k not in ("id", "type", "label")}
            entities.append({"id": e["id"], "type": e["type"], "label": e["label"], "properties": props})
            if e["type"] == "Role":
                rels.append(role_at(e["id"]))
        for r in export.get("relationships", []):
            rels.append(r)
        self.store.upsert_entities(entities)
        self.store.upsert_relationships(rels, source)
        retired = self.store.retire_missing(source, {r["id"] for r in rels})
        retired_entities = self.store.retire_entities(node, {e["id"] for e in entities})
        return {"entities": len(entities), "relationships": len(rels), "retired": retired, "retired_entities": retired_entities}

    def rebuild(self) -> None:
        graph = self.store.to_networkx()
        ids, texts = [], []
        for n, data in graph.nodes(data=True):
            if data.get("type") in ("Concept", "Skill"):
                aliases = data.get("aliases") or []
                ids.append(n)
                texts.append(". ".join([data.get("label") or n, *aliases, data.get("description") or ""]))
        vectors = embedder.embed(texts) if (texts and embedder.available()) else None
        with self._lock:
            self.graph = graph
            self._vocab_ids, self._vocab_vectors = ids, vectors

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
        if not concepts and self._vocab_vectors is not None:
            q = embedder.embed([question])[0]
            scores = self._vocab_vectors @ q
            for i in np.argsort(-scores)[:3]:
                if scores[i] >= VOCABULARY_MIN_SCORE:
                    concepts[self._vocab_ids[i]] = f"meaning match {scores[i]:.2f}"
                    by_vector[self._vocab_ids[i]] = float(scores[i])
        return {"concepts": concepts, "named_subsidiaries": sorted(orgs), "vector_matches": by_vector}

    def route(self, concepts: set[str], named: set[str]) -> dict[str, Any]:
        g = self.graph
        hop: set[str] = set()
        for c in concepts:
            if c not in g:
                continue
            for a, b, data in list(g.out_edges(c, data=True)) + list(g.in_edges(c, data=True)):
                if data["type"] in HOP_TYPES and data["status"] == "approved":
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
                        if d["type"] == "PART_OF_SKILL" and d["status"] == "approved":
                            out |= {x for x, _, e in g.in_edges(a, data=True) if e["type"] == "MENTIONS"}
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
                          if e["type"] == "EVIDENCED_BY" and g.nodes[a].get("type") == "Expert"})
        return {"hop_concepts": hop, "direct_docs": direct, "hop_docs": via_hop, "docs": docs, "datapoints": datapoints,
                "subsidiaries": orgs, "domains": domains, "experts": experts, "narrowed_out": set()}

    def _narrow(self, r: dict[str, Any], named: set[str]) -> None:
        """Keep the named subsidiaries, plus any routed subsidiary that an approved cross-subsidiary link joins
        to a document in a routed datapoint of a named one."""
        g = self.graph
        keep = set(named)
        for a, b, data in g.edges(data=True):
            if data["type"] not in JUDGEMENT_TYPES or data["status"] != "approved":
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

    def expand(self, documents: set[str], blocked_subsidiaries: set[str] = frozenset()) -> dict[str, list[dict]]:
        """Approved judgement relationships between the given documents and anything they link to.
        A relationship with an end at a subsidiary that blocked the caller is hidden."""
        g = self.graph
        used, proposed, hidden = [], [], []
        seen = set()
        for d in documents:
            if d not in g:
                continue
            for a, b, data in list(g.out_edges(d, data=True)) + list(g.in_edges(d, data=True)):
                if data["type"] not in JUDGEMENT_TYPES or data["id"] in seen:
                    continue
                seen.add(data["id"])
                item = {"id": data["id"], "type": data["type"], "source": a, "target": b,
                        "source_title": self.label(a), "target_title": self.label(b),
                        "note": data["properties"].get("note"), "approvals": data.get("approvals", []),
                        "status": data["status"]}
                ends = {g.nodes[a].get("subsidiary") or a.split(":", 1)[0], g.nodes[b].get("subsidiary") or b.split(":", 1)[0]}
                if data["status"] == "proposed":
                    proposed.append(item)
                elif data["status"] != "approved":
                    continue
                elif ends & set(blocked_subsidiaries):
                    hidden.append(item)
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

    def links(self) -> list[dict[str, Any]]:
        g = self.graph
        out = []
        for a, b, d in g.edges(data=True):
            if d["type"] in JUDGEMENT_TYPES and d["source"].startswith("pack:group"):
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
