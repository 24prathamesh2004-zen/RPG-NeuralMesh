"""Central mesh graph store: two SQLite tables (entities, relationships) plus link reviews.

Rows are updated in place by ID, so loading the same export twice changes nothing. A relationship is
retired, never deleted. Link reviews by each side's owner role live in their own table, and the
effective status of a proposed cross-subsidiary link is computed from them.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Any

import networkx as nx
from shared.registry import node_ids

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
DROP TABLE IF EXISTS import_sends;
CREATE TABLE IF NOT EXISTS import_pack_results(
  app_id TEXT NOT NULL, pack_id TEXT NOT NULL, at TEXT NOT NULL, result TEXT NOT NULL, code TEXT, reason TEXT,
  PRIMARY KEY (app_id, pack_id));
CREATE TABLE IF NOT EXISTS revision(id INTEGER PRIMARY KEY CHECK (id = 1), value INTEGER NOT NULL);
INSERT OR IGNORE INTO revision(id, value) VALUES (1, 0);
"""


class GraphStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with closing(self._connect()) as con, con:
            con.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.path, timeout=15)
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA busy_timeout=15000")
        return con

    def edge_sources(self, ids: set[str]) -> dict[str, str]:
        """The source that owns each of the given relationship IDs, for the ones already stored."""
        if not ids:
            return {}
        out: dict[str, str] = {}
        with closing(self._connect()) as con:
            items = sorted(ids)
            for i in range(0, len(items), 500):
                chunk = items[i:i + 500]
                marks = ",".join("?" * len(chunk))
                for r in con.execute(f"SELECT id, source FROM relationships WHERE id IN ({marks})", chunk):
                    out[r["id"]] = r["source"]
        return out

    def upsert_entities(self, entities: list[dict[str, Any]]) -> None:
        with self._lock, closing(self._connect()) as con, con:
            con.executemany(
                "INSERT INTO entities(id,type,label,owner,sensitivity,properties) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET type=excluded.type,label=excluded.label,owner=excluded.owner,"
                "sensitivity=excluded.sensitivity,properties=excluded.properties",
                [(e["id"], e["type"], e.get("label"), e.get("owner"), e.get("sensitivity"),
                  json.dumps(e.get("properties", {}), sort_keys=True)) for e in entities],
            )

    def insert_missing_entities(self, entities: list[dict[str, Any]]) -> None:
        """Add entities that are not stored yet and leave stored ones as they are."""
        with self._lock, closing(self._connect()) as con, con:
            con.executemany(
                "INSERT INTO entities(id,type,label,owner,sensitivity,properties) VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                [(e["id"], e["type"], e.get("label"), e.get("owner"), e.get("sensitivity"),
                  json.dumps(e.get("properties", {}), sort_keys=True)) for e in entities],
            )

    def upsert_relationships(self, rels: list[dict[str, Any]], source: str) -> None:
        with self._lock, closing(self._connect()) as con, con:
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
        with self._lock, closing(self._connect()) as con, con:
            rows = con.execute("SELECT id FROM relationships WHERE source=? AND status!='retired'", (source,)).fetchall()
            gone = [r["id"] for r in rows if r["id"] not in keep_ids]
            con.executemany("UPDATE relationships SET status='retired' WHERE id=?", [(g,) for g in gone])
            if gone:
                con.execute("UPDATE revision SET value = value + 1 WHERE id=1")
            return len(gone)

    def retire_entities(self, subsidiary: str, keep_ids: set[str], types: set[str] | None = None) -> int:
        """Entities of a subsidiary that its latest export no longer lists are marked retired, never deleted.
        Only the kinds the export carries (types) are judged: an asset or an inspection written by an application
        under the same subsidiary is not the node's to retire."""
        with self._lock, closing(self._connect()) as con, con:
            con.execute("BEGIN IMMEDIATE")  # read, change in Python, write back: no other writer in between
            rows = con.execute("SELECT id, type, properties FROM entities").fetchall()
            gone = []
            for r in rows:
                props = json.loads(r["properties"])
                if types is not None and r["type"] not in types:
                    continue
                if props.get("subsidiary") == subsidiary and r["id"] not in keep_ids and not props.get("retired"):
                    props["retired"] = True
                    gone.append((json.dumps(props, sort_keys=True), r["id"]))
            con.executemany("UPDATE entities SET properties=? WHERE id=?", gone)
            ids = [g[1] for g in gone]
            if ids:
                marks = ",".join("?" * len(ids))
                con.execute(f"UPDATE relationships SET status='retired' WHERE status!='retired' AND (from_id IN ({marks}) OR to_id IN ({marks}))",
                            ids + ids)
                con.execute("UPDATE revision SET value = value + 1 WHERE id=1")
            return len(gone)

    def record_send(self, app_id: str, at: str, packs: list[dict[str, Any]]) -> None:
        """The latest result of each pack an application sent through the import tool, for the Applications page: a
        pack keeps its result until the application sends it again."""
        with self._lock, closing(self._connect()) as con, con:
            con.executemany(
                "INSERT INTO import_pack_results(app_id, pack_id, at, result, code, reason) VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(app_id, pack_id) DO UPDATE SET at=excluded.at, result=excluded.result, code=excluded.code, "
                "reason=excluded.reason",
                [(app_id, p["pack_id"], at, p["result"], p.get("code"), p.get("reason")) for p in packs])

    def sends(self) -> dict[str, list[dict[str, Any]]]:
        with closing(self._connect()) as con:
            out: dict[str, list[dict[str, Any]]] = {}
            for r in con.execute("SELECT * FROM import_pack_results ORDER BY app_id, pack_id"):
                out.setdefault(r["app_id"], []).append({k: r[k] for k in ("pack_id", "at", "result", "code", "reason")})
            return out

    def revision(self) -> int:
        """Raised by every write. A reader that loaded an older revision rebuilds its in-memory copy."""
        with closing(self._connect()) as con, con:
            return int(con.execute("SELECT value FROM revision WHERE id=1").fetchone()[0])

    def bump_revision(self) -> int:
        with self._lock, closing(self._connect()) as con, con:
            con.execute("UPDATE revision SET value = value + 1 WHERE id=1")
            return int(con.execute("SELECT value FROM revision WHERE id=1").fetchone()[0])

    def entity_types(self) -> tuple[set[str], dict[str, str]]:
        """IDs and types of every stored entity, for the intake's reference and signature checks."""
        with closing(self._connect()) as con, con:
            rows = con.execute("SELECT id, type FROM entities").fetchall()
        return {r["id"] for r in rows}, {r["id"]: r["type"] for r in rows}

    def export_jsonl(self, path: Path, include_retired: bool = False) -> int:
        """Every entity and relationship as graph records, one per line, sorted, loadable by the JSON Lines adapter."""
        count = 0
        with self._connect() as con, path.open("w", encoding="utf-8") as fh:
            for e in con.execute("SELECT * FROM entities ORDER BY type, id"):
                props = json.loads(e["properties"])
                if props.get("retired") and not include_retired:
                    continue
                rec = {"kind": "node", "id": e["id"], "type": e["type"], "label": e["label"], "owner": e["owner"], "sensitivity": e["sensitivity"],
                       "aliases": props.pop("aliases", []), "description": props.pop("description", None),
                       "external_refs": props.pop("external_refs", []), "properties": props}
                fh.write(json.dumps({k: v for k, v in rec.items() if v not in (None, [], {})}, sort_keys=True) + "\n")
                count += 1
            for r in con.execute("SELECT * FROM relationships ORDER BY type, from_id, to_id, id"):
                if r["status"] == "retired" and not include_retired:
                    continue
                props = json.loads(r["properties"])
                rec = {"kind": "edge", "id": r["id"], "type": r["type"], "from": r["from_id"], "to": r["to_id"], "status": r["status"],
                       "confidence": props.pop("confidence", None), "properties": props, "provenance": json.loads(r["provenance"]),
                       "approvals": json.loads(r["approvals"]), "source": r["source"]}
                fh.write(json.dumps({k: v for k, v in rec.items() if v not in (None, [], {})}, sort_keys=True) + "\n")
                count += 1
        return count

    def exported_sources(self) -> set[str]:
        with closing(self._connect()) as con, con:
            return {r[0] for r in con.execute("SELECT DISTINCT source FROM relationships WHERE source LIKE 'node:%' AND status != 'retired'")}

    def retire_source(self, source: str) -> int:
        """A node that left the registry: retire all its relationships and the entities of its subsidiary, in one
        transaction, so a reader never sees the half-retired state."""
        with self._lock, closing(self._connect()) as con, con:
            con.execute("BEGIN IMMEDIATE")
            con.execute("UPDATE relationships SET status='retired' WHERE source=? AND status!='retired'", (source,))
            if source.startswith("node:"):
                node = source.split(":", 1)[1]
                rows = con.execute("SELECT id, properties FROM entities").fetchall()
                gone = []
                for r in rows:
                    props = json.loads(r["properties"])
                    if (props.get("subsidiary") == node or r["id"] == f"org:{node}") and not props.get("retired"):
                        props["retired"] = True
                        gone.append((json.dumps(props, sort_keys=True), r["id"]))
                con.executemany("UPDATE entities SET properties=? WHERE id=?", gone)
                ids = [g[1] for g in gone]
                if ids:
                    marks = ",".join("?" * len(ids))
                    con.execute(f"UPDATE relationships SET status='retired' WHERE status!='retired' AND (from_id IN ({marks}) OR to_id IN ({marks}))", ids + ids)
            con.execute("UPDATE revision SET value = value + 1 WHERE id=1")
            return con.execute("SELECT COUNT(*) FROM relationships WHERE source=? AND status='retired'", (source,)).fetchone()[0]

    def review_link(self, rel_id: str, subsidiary: str, role: str, decision: str, reviewer: str) -> None:
        self.review_links([(rel_id, subsidiary, role)], decision, reviewer)

    def review_links(self, items: list[tuple[str, str, str]], decision: str, reviewer: str) -> int:
        """One review decision for several (link id, side, role) items, checked against the sides of each link and written
        in one transaction. A side is a company with a Mesh Node, or the group for an end that belongs to no company."""
        if decision not in ("approve", "reject"):
            raise ValueError("decision must be approve or reject")
        if not items:
            return 0
        with self._lock, closing(self._connect()) as con, con:
            graph, _ = self.to_networkx()
            rows = []
            for rel_id, side, role in items:
                row = con.execute("SELECT from_id, to_id FROM relationships WHERE id=?", (rel_id,)).fetchone()
                if row is None:
                    raise KeyError(rel_id)
                if side not in review_sides(graph, row["from_id"], row["to_id"]):
                    raise ValueError(f"{side} is not a side of {rel_id}")
                rows.append((rel_id, side, role, decision, date.today().isoformat(), reviewer))
            con.executemany(
                "INSERT INTO link_reviews VALUES (?,?,?,?,?,?) ON CONFLICT(rel_id, subsidiary) DO UPDATE SET "
                "role=excluded.role, decision=excluded.decision, reviewed_on=excluded.reviewed_on, reviewer=excluded.reviewer",
                rows,
            )
            con.execute("UPDATE revision SET value = value + 1 WHERE id=1")
            return len(rows)

    def reviews(self) -> dict[str, list[dict[str, Any]]]:
        with closing(self._connect()) as con, con:
            out: dict[str, list[dict[str, Any]]] = {}
            for r in con.execute("SELECT * FROM link_reviews"):
                out.setdefault(r["rel_id"], []).append(dict(r))
            return out

    def counts(self) -> dict[str, int]:
        with closing(self._connect()) as con, con:
            return {
                "entities": con.execute("SELECT COUNT(*) FROM entities").fetchone()[0],
                "relationships": con.execute("SELECT COUNT(*) FROM relationships").fetchone()[0],
            }

    def to_networkx(self) -> tuple[nx.MultiDiGraph, int]:
        """The graph and the revision it was read at, both from one read transaction."""
        graph = nx.MultiDiGraph()
        with closing(self._connect()) as con:
            con.execute("BEGIN")
            revision = int(con.execute("SELECT value FROM revision WHERE id=1").fetchone()[0])
            reviews: dict[str, list[dict[str, Any]]] = {}
            for r in con.execute("SELECT * FROM link_reviews"):
                reviews.setdefault(r["rel_id"], []).append(dict(r))
            entities = con.execute("SELECT * FROM entities").fetchall()
            relationships = con.execute("SELECT * FROM relationships").fetchall()
            con.execute("COMMIT")
        props = {e["id"]: json.loads(e["properties"]) for e in entities}
        replaced_by = _replacements(entities, props)
        graph.graph["replaced_by"] = replaced_by
        for e in entities:
            if e["id"] not in replaced_by:
                graph.add_node(e["id"], **{**props[e["id"]], "type": e["type"], "label": e["label"], "owner": e["owner"], "sensitivity": e["sensitivity"]})
        # The names of a replaced entry stay names of the entry that took its place, so free text still finds it.
        labels = {e["id"]: e["label"] for e in entities}
        for old, new in sorted(replaced_by.items()):
            if new in graph:
                names = list(graph.nodes[new].get("aliases") or [])
                seen = {n.lower() for n in [graph.nodes[new].get("label") or "", *names]}
                for name in [labels.get(old) or "", *(props.get(old, {}).get("aliases") or [])]:
                    if name and name.lower() not in seen:
                        names.append(name)
                        seen.add(name.lower())
                graph.nodes[new]["aliases"] = names
        # Links as written first, then the links moved onto a replacing entity: a moved link that repeats one already
        # there (a role that required both the old and the new skill) is left out, and so is a link between two entries
        # that are now one.
        moved = []
        for r in relationships:
            a, b = replaced_by.get(r["from_id"], r["from_id"]), replaced_by.get(r["to_id"], r["to_id"])
            moved.append((r, a, b, (a, b) != (r["from_id"], r["to_id"])))
        for r, a, b, redirected in sorted(moved, key=lambda item: item[3]):  # stable: the written order is kept
            if a == b and r["from_id"] != r["to_id"]:
                continue
            if True:
                approvals = json.loads(r["approvals"])
                sides = review_sides(graph, a, b)
                status = effective_status(r["status"], a, b, approvals, reviews.get(r["id"], []), sides)
                if redirected and status != "retired":
                    same = [(k, d) for k, d in (graph.get_edge_data(a, b) or {}).items()
                            if d.get("type") == r["type"] and d.get("status") != "retired"]
                    # an approved link that moved here wins over a link still proposed, never over a person's
                    # rejection: a rejected link keeps its decision, and the moved one is left out
                    if same and status == "approved" and all(d.get("status") == "proposed" for _, d in same):
                        for k, _ in same:
                            graph.remove_edge(a, b, key=k)
                    elif same:
                        continue
                for end in (a, b):
                    if end not in graph:
                        graph.add_node(end, type="Unknown", label=end)
                graph.add_edge(a, b, key=r["id"], id=r["id"], type=r["type"], status=status,
                               properties=json.loads(r["properties"]), provenance=json.loads(r["provenance"]),
                               approvals=approvals + [{"subsidiary": v["subsidiary"], "role": v["role"], "date": v["reviewed_on"],
                                                       "decision": v["decision"]} for v in reviews.get(r["id"], [])],
                               source=r["source"], proposed=r["status"] == "proposed")
        return graph, revision


def _replacements(entities: list, props: dict[str, dict]) -> dict[str, str]:
    """Joined entries: each id an entity lists under "replaces", mapped to the entity that finally takes its place.
    A replacing entity that is itself replaced passes its claims on (a chain of joins resolves to its end), and of two
    claims on one id the smaller id wins, so the graph is the same on every read."""
    claims: dict[str, set[str]] = {}
    for e in entities:
        if not props[e["id"]].get("retired"):
            for old in props[e["id"]].get("replaces") or []:
                if isinstance(old, str) and old != e["id"]:
                    claims.setdefault(old, set()).add(e["id"])
    direct = {old: min(by) for old, by in claims.items()}
    out: dict[str, str] = {}
    for old in direct:
        end, seen = direct[old], {old}
        while end in direct and end not in seen:  # a cycle stops where it would repeat
            seen.add(end)
            end = direct[end]
        if end != old:
            out[old] = end
    return out


def company_of(graph: nx.MultiDiGraph, entity_id: str) -> str:
    """The company an entity belongs to: its subsidiary property, the org ID itself, or the ID namespace."""
    data = graph.nodes.get(entity_id, {}) if entity_id in graph else {}
    if data.get("subsidiary"):
        return str(data["subsidiary"])
    if entity_id.startswith("org:"):
        return entity_id.split(":", 1)[1]
    return entity_id.split(":", 1)[0]


GROUP_SIDE = "group"  # the side of an end that belongs to no company with a Mesh Node, reviewed by a mesh admin as curator


def review_sides(graph: nx.MultiDiGraph, a: str, b: str) -> set[str]:
    """The sides that approve a link: the company of each end that has a Mesh Node, or the group for an end of shared
    or application vocabulary (an inspection condition, a cover type), which the mesh curator approves."""
    nodes = set(node_ids())
    return {company if company in nodes else GROUP_SIDE for company in (company_of(graph, a), company_of(graph, b))}


def effective_status(stored: str, a: str, b: str, approvals: list[dict], reviews: list[dict], sides: set[str] | None = None) -> str:
    if stored in ("approved", "rejected", "retired") or not reviews:
        return stored
    if any(v.get("decision") == "reject" for v in reviews):
        return "rejected"
    sides = sides or {a.split(":", 1)[0], b.split(":", 1)[0]}
    approved = {x.get("subsidiary") for x in approvals} | {v.get("subsidiary") for v in reviews if v.get("decision") == "approve"}
    return "approved" if sides <= approved else stored
