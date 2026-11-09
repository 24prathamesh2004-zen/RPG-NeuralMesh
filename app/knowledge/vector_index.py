"""Chroma vector store per knowledge pack, embedded in the node process (no server).

One Chroma store lives in each pack's build folder (`build/chroma`), so vectors of one company never sit in a
store of another. Each chunk is stored with its ID (<node>:<document> or <node>:<document>#<n>), its text and
its fields (datapoint, mode, sensitivity, version, stale, title). A rebuild embeds only chunks that are new or
changed and deletes chunks the pack no longer has.

Only text that the node's FTS5 index already holds is embedded: the text allowed to leave the node
in the document's exposure mode. Gated bodies and restricted bodies are never read here.
"""
from __future__ import annotations

import threading
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np

from knowledge import embedder

STORE_DIR = "chroma"
COLLECTION = "chunks"
OLD_FILES = ("vectors.faiss", "chunks.db")  # the earlier FAISS files, removed on the first Chroma build
_FIELDS = ("datapoint", "mode", "sensitivity", "version", "stale", "title")
_lock = threading.Lock()
_open: dict[str, tuple[float, Any]] = {}  # store path -> (newest file time, collection)


@dataclass(frozen=True)
class ChunkRow:
    row_key: str        # the doc_id of the FTS row: <node>:<document> or <node>:<document>#<n>
    datapoint: str      # catalogue code, for example E-03
    mode: str
    sensitivity: str
    version: str
    stale: int
    text: str
    title: str


def _newest(path: Path) -> float:
    """The change stamp of a store: its sqlite file and write-ahead log (a build writes through them), not a walk of the whole folder."""
    stamps = []
    for name in ("chroma.sqlite3", "chroma.sqlite3-wal"):
        try:
            stamps.append((path / name).stat().st_mtime_ns)
        except OSError:
            pass
    return float(max(stamps, default=0))


def _evict_system(key: str) -> None:
    """Chroma keeps one in-memory system for each store path, so a new client would get the old data back. Stop and drop
    the system of this store only."""
    from chromadb.api.shared_system_client import SharedSystemClient
    for identifier in [i for i in list(SharedSystemClient._identifier_to_system) if str(i) == key]:
        system = SharedSystemClient._identifier_to_system.pop(identifier, None)
        SharedSystemClient._identifier_to_refcount.pop(identifier, None)
        try:
            if system is not None:
                system.stop()
        except Exception:  # noqa: BLE001 - a system that cannot stop is dropped all the same
            pass


def _collection(path: Path, create: bool) -> Any:
    """One open collection per store, opened again when another process (the pack build) changed the files."""
    import chromadb
    from chromadb.config import Settings

    key = str(path)
    with _lock:
        stamp = _newest(path)
        cached = _open.get(key)
        if cached and cached[0] == stamp:
            return cached[1]
        if cached:
            _open.pop(key, None)  # only this store is opened again: the handles of other packs stay in use
            _evict_system(key)
        client = chromadb.PersistentClient(path=key, settings=Settings(anonymized_telemetry=False))
        if create:
            col = client.get_or_create_collection(COLLECTION, embedding_function=None, metadata={"hnsw:space": "cosine"})
        else:
            col = client.get_collection(COLLECTION, embedding_function=None)
        _open[key] = (_newest(path), col)
        return col


class VectorIndex:
    """Cosine search over one pack's chunks in an embedded Chroma store."""

    def __init__(self, build_dir: Path) -> None:
        self.build_dir = build_dir
        self.path = build_dir / STORE_DIR

    def exists(self) -> bool:
        return (self.path / "chroma.sqlite3").is_file()

    def build(self, rows: list[ChunkRow]) -> int:
        """Add new and changed chunks, delete removed ones. Returns the number of chunks in the store."""
        self.build_dir.mkdir(parents=True, exist_ok=True)
        for name in OLD_FILES:
            (self.build_dir / name).unlink(missing_ok=True)
        col = _collection(self.path, create=True)
        stored = col.get(include=["documents", "metadatas"])
        before = {i: (d, m) for i, d, m in zip(stored["ids"], stored["documents"], stored["metadatas"])}
        wanted = {r.row_key: r for r in rows}
        changed = [r for r in sorted(rows, key=lambda r: r.row_key)
                   if before.get(r.row_key) != (r.text, self._meta(r))]
        if changed:
            vectors = embedder.embed([f"{r.title}. {r.text}" for r in changed])
            col.upsert(ids=[r.row_key for r in changed], embeddings=[v.tolist() for v in vectors],
                       documents=[r.text for r in changed], metadatas=[self._meta(r) for r in changed])
        removed = sorted(set(before) - set(wanted))
        if removed:
            col.delete(ids=removed)
        with _lock:
            _open.pop(str(self.path), None)
        return len(wanted)

    @staticmethod
    def _meta(r: ChunkRow) -> dict[str, Any]:
        row = asdict(r)
        return {k: row[k] for k in _FIELDS}

    def search(self, query_vector: np.ndarray, top_k: int = 30, min_score: float = 0.25) -> list[tuple[str, float]]:
        if not self.exists():
            return []
        try:
            col = _collection(self.path, create=False)
        except Exception:  # noqa: BLE001 - a build that stopped midway leaves no collection: no hits, not an error
            return []
        count = col.count()
        if count == 0:
            return []
        result = col.query(query_embeddings=[query_vector.astype("float32").tolist()], n_results=min(top_k, count),
                           include=["distances"])
        out = [(i, 1.0 - float(d)) for i, d in zip(result["ids"][0], result["distances"][0])]
        return [(i, s) for i, s in out if s >= min_score]

    def all_text(self) -> str:
        """Every stored title and text, in ID order, for the canary check."""
        if not self.exists():
            return ""
        stored = _collection(self.path, create=False).get(include=["documents", "metadatas"])
        rows = sorted(zip(stored["ids"], stored["documents"], stored["metadatas"]))
        return " ".join(f"{m.get('title', '')} {d or ''}" for _, d, m in rows)

