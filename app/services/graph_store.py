"""Central mesh graph store: two SQLite tables (entities, relationships) plus link reviews.

Rows are updated in place by ID, so loading the same export twice changes nothing. A relationship is
retired, never deleted. Link reviews by each side's owner role live in their own table, and the
effective status of a proposed cross-subsidiary link is computed from them.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import date
from pathlib import Path
from typing import Any

import networkx as nx

_SCHEMA = """
CREATE TABLE IF NOT EXISTS entities(
  id TEXT PRIMARY KEY, type TEXT NOT NULL, label TEXT, owner TEXT, sensitivity TEXT, properties TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS relationships(
  id TEXT PRIMARY KEY, type TEXT NOT NULL, from_id TEXT NOT NULL, to_id TEXT NOT NULL, status TEXT NOT NULL,
  properties TEXT NOT NULL DEFAULT '{}', provenance TEXT NOT NULL DEFAULT '{}', approvals TEXT NOT NULL DEFAULT '[]',
  source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS link_reviews(
  rel_id TEXT NOT NULL, subsidiary TEXT NOT NULL, role TEXT NOT NULL, decision TEXT NOT NULL, reviewed_on TEXT NOT NULL,
  reviewer TEXT NOT NULL, PRIMARY KEY (rel_id, subsidiary));
"""


class GraphStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def upsert_entities(self, entities: list[dict[str, Any]]) -> None:
        with self._lock, self._connect() as con:
            con.executemany(
                "INSERT INTO entities(id,type,label,owner,sensitivity,properties) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET type=excluded.type,label=excluded.label,owner=excluded.owner,"
                "sensitivity=excluded.sensitivity,properties=excluded.properties",
                [(e["id"], e["type"], e.get("label"), e.get("owner"), e.get("sensitivity"),
                  json.dumps(e.get("properties", {}), sort_keys=True)) for e in entities],
            )

    def insert_missing_entities(self, entities: list[dict[str, Any]]) -> None:
        """Add entities that are not stored yet and leave stored ones as they are."""
        with self._lock, self._connect() as con:
            con.executemany(
                "INSERT INTO entities(id,type,label,owner,sensitivity,properties) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                [(e["id"], e["type"], e.get("label"), e.get("owner"), e.get("sensitivity"),
                  json.dumps(e.get("properties", {}), sort_keys=True)) for e in entities],
            )

    def upsert_relationships(self, rels: list[dict[str, Any]], source: str) -> None:
        with self._lock, self._connect() as con:
            con.executemany(
                "INSERT INTO relationships(id,type,from_id,to_id,status,properties,provenance,approvals,source) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET type=excluded.type,from_id=excluded.from_id,"
                "to_id=excluded.to_id,status=excluded.status,properties=excluded.properties,"
                "provenance=excluded.provenance,approvals=excluded.approvals,source=excluded.source",
                [(r["id"], r["type"], r["from"], r["to"], r.get("status", "approved"),
                  json.dumps(r.get("properties", {}), sort_keys=True), json.dumps(r.get("provenance", {}), sort_keys=True),
                  json.dumps(r.get("approvals", []), sort_keys=True), source) for r in rels],
            )

    def retire_missing(self, source: str, keep_ids: set[str]) -> int:
        """Relationships of a source that a new load no longer contains are retired, not deleted."""
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT id FROM relationships WHERE source=? AND status!='retired'", (source,)).fetchall()
            gone = [r["id"] for r in rows if r["id"] not in keep_ids]
            con.executemany("UPDATE relationships SET status='retired' WHERE id=?", [(g,) for g in gone])
            return len(gone)

    def retire_entities(self, subsidiary: str, keep_ids: set[str]) -> int:
        """Entities of a subsidiary that its latest export no longer lists are marked retired, never deleted."""
        with self._lock, self._connect() as con:
            rows = con.execute("SELECT id, properties FROM entities").fetchall()
            gone = []
            for r in rows:
                props = json.loads(r["properties"])
                if props.get("subsidiary") == subsidiary and r["id"] not in keep_ids and not props.get("retired"):
                    props["retired"] = True
                    gone.append((json.dumps(props, sort_keys=True), r["id"]))
            con.executemany("UPDATE entities SET properties=? WHERE id=?", gone)
            ids = [g[1] for g in gone]
            if ids:
                marks = ",".join("?" * len(ids))
                con.execute(f"UPDATE relationships SET status='retired' WHERE status!='retired' AND (from_id IN ({marks}) OR to_id IN ({marks}))",
                            ids + ids)
            return len(gone)

    def exported_sources(self) -> set[str]:
        with self._connect() as con:
            return {r[0] for r in con.execute("SELECT DISTINCT source FROM relationships WHERE source LIKE 'node:%' AND status != 'retired'")}

    def retire_source(self, source: str) -> int:
        """A node that left the registry: retire all its relationships and the entities of its subsidiary."""
        self.retire_missing(source, set())
        if source.startswith("node:"):
            node = source.split(":", 1)[1]
            self.retire_entities(node, set())
            with self._lock, self._connect() as con:
                row = con.execute("SELECT properties FROM entities WHERE id=?", (f"org:{node}",)).fetchone()
                if row is not None:
                    props = json.loads(row["properties"])
                    props["retired"] = True
                    con.execute("UPDATE entities SET properties=? WHERE id=?", (json.dumps(props, sort_keys=True), f"org:{node}"))
        with self._connect() as con:
            return con.execute("SELECT COUNT(*) FROM relationships WHERE source=? AND status='retired'", (source,)).fetchone()[0]

    def review_link(self, rel_id: str, subsidiary: str, role: str, decision: str, reviewer: str) -> None:
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        with self._lock, self._connect() as con:
            row = con.execute("SELECT from_id, to_id FROM relationships WHERE id=?", (rel_id,)).fetchone()
            if row is None:
                raise KeyError(rel_id)
            sides = {row["from_id"].split(":", 1)[0], row["to_id"].split(":", 1)[0]}
            if subsidiary not in sides:
                raise ValueError(f"{subsidiary} is not a side of {rel_id}")
            con.execute(
                "INSERT INTO link_reviews VALUES (?,?,?,?,?,?) ON CONFLICT(rel_id, subsidiary) DO UPDATE SET "
                "role=excluded.role, decision=excluded.decision, reviewed_on=excluded.reviewed_on, reviewer=excluded.reviewer",
                (rel_id, subsidiary, role, decision, date.today().isoformat(), reviewer),
            )

    def reviews(self) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as con:
            out: dict[str, list[dict[str, Any]]] = {}
            for r in con.execute("SELECT * FROM link_reviews"):
                out.setdefault(r["rel_id"], []).append(dict(r))
            return out

    def counts(self) -> dict[str, int]:
        with self._connect() as con:
            return {
                "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "relationships": con.execute("SELECT COUNT(*) FROM relationships").fetchone()[0],
            }

    def to_networkx(self) -> nx.MultiDiGraph:
        graph = nx.MultiDiGraph()
        reviews = self.reviews()
        with self._connect() as con:
            for e in con.execute("SELECT * FROM entities"):
                graph.add_node(e["id"], type=e["type"], label=e["label"], owner=e["owner"], sensitivity=e["sensitivity"],
                               **json.loads(e["properties"]))
            for r in con.execute("SELECT * FROM relationships"):
                approvals = json.loads(r["approvals"])
                status = effective_status(r["status"], r["from_id"], r["to_id"], approvals, reviews.get(r["id"], []))
                for end in (r["from_id"], r["to_id"]):
                    if end not in graph:
                        graph.add_node(end, type="Unknown", label=end)
                graph.add_edge(r["from_id"], r["to_id"], key=r["id"], id=r["id"], type=r["type"], status=status,
                               properties=json.loads(r["properties"]), provenance=json.loads(r["provenance"]),
                               approvals=approvals + [{"subsidiary": v["subsidiary"], "role": v["role"], "date": v["reviewed_on"],
                                                       "decision": v["decision"]} for v in reviews.get(r["id"], [])],
                               source=r["source"])
        return graph


def effective_status(stored: str, a: str, b: str, approvals: list[dict], reviews: list[dict]) -> str:
    if stored in ("approved", "rejected", "retired") or not reviews:
        return stored
    if any(v["decision"] == "reject" for v in reviews):
        return "rejected"
    sides = {a.split(":", 1)[0], b.split(":", 1)[0]}
    approved = {x["subsidiary"] for x in approvals} | {v["subsidiary"] for v in reviews if v["decision"] == "approve"}
    return "approved" if sides <= approved else stored
