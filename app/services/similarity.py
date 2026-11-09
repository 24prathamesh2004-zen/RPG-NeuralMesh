"""The similarity layer: SIMILAR_TO links computed from the graph and from text, each with its reason.

Run as a job (make similarity, or python -m scripts.similarity_job). For each pair of live entities of the same
type (Concept, Skill, Role, Document, Asset) two scores are computed: a structural score from shared neighbours
(rare neighbours weigh more) and a textual score from the vectors of label, aliases and description. The top k
per entity above the threshold are written as SIMILAR_TO with provenance method computed, the score as
confidence, and the reason in words. Links the job no longer produces are retired. Declared links written by
people (SAME_AS, RELATED_TO) are not touched, and nothing about a person enters the score.
"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any

import networkx as nx
import numpy as np

from contracts.graph import GraphEdge, Provenance
from knowledge import embedder
from services.ontology import ontology

SOURCE = "job:similarity"
TYPES = ("Concept", "Skill", "Role", "Document", "Asset")
TOP_K = 5
MIN_SCORE = 0.30
STRUCTURAL_WEIGHT = 0.6
TEXT_WEIGHT = 0.4


def _neighbours(g: nx.MultiDiGraph, node: str) -> set[str]:
    hop = ontology().group("hop") | ontology().group("structure")
    out = set()
    for a, b, d in list(g.out_edges(node, data=True)) + list(g.in_edges(node, data=True)):
        if d["type"] in hop and d["status"] in ("approved", "proposed"):  # proposed structure counts, the link says computed
            out.add(b if a == node else a)
    return out


def structural_scores(g: nx.MultiDiGraph, ids: list[str]) -> dict[tuple[str, str], tuple[float, str]]:
    """Weighted overlap of neighbour sets. A neighbour shared by few entities counts more than a common one."""
    neigh = {i: _neighbours(g, i) for i in ids}
    freq: dict[str, int] = defaultdict(int)
    for s in neigh.values():
        for n in s:
            freq[n] += 1
    total = max(1, len(ids))
    weight = {n: math.log(1 + total / f) for n, f in freq.items()}
    out: dict[tuple[str, str], tuple[float, str]] = {}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = neigh[a] & neigh[b]
            if not shared:
                continue
            num = sum(weight[n] for n in shared)
            den = sum(weight[n] for n in neigh[a] | neigh[b]) or 1.0
            score = num / den
            if score > 0:
                labels = ", ".join(g.nodes[n].get("label") or n for n in sorted(shared)[:3])
                out[(a, b)] = (score, f"shares {len(shared)} of {len(neigh[a] | neigh[b])} connections ({labels})")
    return out


def text_scores(g: nx.MultiDiGraph, ids: list[str]) -> dict[tuple[str, str], tuple[float, str]]:
    if not ids or not embedder.available():
        return {}
    texts = []
    for i in ids:
        d = g.nodes[i]
        texts.append(". ".join([d.get("label") or i, *(d.get("aliases") or []), d.get("description") or ""]))
    vectors = embedder.embed(texts)
    sims = vectors @ vectors.T
    out: dict[tuple[str, str], tuple[float, str]] = {}
    for i, a in enumerate(ids):
        for j in range(i + 1, len(ids)):
            s = float(sims[i, j])
            if s >= 0.35:
                out[(a, ids[j])] = (s, f"text score {s:.2f}")
    return out


def compute(g: nx.MultiDiGraph, top_k: int = TOP_K, min_score: float = MIN_SCORE) -> list[GraphEdge]:
    edges: list[GraphEdge] = []
    prov = Provenance(method="computed", by_role="Similarity job")
    for kind in TYPES:
        ids = sorted(n for n, d in g.nodes(data=True) if d.get("type") == kind and not d.get("retired"))
        if len(ids) < 2:
            continue
        struct = structural_scores(g, ids)
        text = text_scores(g, ids)
        combined: dict[str, list[tuple[float, str, str]]] = defaultdict(list)
        for pair in set(struct) | set(text):
            s_score, s_reason = struct.get(pair, (0.0, ""))
            t_score, t_reason = text.get(pair, (0.0, ""))
            # both signals add up. One signal alone must be strong on its own: a text score of 0.5 or more, or a structural one above the floor
            score = max(STRUCTURAL_WEIGHT * s_score + TEXT_WEIGHT * t_score, s_score, t_score if t_score >= 0.5 else 0.0)
            if score < min_score:
                continue
            reason = " and ".join(r for r in (s_reason, t_reason) if r)
            combined[pair[0]].append((score, pair[1], reason))
            combined[pair[1]].append((score, pair[0], reason))
        written: set[tuple[str, str]] = set()
        for a, items in combined.items():
            for score, b, reason in sorted(items, reverse=True)[:top_k]:
                key = tuple(sorted((a, b)))
                if key in written:
                    continue
                written.add(key)
                edges.append(GraphEdge(id=f"rel:similarity/{key[0]}~{key[1]}", type="SIMILAR_TO", **{"from": key[0], "to": key[1]},
                                       status="proposed", provenance=prov, confidence=round(score, 3), properties={"reason": reason, "kind": kind}))
    return edges


def run(mesh) -> dict[str, Any]:
    """Compute on the current graph, write through the intake, rebuild. Returns the counts."""
    edges = compute(mesh.graph)
    report = mesh.load_records(SOURCE, [], edges)
    if not report.ok:
        return {"written": 0, "errors": report.errors}
    mesh.rebuild()
    by_kind: dict[str, int] = defaultdict(int)
    for e in edges:
        by_kind[e.properties["kind"]] += 1
    return {"written": len(edges), "retired": report.retired_edges, "by_type": dict(by_kind)}
