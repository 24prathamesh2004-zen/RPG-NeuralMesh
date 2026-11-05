"""What a node knows about its own packs: documents, concepts, versions, and the hybrid search over them.

Search runs FTS5 keyword search over the node's index.db and FAISS vector search over each pack's
build folder, then merges the two ranked lists (and a list of documents that mention the routed concepts)
by reciprocal rank fusion: each row scores 1 / (60 + rank) in each list and the scores are added.
"""
from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from knowledge import embedder
from knowledge.vector_index import VectorIndex

RRF_K = 60
CANDIDATES_PER_LIST = 30


@dataclass
class NodeKnowledge:
    packs: list[dict] = field(default_factory=list)
    documents: dict[str, dict] = field(default_factory=dict)        # <node>:<doc> -> document entry + pack fields
    datapoint_domain: dict[str, str] = field(default_factory=dict)  # catalogue code -> domain
    datapoint_purposes: dict[str, list[str]] = field(default_factory=dict)
    superseded_by: dict[str, str] = field(default_factory=dict)
    pack_dirs: dict[str, Path] = field(default_factory=dict)        # domain -> pack folder
    relationships: list[dict] = field(default_factory=list)


def load_node_knowledge(node_dir: Path) -> NodeKnowledge:
    knowledge = NodeKnowledge()
    for pack_path in sorted((node_dir / "packs").glob("*/pack.json")):
        pack = json.loads(pack_path.read_text(encoding="utf-8"))
        domain = pack["pack"]["domain"]
        knowledge.packs.append(pack)
        knowledge.pack_dirs[domain] = pack_path.parent
        for dp in pack.get("datapoints", []):
            knowledge.datapoint_domain[dp["catalogue_id"]] = domain
            knowledge.datapoint_purposes[dp["catalogue_id"]] = list(dp.get("purposes_allowed", []))
        for doc in pack.get("documents", []):
            knowledge.documents[doc["id"]] = {**doc, "pack_version": pack["pack"]["published_at"], "domain": domain}
            if doc.get("supersedes"):
                knowledge.superseded_by[doc["supersedes"]] = doc["id"]
        knowledge.relationships.extend(pack.get("relationships", []))
    return knowledge


STOPWORDS = frozenset(
    "a an and are as at be been but by can could do does for from had has have how i in into is it its me my of on or "
    "our should so than that the their them then there these they this to us was we were what when where which who why "
    "will with would you your".split()
)


def fts_query(query: str) -> str:
    """OR of the query words. Common words are left out, since OR over "the" matches every row."""
    tokens = re.findall(r"[\w-]+", query, flags=re.UNICODE)[:24]
    content = [t for t in tokens if t.lower() not in STOPWORDS]
    return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in content)


def _fts_keys(index_path: Path, query: str) -> list[str]:
    normalized = fts_query(query[:1000])
    if not normalized:
        return []
    connection = sqlite3.connect(f"file:{index_path.as_posix()}?mode=ro", uri=True)
    try:
        rows = connection.execute(
            "SELECT doc_id FROM idx WHERE idx MATCH ? ORDER BY bm25(idx) LIMIT ?",
            (normalized, CANDIDATES_PER_LIST),
        ).fetchall()
    except sqlite3.OperationalError:
        rows = []
    finally:
        connection.close()
    return [r[0] for r in rows]


def _vector_keys(knowledge: NodeKnowledge, query: str, domains: set[str] | None) -> list[tuple[str, float]]:
    if not embedder.available() or not knowledge.pack_dirs:
        return []
    vector = embedder.embed([query[:1000]])[0]
    hits: list[tuple[str, float]] = []
    for domain, pack_dir in knowledge.pack_dirs.items():
        if domains and domain not in domains:
            continue
        hits.extend(VectorIndex(pack_dir / "build").search(vector, CANDIDATES_PER_LIST))
    hits.sort(key=lambda h: -h[1])
    return hits[:CANDIDATES_PER_LIST]


def _concept_keys(knowledge: NodeKnowledge, all_keys: list[str], concepts: set[str]) -> list[str]:
    if not concepts:
        return []
    scored = []
    for key in all_keys:
        doc = knowledge.documents.get(key.split("#", 1)[0], {})
        overlap = len(concepts.intersection(doc.get("concepts", [])))
        if overlap:
            scored.append((overlap, key))
    scored.sort(key=lambda s: (-s[0], s[1]))
    return [k for _, k in scored]


def hybrid_rank(index_path: Path, knowledge: NodeKnowledge, query: str, *, domains: set[str] | None = None,
                concepts: set[str] | None = None, limit: int = 10) -> tuple[list[tuple[str, float, int]], dict[str, Any]]:
    """Return [(row_key, rrf_score, rank)] and a small trace of what each list contributed."""
    keyword = _fts_keys(index_path, query)
    vector = [k for k, _ in _vector_keys(knowledge, query, domains)]
    if domains:
        keyword = [k for k in keyword if _domain_of_key(knowledge, k) in domains]
    connection = sqlite3.connect(f"file:{index_path.as_posix()}?mode=ro", uri=True)
    try:
        every_key = [r[0] for r in connection.execute("SELECT doc_id FROM idx")]
    finally:
        connection.close()
    if domains:
        every_key = [k for k in every_key if _domain_of_key(knowledge, k) in domains]
    concept = _concept_keys(knowledge, every_key, set(concepts or ())) if (keyword or vector) else []
    scores: dict[str, float] = {}
    for ranked in (keyword, vector, concept):
        for rank, key in enumerate(ranked, start=1):
            scores[key] = scores.get(key, 0.0) + 1.0 / (RRF_K + rank)
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))[:limit]
    trace = {"keyword_hits": len(keyword), "vector_hits": len(vector), "concept_hits": len(concept)}
    return [(key, score, i + 1) for i, (key, score) in enumerate(ordered)], trace


def _domain_of_key(knowledge: NodeKnowledge, key: str) -> str | None:
    doc = knowledge.documents.get(key.split("#", 1)[0])
    if doc:
        return doc["domain"]
    parts = key.split(":")
    return knowledge.datapoint_domain.get(parts[1]) if len(parts) > 1 else None
