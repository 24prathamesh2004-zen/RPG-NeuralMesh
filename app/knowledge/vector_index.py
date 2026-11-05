"""FAISS index per knowledge pack, with a chunk table that maps each vector to its row.

Only text that the node's FTS5 index already holds is embedded: the text allowed to leave the node
in the document's exposure mode. Gated bodies and restricted bodies are never read here.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from knowledge import embedder

INDEX_FILE = "vectors.faiss"
CHUNKS_FILE = "chunks.db"


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


class VectorIndex:
    """Exact cosine search (FAISS IndexFlatIP on normalised vectors) over one pack's rows."""

    def __init__(self, build_dir: Path) -> None:
        self.build_dir = build_dir

    def exists(self) -> bool:
        return (self.build_dir / INDEX_FILE).is_file() and (self.build_dir / CHUNKS_FILE).is_file()

    def build(self, rows: list[ChunkRow]) -> int:
        import faiss

        self.build_dir.mkdir(parents=True, exist_ok=True)
        rows = sorted(rows, key=lambda r: r.row_key)
        vectors = embedder.embed([f"{r.title}. {r.text}" for r in rows]) if rows else np.zeros((0, embedder.DIMENSIONS), "float32")
        index = faiss.IndexFlatIP(embedder.DIMENSIONS)
        if len(rows):
            index.add(vectors)
        faiss.write_index(index, str(self.build_dir / INDEX_FILE))
        db_path = self.build_dir / CHUNKS_FILE
        if db_path.exists():
            db_path.unlink()
        con = sqlite3.connect(db_path)
        con.execute(
            "CREATE TABLE chunks(vector_id INTEGER PRIMARY KEY, row_key TEXT UNIQUE, datapoint TEXT, mode TEXT,"
            " sensitivity TEXT, version TEXT, stale INTEGER, title TEXT, text TEXT)"
        )
        con.executemany(
            "INSERT INTO chunks VALUES (?,?,?,?,?,?,?,?,?)",
            [(i, r.row_key, r.datapoint, r.mode, r.sensitivity, r.version, r.stale, r.title, r.text) for i, r in enumerate(rows)],
        )
        con.commit()
        con.close()
        return len(rows)

    def search(self, query_vector: np.ndarray, top_k: int = 30, min_score: float = 0.25) -> list[tuple[str, float]]:
        import faiss

        if not self.exists():
            return []
        index = faiss.read_index(str(self.build_dir / INDEX_FILE))
        if index.ntotal == 0:
            return []
        scores, ids = index.search(query_vector.reshape(1, -1).astype("float32"), min(top_k, index.ntotal))
        con = sqlite3.connect(f"file:{(self.build_dir / CHUNKS_FILE).as_posix()}?mode=ro", uri=True)
        try:
            out = []
            for score, vid in zip(scores[0], ids[0]):
                if vid < 0 or score < min_score:
                    continue
                row = con.execute("SELECT row_key FROM chunks WHERE vector_id=?", (int(vid),)).fetchone()
                if row:
                    out.append((row[0], float(score)))
            return out
        finally:
            con.close()

    def all_text(self) -> str:
        if not self.exists():
            return ""
        con = sqlite3.connect(self.build_dir / CHUNKS_FILE)
        try:
            return " ".join(r[0] or "" for r in con.execute("SELECT title || ' ' || text FROM chunks"))
        finally:
            con.close()
