"""Ingested context graphs: a graph a person writes as JSON, with the nodes and the edges they choose, kept as written.

The person owns the data. The JSON names the graph, the company that owns it, its nodes (type and name) and its edges
(type, source and target), and may give the sensitivity, the sharing rule, whether the data is invented, a description,
other names and properties. Code checks the JSON and keeps it, and never writes content the person did not write:

- Made by code and reported in "filled": an id for a node or an edge that has none, a node name taken from its id, an
  edge end given by name or under "from" and "to", fields of a node or an edge beyond the known ones kept as its
  properties, the entries of "documents" (written by Upload input) kept with the nodes of the same ids. Names, types
  and other names are kept on one line, and a field with the value null is left out and counted under "ignored".
- Set to the safe value and reported in "defaults" when missing: sensitivity Restricted, sharing "company" (only the
  owning company and mesh admins see the graph), synthetic false (the data is treated as real, so no cloud model reads
  it). Only a mesh admin may mark a graph as invented with synthetic true.
- Refused with the place named in "problems", and nothing kept: a missing graph name, company, node type or edge type,
  an edge end that is no node of the graph, a "documents" entry with no node of its id, an unknown company or one the
  person may not write for, a sharing rule that opens a Confidential or Restricted graph to the group, a graph of the
  shared inputs node Others that does not say "sharing": "group", a value nested deeper than a list of plain values,
  and a text over its length limit.

Each graph is one JSON file in folder() under an id "cg-" with eight hex characters. It keeps its own node and edge
types, because the person decides them, so it is not loaded into the central mesh graph, whose graph rules hold the
types of the mesh only. api/routers/context_graphs.py serves it: the graph as JSON, its view for the page, and a query by
question, node, nodes or edges. A written answer to a question comes from the answer model only when the model policy
allows that model for the graph's sensitivity and synthetic flag, so a real graph gets its edges without a cloud model
reading them. A JSON whose graph_id names a graph made by Upload input (an id that is not "cg-") corrects that graph: it
is kept as an ingested graph that records the uploaded graph under "corrects", a later JSON for the same uploaded graph
replaces it, and only a mesh admin loads one. The uploaded graph's inputs stay in the mesh. A correction takes from the
uploaded graph what the JSON leaves out and the graph already says, reported in "filled": synthetic true when every input
is marked invented, and sharing "group" with sensitivity Internal for a graph of the shared inputs node Others, whose
inputs every company already reads. ingest_log.jsonl in the folder keeps one line for each create, replace and drop, with ids and counts and
never the content. A dropped graph's file is deleted.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import threading
import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from services.mesh_graph import _phrase_in, norm_tokens
from shared.registry import company_nodes, is_shared, node as registered_node, node_ids

APP_ROOT = Path(__file__).resolve().parents[1]
PROMPT_FILE = APP_ROOT / "config" / "prompts" / "graph_answer_v1.txt"
PROMPT_VERSION = "graph_answer_v1"
LOG_FILE = "ingest_log.jsonl"
GRAPH_ID = re.compile(r"cg-[0-9a-f]{8}")
SENSITIVITIES = ("Public", "Internal", "Confidential", "Restricted")
OPEN_TO_GROUP = frozenset({"Public", "Internal"})  # the sensitivities a graph shared with the whole group may have
SHARINGS = ("company", "group")
NAME_MIN, NAME_MAX = 3, 80
TEXT_MAX = 200  # an id, a node name, another name
TYPE_MAX = 60
KEY_MAX = 100  # the name of a property
VALUE_MAX = 2_000  # one property value
LIST_MAX = 100  # values in one property list
DESCRIPTION_MAX = 1_000
MAX_NODES = 5_000
MAX_EDGES = 20_000
MAX_PROPERTIES = 50
MAX_ALIASES = 50
QUESTION_MAX = 2_000
FOUND_MAX = 200  # nodes in one answer to a nodes or node query
EDGES_MAX = 500  # edges in one answer to an edges or node query
CONTEXT_NODES = 30  # nodes given to the answer model
CONTEXT_EDGES = 40  # edges given to the answer model
PROMPT_PROPERTIES = 8
PROMPT_VALUE_CHARS = 200
NO_ANSWER = "The graph does not answer this question."
NODE_KEYS = frozenset({"id", "type", "name", "label", "aliases", "properties"})
EDGE_KEYS = frozenset({"id", "type", "source", "target", "from", "to", "properties"})
TOP_KEYS = frozenset({"graph", "graph_id", "company", "companies", "description", "sensitivity", "sharing", "synthetic",
                      "nodes", "edges", "relationships", "documents"})
EMAIL = re.compile(r"[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}")  # bounded, so a long text without an @ costs little
CITATION = re.compile(r"\[\s*([NE]\d+(?:\s*,\s*[NE]\d+)*)\s*\]")
STOPWORDS = frozenset("a an the of to for in on at by with and or is are was were be been do doe does did which what who whom whose "
                      "how many much when where why this that these those it its their them they there from into about any all "
                      "list show give tell me us our we you your can could should would will has have had not no".split())
_lock = threading.RLock()
_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}


class IngestRefused(ValueError):
    """The JSON was not kept. problems name each field to fix, and the rest of the report says what would have been
    filled, set by default and not read."""

    def __init__(self, report: dict[str, list[str]]) -> None:
        super().__init__("; ".join(report["problems"][:3]))
        self.report = report


class NodeNotFound(KeyError):
    def __init__(self, ref: str, close: list[str]) -> None:
        super().__init__(ref)
        self.ref, self.close = ref, close


class NodeAmbiguous(ValueError):
    def __init__(self, ref: str, candidates: list[dict[str, Any]]) -> None:
        super().__init__(ref)
        self.ref, self.candidates = ref, candidates


def folder() -> Path:
    return Path(os.getenv("NEURALMESH_CONTEXT_GRAPHS", str(APP_ROOT / ".neuralmesh" / "context_graphs")))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _text(value: Any) -> str:
    """A string or number as one line of text. Anything else (a list, an object, true or false) is empty."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return " ".join(str(value).split())


def company_name(node_id: str | None) -> str:
    try:
        return registered_node(str(node_id)).display
    except KeyError:
        return str(node_id or "")


def company_of(value: Any) -> str | None:
    """The node id of a company written by its id or its name, in any case."""
    text = _text(value).casefold()
    for node_id in node_ids():
        if text in (node_id.casefold(), registered_node(node_id).display.casefold()):
            return node_id
    return None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "item"


def _value_problem(value: Any) -> str | None:
    if value is None or isinstance(value, (bool, int, float)):
        return None
    if isinstance(value, str):
        return f"has more than {VALUE_MAX:,} characters" if len(value) > VALUE_MAX else None
    if isinstance(value, list):
        if len(value) > LIST_MAX:
            return f"is a list of more than {LIST_MAX} values"
        for item in value:
            if isinstance(item, (list, dict)):
                return "holds a list or an object inside a list. A property holds plain values: text, numbers, true or false"
            problem = _value_problem(item)
            if problem:
                return problem
        return None
    return "is an object. A property holds a plain value or a list of plain values"


def _sha(content: dict[str, Any]) -> str:
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


# ── reading the JSON a person wrote ─────────────────────────────────────────
def parse(data: Any) -> tuple[dict[str, Any], dict[str, list[str]]]:
    """(graph, report). report holds "problems" (nothing may be kept while there is one), "filled", "defaults",
    "ignored" and "warnings". The graph is complete only when problems is empty."""
    report: dict[str, list[str]] = {"problems": [], "filled": [], "defaults": [], "ignored": [], "warnings": []}
    problems, filled, defaults = report["problems"], report["filled"], report["defaults"]
    if not isinstance(data, dict):
        problems.append('The JSON is one object in { } with "graph", "company", "nodes" and "edges".')
        return {}, report
    report["ignored"] += [f"{key} (not a field of the format)" for key in sorted(set(data) - TOP_KEYS)]

    name = _text(data.get("graph"))
    if not name:
        problems.append(f'graph: the name of the graph is missing. Write "graph": "<a name of {NAME_MIN} to {NAME_MAX} characters>".')
    elif not NAME_MIN <= len(name) <= NAME_MAX:
        problems.append(f"graph: the name has {len(name)} characters. A name has {NAME_MIN} to {NAME_MAX}.")

    raw_company = data.get("company")
    many = False  # "companies" names more than one company, which is its own problem
    if raw_company in (None, "") and isinstance(data.get("companies"), list):
        listed = [c for c in data["companies"] if c not in (None, "")]
        if len(listed) == 1:
            raw_company = listed[0]
            filled.append('company taken from "companies"')
        elif len(listed) > 1:
            problems.append(f'company: a context graph belongs to one company, and "companies" names {len(listed)}. '
                            'Write "company" with the one that owns the data.')
            many = True
    company = None
    if many:
        pass
    elif raw_company is None or raw_company == "":
        problems.append('company: missing. Write "company" with the company that owns the data, for example "CEAT".')
    else:
        company = company_of(raw_company)
        if company is None:
            names = ", ".join(registered_node(n).display for n in node_ids())
            problems.append(f'company: "{_text(raw_company)[:60]}" is not a company of the mesh. Use one of: {names}.')

    raw = data.get("sensitivity")
    sensitivity_given = raw not in (None, "")
    sensitivity = "Restricted"
    if not sensitivity_given:
        defaults.append("sensitivity: Restricted, because none was given")
    else:
        match = next((s for s in SENSITIVITIES if s.casefold() == _text(raw).casefold()), None)
        if match is None:
            problems.append(f'sensitivity: "{_text(raw)[:40]}" is not one of {", ".join(SENSITIVITIES)}.')
        else:
            sensitivity = match

    shared_node = company is not None and is_shared(company)
    raw = data.get("sharing")
    sharing = "company"
    if shared_node and _text(raw).casefold() != "group":
        # the shared inputs node belongs to no company: its graph is read by every company, which the JSON must say itself
        problems.append('sharing: a graph of the shared inputs node Others is read by every company. Write "sharing": "group" '
                        'and "sensitivity": "Internal" or "Public", or name the company that owns the data.')
        sharing = "group"
    elif raw in (None, ""):
        defaults.append(f"sharing: company, so only {company_name(company) if company else 'the owning company'} and mesh admins see the graph, because none was given")
    elif _text(raw).casefold() not in SHARINGS:
        problems.append(f'sharing: "{_text(raw)[:40]}" is not "company" (only the owning company sees the graph) or "group" (every company sees it).')
    else:
        sharing = _text(raw).casefold()
    if sharing == "group" and sensitivity not in OPEN_TO_GROUP and not any(p.startswith(("sensitivity:", "sharing:")) for p in problems):
        why = f"{sensitivity}, because none was given" if not sensitivity_given else sensitivity
        keep = "" if shared_node else ', or keep the graph to its company with "sharing": "company"'
        problems.append(f'sharing: "group" opens the graph to every company, which a graph of sensitivity {why} may not be. '
                        f'Write "sensitivity": "Internal" or "Public"{keep}.')

    raw = data.get("synthetic")
    synthetic = False
    if raw is None:
        defaults.append("synthetic: false, so the data is treated as real and no cloud model reads it")
    elif isinstance(raw, bool):
        synthetic = raw
    else:
        problems.append("synthetic: true or false, written without quotes.")

    description = None
    if data.get("description") not in (None, ""):
        if not isinstance(data["description"], str):
            problems.append("description: a text in quotes.")
        elif len(data["description"]) > DESCRIPTION_MAX:
            problems.append(f"description: more than {DESCRIPTION_MAX:,} characters.")
        else:
            description = " ".join(data["description"].split())

    nodes = _nodes(data.get("nodes"), report)
    _documents(data.get("documents"), nodes, report)
    for node in nodes:
        _check_properties(node["properties"], node["_where"], report)
    edges = _edges(data, nodes, report)
    if not problems:  # a refused JSON is not scanned: its texts may be over their limits
        _warn_emails(nodes, edges, report)
    graph = {"name": name, "company": company, "description": description, "sensitivity": sensitivity, "sharing": sharing,
             "synthetic": synthetic,
             "nodes": [{k: v for k, v in n.items() if not k.startswith("_")} for n in nodes],
             "edges": [{k: v for k, v in e.items() if not k.startswith("_")} for e in edges]}
    return graph, report


def _extra(raw: dict[str, Any], known: frozenset[str], props: dict[str, Any], nulls: list[int]) -> int:
    """Fields beyond the known ones are kept as properties, except a null one (the standard JSON structure writes null
    for a value the graph does not have), which is counted in nulls. A property written under "properties" stays as written."""
    count = 0
    for key in sorted(set(raw) - known):
        if raw[key] is None:
            nulls[0] += 1
        elif key not in props:
            props[key] = raw[key]
            count += 1
    return count


def _nodes(raw_nodes: Any, report: dict[str, list[str]]) -> list[dict[str, Any]]:
    problems = report["problems"]
    if not isinstance(raw_nodes, list) or not raw_nodes:
        problems.append('nodes: missing or empty. Write "nodes": [ { "type": "...", "name": "..." } ].')
        return []
    if len(raw_nodes) > MAX_NODES:
        problems.append(f"nodes: {len(raw_nodes):,} nodes. A graph has at most {MAX_NODES:,}.")
        return []
    nodes: list[dict[str, Any]] = []
    names_from_ids = extra = 0
    nulls = [0]
    for i, raw in enumerate(raw_nodes):
        place = f"nodes[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{place}: a node is an object in {{ }}.")
            continue
        node_id = _text(raw.get("id"))
        ntype = _text(raw.get("type"))
        name = _text(raw.get("name")) or _text(raw.get("label"))
        where = f'{place} ("{name or node_id}")' if (name or node_id) else place
        if not ntype:
            problems.append(f'{where}: type is missing. Write what the node is, for example "Supplier".')
        elif len(ntype) > TYPE_MAX:
            problems.append(f"{where}: the type has more than {TYPE_MAX} characters.")
        if not name and node_id:
            name = node_id
            names_from_ids += 1
        if not name:
            problems.append(f"{where}: name is missing.")
        elif len(name) > TEXT_MAX:
            problems.append(f"{where}: the name has more than {TEXT_MAX} characters.")
        if len(node_id) > TEXT_MAX:
            problems.append(f"{where}: the id has more than {TEXT_MAX} characters.")
        aliases = raw.get("aliases") or []
        if not isinstance(aliases, list) or any(not isinstance(a, str) for a in aliases):
            problems.append(f"{where}: aliases is a list of names in [ ].")
            aliases = []
        elif len(aliases) > MAX_ALIASES:
            problems.append(f"{where}: more than {MAX_ALIASES} other names.")
        elif any(len(a) > TEXT_MAX for a in aliases):
            problems.append(f"{where}: another name has more than {TEXT_MAX} characters.")
        aliases = list(dict.fromkeys(" ".join(a.split()) for a in aliases if a.strip()))
        props = raw.get("properties") if raw.get("properties") is not None else {}
        if not isinstance(props, dict):
            problems.append(f"{where}: properties is an object in {{ }}.")
            props = {}
        props = dict(props)
        extra += _extra(raw, NODE_KEYS, props, nulls)
        nodes.append({"id": node_id, "type": ntype, "name": name, "aliases": aliases, "properties": props, "_where": where})
    seen: dict[str, str] = {}
    for node in nodes:
        if node["id"]:
            if node["id"] in seen:
                problems.append(f'{node["_where"]}: the id "{node["id"]}" is given twice (also {seen[node["id"]]}).')
            seen.setdefault(node["id"], node["_where"])
    made = 0
    for node in nodes:
        if not node["id"] and node["name"] and node["type"]:
            base = f'{_slug(node["type"])}-{_slug(node["name"])}'
            candidate, n = base, 2
            while candidate in seen:
                candidate, n = f"{base}-{n}", n + 1
            node["id"] = candidate
            seen[candidate] = node["_where"]
            made += 1
    if made:
        report["filled"].append(f"{made} node {'id' if made == 1 else 'ids'} made from the type and the name")
    if names_from_ids:
        report["filled"].append(f"{names_from_ids} node {'name' if names_from_ids == 1 else 'names'} taken from the id")
    if extra:
        report["filled"].append(f"{extra} extra node {'field' if extra == 1 else 'fields'} kept as properties")
    if nulls[0]:
        report["ignored"].append(f"{nulls[0]} node {'field' if nulls[0] == 1 else 'fields'} with the value null")
    return nodes


def _documents(raw_docs: Any, nodes: list[dict[str, Any]], report: dict[str, list[str]]) -> None:
    """The "documents" list that Upload input writes: each entry's fields are kept with the node of the same id, which
    that structure always writes. An entry with no node of its id is refused: code makes no node the person did not write."""
    if raw_docs is None:
        return
    if not isinstance(raw_docs, list):
        report["problems"].append("documents: a list in [ ].")
        return
    if len(raw_docs) > MAX_NODES:
        report["problems"].append(f"documents: {len(raw_docs):,} entries. A graph has at most {MAX_NODES:,} nodes.")
        return
    by_id = {n["id"]: n for n in nodes if n["id"]}
    merged = 0
    for j, raw in enumerate(raw_docs):
        doc_id = _text(raw.get("id")) if isinstance(raw, dict) else ""
        if not doc_id:
            report["problems"].append(f'documents[{j}]: a document entry is an object with an "id".')
            continue
        node = by_id.get(doc_id)
        if node is None:
            report["problems"].append(f'documents[{j}]: no node has the id "{doc_id[:80]}". A document entry adds its fields to the node of the same id.')
            continue
        for key, value in raw.items():
            if key not in ("id", "title"):
                node["properties"].setdefault(key, value)
        merged += 1
    if merged:
        report["filled"].append(f"{merged} document {'entry' if merged == 1 else 'entries'} kept with {'its node' if merged == 1 else 'their nodes'} as properties")


def _check_properties(props: dict[str, Any], where: str, report: dict[str, list[str]]) -> None:
    if len(props) > MAX_PROPERTIES:
        report["problems"].append(f"{where}: more than {MAX_PROPERTIES} properties.")
    for key, value in props.items():
        if not key.strip() or len(key) > KEY_MAX:
            report["problems"].append(f"{where}: a property name is empty or has more than {KEY_MAX} characters.")
            continue
        problem = _value_problem(value)
        if problem:
            report["problems"].append(f"{where}: property {key} {problem}.")


def _edges(data: dict[str, Any], nodes: list[dict[str, Any]], report: dict[str, list[str]]) -> list[dict[str, Any]]:
    problems = report["problems"]
    if "edges" in data and "relationships" in data:
        problems.append('edges: written twice, as "edges" and as "relationships". Write them once, under "edges".')
        return []
    raw_edges = data.get("edges", data.get("relationships"))
    if raw_edges is None:
        report["warnings"].append("The graph has no edges, only nodes.")
        return []
    if not isinstance(raw_edges, list):
        problems.append('edges: a list in [ ], each with "type", "source" and "target".')
        return []
    if len(raw_edges) > MAX_EDGES:
        problems.append(f"edges: {len(raw_edges):,} edges. A graph has at most {MAX_EDGES:,}.")
        return []
    by_id = {n["id"]: n for n in nodes if n["id"]}
    by_name: dict[str, list[str]] = {}
    for n in nodes:
        for name in [n["name"], *n["aliases"]]:
            if name and n["id"] and n["id"] not in by_name.get(name.casefold(), []):
                by_name.setdefault(name.casefold(), []).append(n["id"])
    by_name_count = 0

    def end(raw: dict[str, Any], key: str, other: str, where: str) -> str | None:
        nonlocal by_name_count
        used = key if raw.get(key) not in (None, "") else other if raw.get(other) not in (None, "") else None
        if used is None:
            problems.append(f'{where}: {key} is missing. Write the id of the node the edge {"starts" if key == "source" else "ends"} at.')
            return None
        ref = _text(raw[used])
        if ref in by_id:
            if used != key:
                by_name_count += 1
            return ref
        ids = by_name.get(ref.casefold(), [])
        if len(ids) == 1:
            by_name_count += 1
            return ids[0]
        if len(ids) > 1:
            problems.append(f'{where}: {used} "{ref}" names {len(ids)} nodes ({", ".join(ids[:5])}). Write the id of one.')
        else:
            problems.append(f'{where}: {used} "{ref[:80]}" is not a node of this graph.')
        return None

    edges: list[dict[str, Any]] = []
    extra = 0
    nulls = [0]
    for i, raw in enumerate(raw_edges):
        place = f"edges[{i}]"
        if not isinstance(raw, dict):
            problems.append(f"{place}: an edge is an object in {{ }}.")
            continue
        etype = _text(raw.get("type"))
        edge_id = _text(raw.get("id"))
        where = f'{place} ("{edge_id}")' if edge_id else place
        if not etype:
            problems.append(f'{where}: type is missing. Write the kind of link, for example "SUPPLIES".')
        elif len(etype) > TYPE_MAX:
            problems.append(f"{where}: the type has more than {TYPE_MAX} characters.")
        if len(edge_id) > TEXT_MAX:
            problems.append(f"{where}: the id has more than {TEXT_MAX} characters.")
        source = end(raw, "source", "from", where)
        target = end(raw, "target", "to", where)
        props = raw.get("properties") if raw.get("properties") is not None else {}
        if not isinstance(props, dict):
            problems.append(f"{where}: properties is an object in {{ }}.")
            props = {}
        props = dict(props)
        # "from" and "to" beside "source" and "target" are the names of the ends, as the standard JSON structure writes them
        extra += _extra(raw, EDGE_KEYS, props, nulls)
        _check_properties(props, where, report)
        edges.append({"id": edge_id, "type": etype, "source": source or "", "target": target or "", "properties": props, "_where": where})
    seen: dict[str, str] = {}
    for edge in edges:
        if edge["id"]:
            if edge["id"] in seen:
                problems.append(f'{edge["_where"]}: the id "{edge["id"]}" is given twice (also {seen[edge["id"]]}).')
            seen.setdefault(edge["id"], edge["_where"])
    made = 0
    counts: Counter[str] = Counter()
    for edge in edges:
        if not edge["id"] and edge["type"]:
            base = _slug(edge["type"])
            counts[base] += 1
            candidate = f"{base}-{counts[base]}"
            while candidate in seen:
                counts[base] += 1
                candidate = f"{base}-{counts[base]}"
            edge["id"] = candidate
            seen[candidate] = edge["_where"]
            made += 1
    if made:
        report["filled"].append(f"{made} edge {'id' if made == 1 else 'ids'} made from the type")
    if by_name_count:
        report["filled"].append(f"{by_name_count} edge {'end' if by_name_count == 1 else 'ends'} given by name or under \"from\" and \"to\" matched to node ids")
    if extra:
        report["filled"].append(f"{extra} extra edge {'field' if extra == 1 else 'fields'} kept as properties")
    if nulls[0]:
        report["ignored"].append(f"{nulls[0]} edge {'field' if nulls[0] == 1 else 'fields'} with the value null")
    return edges


def _warn_emails(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], report: dict[str, list[str]]) -> None:
    places = []
    for item in [*nodes, *edges]:
        texts = [item.get("name") or "", *item.get("aliases", [])]
        for key, value in item["properties"].items():
            texts += [str(v) for v in (value if isinstance(value, list) else [value]) if isinstance(v, str)]
        if any(len(t) <= VALUE_MAX and EMAIL.search(t) for t in texts):
            places.append(item["_where"])
    if places:
        shown = ", ".join(places[:5]) + (f" and {len(places) - 5} more" if len(places) > 5 else "")
        report["warnings"].append(f"An email address is written in {shown}. It is kept as written, and everyone the graph is shared with can read it.")


# ── keeping, listing and dropping ───────────────────────────────────────────
def _path(graph_id: str) -> Path:
    return folder() / f"{graph_id}.json"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    hit = _cache.get(str(path))
    if hit and hit[0] == key:
        return hit[1]
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    _cache[str(path)] = (key, record)
    return record


def records() -> list[dict[str, Any]]:
    base = folder()
    if not base.is_dir():
        return []
    return [r for p in sorted(base.glob("cg-*.json")) if GRAPH_ID.fullmatch(p.stem) and (r := _read(p))]


def get(graph_id: str) -> dict[str, Any] | None:
    return _read(_path(graph_id)) if GRAPH_ID.fullmatch(graph_id or "") else None


def may_see(record: dict[str, Any], company: str, roles: list[str]) -> bool:
    return "mesh_admin" in roles or record["company"] == company or record["sharing"] == "group"


def may_change(record: dict[str, Any], company: str, roles: list[str]) -> bool:
    return "mesh_admin" in roles or record["company"] == company


def endpoints(graph_id: str) -> dict[str, str]:
    base = f"/api/v1/context-graphs/{graph_id}"
    return {"graph": base, "view": f"{base}/view", "query": f"{base}/query"}


def summary(record: dict[str, Any], company: str, roles: list[str]) -> dict[str, Any]:
    return {"id": record["id"], "name": record["name"], "company": record["company"], "company_name": company_name(record["company"]),
            "description": record.get("description"), "sensitivity": record["sensitivity"], "sharing": record["sharing"],
            "synthetic": record["synthetic"], "nodes": len(record["nodes"]), "edges": len(record["edges"]),
            "node_types": dict(Counter(n["type"] for n in record["nodes"]).most_common()),
            "edge_types": dict(Counter(e["type"] for e in record["edges"]).most_common()),
            "created": record["created"], "updated": record.get("updated"), "can_change": may_change(record, company, roles),
            "corrects": record.get("corrects"),
            "endpoints": endpoints(record["id"])}


def visible(company: str, roles: list[str]) -> list[dict[str, Any]]:
    """The summaries of the graphs the caller may see, the latest first."""
    shown = [summary(r, company, roles) for r in records() if may_see(r, company, roles)]
    return sorted(shown, key=lambda s: (s["updated"] or s["created"])["at"], reverse=True)


def _who(user: dict[str, Any]) -> dict[str, str]:
    company = str(user.get("company") or "")
    return {"at": _now(), "by_role": "Mesh admin" if "mesh_admin" in (user.get("roles") or []) else "User",
            "by_company": company, "by_company_name": company_name(company)}


def _log(line: dict[str, Any]) -> None:
    base = folder()
    base.mkdir(parents=True, exist_ok=True)
    with (base / LOG_FILE).open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, sort_keys=True) + "\n")


def _write_atomic(path: Path, record: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def _store_problems(graph: dict[str, Any], graph_id: str, user: dict[str, Any],
                    corrects: dict[str, Any] | None = None) -> tuple[list[str], dict[str, Any] | None]:
    """The checks that need the graphs already kept: the graph to replace, the company the person may write for and a
    name already taken. ``corrects`` is the uploaded graph the graph_id names, when it names one."""
    company, roles = str(user.get("company") or ""), list(user.get("roles") or [])
    problems: list[str] = []
    existing = None
    if corrects:
        if "mesh_admin" not in roles and all(n == company or is_shared(n) for n in corrects.get("nodes") or ["?"]):
            problems.append(f'graph_id: {graph_id[:40]} is a graph made by Upload input, and only a mesh admin corrects it. '
                            "Leave graph_id out to create a new graph.")
        elif "mesh_admin" not in roles:  # a graph with inputs of another company: answered as a graph that does not exist
            problems.append(f"graph_id: there is no context graph {graph_id[:40]} to replace. Leave graph_id out to create a new graph.")
        else:
            existing = next((r for r in records() if r.get("corrects") == corrects["id"]), None)
            if existing and graph.get("company") and graph["company"] != existing["company"]:
                problems.append(f"company: the correction of {graph_id} belongs to {company_name(existing['company'])}, and a graph keeps its company.")
    elif graph_id:
        existing = get(graph_id)
        if existing is None or not may_see(existing, company, roles):
            problems.append(f"graph_id: there is no context graph {graph_id[:40]} to replace. Leave graph_id out to create a new graph.")
            existing = None
        elif not may_change(existing, company, roles):
            problems.append(f"graph_id: only {company_name(existing['company'])} and mesh admins may replace this graph.")
            existing = None
        elif graph.get("company") and graph["company"] != existing["company"]:
            problems.append(f"company: graph {graph_id} belongs to {company_name(existing['company'])}, and a graph keeps its company. "
                            f"Leave graph_id out to create a new graph for {company_name(graph['company'])}.")
    if graph.get("synthetic") and "mesh_admin" not in roles:
        problems.append('synthetic: only a mesh admin marks a graph as invented. Leave "synthetic" out, or write false, '
                        "and the graph is treated as real data.")
    writes_for_company = bool(graph.get("company")) and ("mesh_admin" in roles or graph["company"] == company)
    if graph.get("company") and not writes_for_company:
        problems.append(f"company: you may ingest the data of {company_name(company) or 'your own company'} only. A mesh admin ingests for another company.")
    if graph.get("name") and writes_for_company:  # the names of a company's graphs are told only to those who may write for it
        for other in records():
            if (other["id"] != (existing or {}).get("id") and other["company"] == graph["company"]
                    and other["name"].casefold() == graph["name"].casefold()):
                problems.append(f'graph: a context graph named "{other["name"]}" exists for {company_name(other["company"])} (id {other["id"]}). '
                                f'Send "graph_id": "{other["id"]}" to replace it, or choose another name.')
    return problems, existing


def _from_upload(data: dict[str, Any], info: dict[str, Any]) -> dict[str, Any]:
    """What a correction takes from the uploaded graph when the JSON leaves it out: synthetic true when every input is
    marked invented, and sharing "group" with sensitivity Internal for a graph of the shared inputs node Others."""
    fill: dict[str, Any] = {}
    if data.get("synthetic") is None and info.get("synthetic"):
        fill["synthetic"] = True
    raw = data.get("company")
    if raw in (None, "") and isinstance(data.get("companies"), list):
        listed = [c for c in data["companies"] if c not in (None, "")]
        raw = listed[0] if len(listed) == 1 else None
    owner = company_of(raw) if raw not in (None, "") else None
    if owner and is_shared(owner):
        if data.get("sharing") in (None, ""):
            fill["sharing"] = "group"
        if data.get("sensitivity") in (None, ""):
            fill["sensitivity"] = "Internal"
    return fill


def ingest(data: Any, user: dict[str, Any], *, check_only: bool = False,
           uploaded: Callable[[str], dict[str, Any] | None] | None = None) -> dict[str, Any]:
    """Check the JSON and keep it as a context graph, or replace the graph its graph_id names. check_only checks and
    keeps nothing. ``uploaded`` looks up a graph made by Upload input by its id (services.uploads.upload_graph_info), so
    a graph_id that names one makes the JSON its correction. Raises IngestRefused with the report when anything has to
    be fixed."""
    company, roles = str(user.get("company") or ""), list(user.get("roles") or [])
    graph_id = _text(data.get("graph_id")) if isinstance(data, dict) else ""
    corrects = uploaded(graph_id) if graph_id and uploaded and not GRAPH_ID.fullmatch(graph_id) else None
    fill = _from_upload(data, corrects) if corrects and "mesh_admin" in roles else {}
    graph, report = parse({**data, **fill} if fill else data)
    report["filled"] += [f'{key}: {json.dumps(value)}, as in the uploaded graph "{corrects["name"]}"' for key, value in fill.items()] if corrects else []
    with _lock:
        problems, existing = _store_problems(graph, graph_id, user, corrects)
        report["problems"] += problems
        if not report["problems"] and not graph.get("company"):  # never a graph without its company
            report["problems"].append('company: missing. Write "company" with the company that owns the data, for example "CEAT".')
        if report["problems"]:
            raise IngestRefused(report)
        result = {k: report[k] for k in ("filled", "defaults", "ignored", "warnings")}
        content = {k: graph[k] for k in ("name", "company", "description", "sensitivity", "sharing", "synthetic", "nodes", "edges")}
        sha = _sha(content)
        link = {"corrects": corrects["id"]} if corrects else {}
        if check_only:
            preview = {"id": existing["id"] if existing else None, **content, **link, "created": _who(user), "updated": None}
            shown_summary = summary({**preview, "id": preview["id"] or "cg-00000000"}, company, roles)
            if not existing:  # a graph that is not kept has no id and no routes yet
                shown_summary.update(id=None, endpoints=None)
            return {"graph": shown_summary,
                    "replaced": existing is not None, "unchanged": bool(existing and existing.get("sha256") == sha), "checked_only": True, **result}
        if existing and existing.get("sha256") == sha:
            return {"graph": summary(existing, company, roles), "replaced": False, "unchanged": True, **result}
        new_id = existing["id"] if existing else next(i for i in (f"cg-{uuid.uuid4().hex[:8]}" for _ in range(100)) if not _path(i).exists())
        record = {"id": new_id, **content, **({"corrects": existing["corrects"]} if existing and existing.get("corrects") else link),
                  "created": existing["created"] if existing else _who(user),
                  "updated": _who(user) if existing else None, "sha256": sha}
        _write_atomic(_path(new_id), record)
        _log({"action": "replaced" if existing else "created", "id": new_id, "name": record["name"], "company": record["company"],
              "nodes": len(record["nodes"]), "edges": len(record["edges"]), "sha256": sha, **({"corrects": record["corrects"]} if record.get("corrects") else {}),
              "user": str(user.get("sub") or ""), **_who(user)})
    return {"graph": summary(record, company, roles), "replaced": existing is not None, "unchanged": False, **result}


def drop(graph_id: str, user: dict[str, Any]) -> dict[str, Any]:
    """Delete a graph's file. The log keeps its id, name, company and counts. KeyError when the caller may not see it,
    PermissionError when the caller may not change it."""
    company, roles = str(user.get("company") or ""), list(user.get("roles") or [])
    with _lock:
        record = get(graph_id)
        if record is None or not may_see(record, company, roles):
            raise KeyError(graph_id)
        if not may_change(record, company, roles):
            raise PermissionError(f"Only {company_name(record['company'])} and mesh admins may drop this graph.")
        _path(graph_id).unlink()
        _cache.pop(str(_path(graph_id)), None)
        line = {"id": graph_id, "name": record["name"], "company": record["company"], "nodes": len(record["nodes"]), "edges": len(record["edges"])}
        _log({"action": "dropped", **line, "user": str(user.get("sub") or ""), **_who(user)})
    return {"dropped": {**line, "company_name": company_name(record["company"])}}


def shown(graph_id: str, company: str, roles: list[str]) -> dict[str, Any]:
    """The record of a graph the caller may see. KeyError otherwise."""
    record = get(graph_id)
    if record is None or not may_see(record, company, roles):
        raise KeyError(graph_id)
    return record


def as_json(record: dict[str, Any]) -> dict[str, Any]:
    """The graph in the format it was ingested in, with its graph_id, so it can be changed and sent back to replace it."""
    def clean(item: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
        out = {k: item[k] for k in keys}
        if item.get("aliases"):
            out["aliases"] = item["aliases"]
        if item.get("properties"):
            out["properties"] = item["properties"]
        return out
    out = {"graph_id": record["id"], "graph": record["name"], "company": company_name(record["company"]),
           **({"description": record["description"]} if record.get("description") else {}),
           "sensitivity": record["sensitivity"], "sharing": record["sharing"], "synthetic": record["synthetic"],
           "nodes": [clean(n, ("id", "type", "name")) for n in record["nodes"]],
           "edges": [clean(e, ("id", "type", "source", "target")) for e in record["edges"]]}
    return out


def view(record: dict[str, Any]) -> dict[str, Any]:
    """Nodes and edges in the shape the graph drawing of the Context graph page takes."""
    return {"id": record["id"], "name": record["name"], "documents": [],
            "nodes": [{"id": n["id"], "type": n["type"], "label": n["name"], "subsidiary": record["company"]} for n in record["nodes"]],
            "edges": [{"id": e["id"], "type": e["type"], "source": e["source"], "target": e["target"], "status": "approved"} for e in record["edges"]],
            "counts": dict(Counter(n["type"] for n in record["nodes"]))}


def quality(record: dict[str, Any]) -> list[dict[str, str]]:
    """Points to look at in an ingested graph: nodes with no edge, two nodes of one type with one name, nodes of type
    Unknown, and a graph that falls into separate parts. One "ok" line when there is none."""
    nodes, edges = record["nodes"], record["edges"]
    degree = Counter(end for e in edges for end in (e["source"], e["target"]))
    notes: list[dict[str, str]] = []
    alone = [n["name"] for n in nodes if not degree[n["id"]]]
    if alone:
        shown = ", ".join(f'"{x}"' for x in alone[:5]) + (f" and {len(alone) - 5} more" if len(alone) > 5 else "")
        notes.append({"level": "warn", "text": f"{len(alone)} {'node has' if len(alone) == 1 else 'nodes have'} no edge: {shown}"})
    twice = [f'{t} "{name}"' for (t, name), k in Counter((n["type"], n["name"].casefold()) for n in nodes).items() if k > 1]
    if twice:
        notes.append({"level": "warn", "text": f"The same name is written for two nodes of one type: {', '.join(twice[:5])}"})
    unknown = sum(1 for n in nodes if n["type"] == "Unknown")
    if unknown:
        notes.append({"level": "note", "text": f"{unknown} {'node is' if unknown == 1 else 'nodes are'} of type Unknown, the end of an edge whose node was not written"})
    parent = {n["id"]: n["id"] for n in nodes}
    def root(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    for e in edges:
        if e["source"] in parent and e["target"] in parent:
            parent[root(e["source"])] = root(e["target"])
    parts = len({root(n["id"]) for n in nodes if degree[n["id"]]})
    if parts > 1:
        notes.append({"level": "note", "text": f"The linked nodes fall into {parts} separate parts with no edge between them"})
    return notes or [{"level": "ok", "text": "Every node has an edge, no name repeats and the graph is one connected whole"}]


def sample(company: str) -> dict[str, Any]:
    """A small graph in the format, with invented values, for the caller's company."""
    name = company_name(company) if company in node_ids() and not is_shared(company) else company_nodes()[0].display
    return {
        "graph": "Example: spare parts of a mixing line",
        "company": name,
        "description": "Example data, invented to show the JSON structure.",
        "sensitivity": "Internal",
        "sharing": "company",
        "nodes": [
            {"id": "plant-a", "type": "Plant", "name": "Plant A", "properties": {"city": "Example city"}},
            {"id": "line-1", "type": "Line", "name": "Mixing line 1"},
            {"id": "m-01", "type": "Machine", "name": "Internal mixer M-01", "aliases": ["Mixer 1"]},
            {"id": "rs-200", "type": "Part", "name": "Rotor seal RS-200", "properties": {"material": "FKM", "stock": 14}},
            {"id": "sup-x", "type": "Supplier", "name": "Supplier X", "properties": {"lead_time_days": 21}},
            {"id": "sup-y", "type": "Supplier", "name": "Supplier Y", "properties": {"lead_time_days": 35}},
            {"id": "wear", "type": "Defect", "name": "Seal wear"},
        ],
        "edges": [
            {"type": "HAS_LINE", "source": "plant-a", "target": "line-1"},
            {"type": "HAS_MACHINE", "source": "line-1", "target": "m-01"},
            {"type": "USES_PART", "source": "m-01", "target": "rs-200", "properties": {"per_year": 6}},
            {"type": "SUPPLIES", "source": "sup-x", "target": "rs-200", "properties": {"preferred": True}},
            {"type": "SUPPLIES", "source": "sup-y", "target": "rs-200"},
            {"type": "AFFECTS", "source": "wear", "target": "rs-200"},
            {"type": "SEEN_ON", "source": "wear", "target": "m-01", "properties": {"times_in_2026": 4}},
        ],
    }


# ── queries ─────────────────────────────────────────────────────────────────
def _node_out(node: dict[str, Any]) -> dict[str, Any]:
    return {"id": node["id"], "type": node["type"], "name": node["name"], "aliases": node.get("aliases", []), "properties": node.get("properties", {})}


def _edge_out(edge: dict[str, Any], by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    s, t = by_id[edge["source"]], by_id[edge["target"]]
    return {"id": edge["id"], "type": edge["type"], "source": {"id": s["id"], "name": s["name"], "type": s["type"]},
            "target": {"id": t["id"], "name": t["name"], "type": t["type"]}, "properties": edge.get("properties", {}),
            "text": f'{s["name"]} {edge["type"]} {t["name"]}'}


def find(record: dict[str, Any], ref: Any) -> list[dict[str, Any]]:
    """The nodes a reference names: its id, else its name, else another name, in any case."""
    text = _text(ref)
    if not text:
        return []
    exact = [n for n in record["nodes"] if n["id"] == text]
    if exact:
        return exact
    low = text.casefold()
    by_name = [n for n in record["nodes"] if n["name"].casefold() == low]
    return by_name or [n for n in record["nodes"] if any(a.casefold() == low for a in n.get("aliases", []))]


def _one(record: dict[str, Any], ref: Any) -> dict[str, Any]:
    found = find(record, ref)
    if not found:
        names = [n["name"] for n in record["nodes"]]
        raise NodeNotFound(_text(ref), difflib.get_close_matches(_text(ref), names, n=3, cutoff=0.5))
    if len(found) > 1:
        raise NodeAmbiguous(_text(ref), [_node_out(n) for n in found[:10]])
    return found[0]


def query_node(record: dict[str, Any], ref: Any, hops: int = 1) -> dict[str, Any]:
    """A node with its properties, the nodes up to hops edges away, and the edges walked to reach them: the node's own
    edges, and with two hops also the edges of the nodes one edge away."""
    start = _one(record, ref)
    by_id = {n["id"]: n for n in record["nodes"]}
    reached = {start["id"]}
    frontier = {start["id"]}
    walked: list[dict[str, Any]] = []
    walked_ids: set[str] = set()
    for _ in range(max(1, min(int(hops), 2))):
        nxt = set()
        for e in record["edges"]:
            if e["source"] in frontier or e["target"] in frontier:
                if e["id"] not in walked_ids:
                    walked_ids.add(e["id"])
                    walked.append(e)
                nxt |= {e["source"], e["target"]} - reached
        reached |= nxt
        frontier = nxt
    edges = walked
    neighbours = [by_id[i] for i in sorted(reached - {start["id"]}, key=lambda i: by_id[i]["name"].casefold())]
    return {"node": _node_out(start), "neighbours": [_node_out(n) for n in neighbours[:FOUND_MAX]], "neighbours_total": len(neighbours),
            "edges": [_edge_out(e, by_id) for e in edges[:EDGES_MAX]], "edges_total": len(edges)}


def _property_matches(node: dict[str, Any], wanted: dict[str, Any]) -> bool:
    for key, value in wanted.items():
        have = node.get("properties", {}).get(key)
        values = have if isinstance(have, list) else [have]
        if not any(str(v).casefold() == str(value).casefold() for v in values if v is not None):
            return False
    return True


def query_nodes(record: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    """Nodes by type (equal), name (a part of the name or another name) and properties (equal values), in any case."""
    ntype, name = _text(filters.get("type")).casefold(), _text(filters.get("name")).casefold()
    props = filters.get("properties") or {}
    found = [n for n in record["nodes"]
             if (not ntype or n["type"].casefold() == ntype)
             and (not name or name in n["name"].casefold() or any(name in a.casefold() for a in n.get("aliases", [])))
             and _property_matches(n, props)]
    return {"nodes": [_node_out(n) for n in found[:FOUND_MAX]], "total": len(found)}


def query_edges(record: dict[str, Any], filters: dict[str, Any]) -> dict[str, Any]:
    """Edges by type (equal, in any case), source and target (a node id, name or other name)."""
    etype = _text(filters.get("type")).casefold()
    sources = {n["id"] for n in find(record, filters["source"])} if filters.get("source") not in (None, "") else None
    targets = {n["id"] for n in find(record, filters["target"])} if filters.get("target") not in (None, "") else None
    for ref, ids in ((filters.get("source"), sources), (filters.get("target"), targets)):
        if ids is not None and not ids:
            _one(record, ref)  # raises NodeNotFound with the closest names
    by_id = {n["id"]: n for n in record["nodes"]}
    found = [e for e in record["edges"] if (not etype or e["type"].casefold() == etype)
             and (sources is None or e["source"] in sources) and (targets is None or e["target"] in targets)]
    return {"edges": [_edge_out(e, by_id) for e in found[:EDGES_MAX]], "total": len(found)}


PATH_HOPS_MAX = 6  # the longest way a path query looks for, in edges
PATHS_MAX = 3  # the shortest ways given back
SIMILAR_MAX = 20


def _neighbours(record: dict[str, Any]) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for e in record["edges"]:
        if e["source"] != e["target"]:
            out.setdefault(e["source"], set()).add(e["target"])
            out.setdefault(e["target"], set()).add(e["source"])
    return out


def query_path(record: dict[str, Any], from_ref: Any, to_ref: Any, max_hops: int = 4) -> dict[str, Any]:
    """The shortest ways from one node to another, of at most max_hops edges. An edge is walked in either direction and
    is given back as it is stored, so its direction stays as written. Up to PATHS_MAX ways of the same length."""
    start, goal = _one(record, from_ref), _one(record, to_ref)
    by_id = {n["id"]: n for n in record["nodes"]}
    head = {"from": _node_out(start), "to": _node_out(goal)}
    if start["id"] == goal["id"]:
        return {**head, "hops": 0, "paths": [], "note": "The two names are the same node."}
    touching: dict[str, list[dict[str, Any]]] = {}
    for e in record["edges"]:
        touching.setdefault(e["source"], []).append(e)
        if e["target"] != e["source"]:
            touching.setdefault(e["target"], []).append(e)
    depth = {start["id"]: 0}
    before: dict[str, list[tuple[str, dict[str, Any]]]] = {}  # each node with the nodes and edges one step nearer the start
    frontier = [start["id"]]
    while frontier and goal["id"] not in depth and depth[frontier[0]] < max_hops:
        level = depth[frontier[0]] + 1
        reached = []
        for node in frontier:
            for e in touching.get(node, []):
                other = e["target"] if e["source"] == node else e["source"]
                if other not in depth:
                    depth[other] = level
                    reached.append(other)
                if depth[other] == level:
                    before.setdefault(other, []).append((node, e))
        frontier = reached
    if goal["id"] not in depth:
        return {**head, "hops": None, "paths": [], "note": f"No way of at most {max_hops} edges joins the two nodes."}
    ways: list[list[dict[str, Any]]] = []

    def back(node: str, tail: list[dict[str, Any]]) -> None:
        if len(ways) >= PATHS_MAX:
            return
        if node == start["id"]:
            ways.append(list(reversed(tail)))
            return
        for prev, e in before.get(node, []):
            back(prev, [*tail, e])

    back(goal["id"], [])
    paths = []
    for way in ways:
        steps = [_edge_out(e, by_id) for e in way]
        paths.append({"edges": steps, "text": ", then ".join(s["text"] for s in steps)})
    return {**head, "hops": depth[goal["id"]], "paths": paths}


def query_similar(record: dict[str, Any], ref: Any, top: int = 5) -> dict[str, Any]:
    """Nodes of the same type as the node, ranked by the neighbours they share with it: shared neighbours divided by all
    the neighbours of the two (the Jaccard index). The shared neighbours are given as the reason."""
    node = _one(record, ref)
    by_id = {n["id"]: n for n in record["nodes"]}
    near = _neighbours(record)
    mine = near.get(node["id"], set())
    found = []
    for other in record["nodes"]:
        if other["id"] == node["id"] or other["type"] != node["type"]:
            continue
        theirs = near.get(other["id"], set())
        shared = mine & theirs
        if shared:
            union = mine | theirs
            found.append({"node": _node_out(other), "score": round(len(shared) / len(union), 3),
                          "shared": sorted((by_id[i]["name"] for i in shared), key=str.casefold),
                          "reason": f"shares {len(shared)} of the {len(union)} neighbours of the two"})
    found.sort(key=lambda f: (-f["score"], f["node"]["name"].casefold()))
    out: dict[str, Any] = {"node": _node_out(node), "similar": found[:top], "total": len(found),
                           "rule": "nodes of the same type, ranked by shared neighbours divided by all the neighbours of the two"}
    if not mine:
        out["note"] = "The node has no edges, so no node shares a neighbour with it."
    return out


def overview(record: dict[str, Any]) -> dict[str, Any]:
    """What the graph holds: the node types and the edge types with their counts, and the node types each edge type joins."""
    by_id = {n["id"]: n for n in record["nodes"]}
    kinds: dict[str, dict[str, Any]] = {}
    for e in record["edges"]:
        k = kinds.setdefault(e["type"], {"type": e["type"], "count": 0, "from_types": set(), "to_types": set()})
        k["count"] += 1
        k["from_types"].add(by_id[e["source"]]["type"])
        k["to_types"].add(by_id[e["target"]]["type"])
    linked = {e["source"] for e in record["edges"]} | {e["target"] for e in record["edges"]}
    return {"nodes": len(record["nodes"]), "edges": len(record["edges"]),
            "node_types": dict(Counter(n["type"] for n in record["nodes"]).most_common()),
            "edge_types": [{**k, "from_types": sorted(k["from_types"]), "to_types": sorted(k["to_types"])}
                           for k in sorted(kinds.values(), key=lambda k: (-k["count"], k["type"]))],
            "nodes_without_edges": sum(1 for n in record["nodes"] if n["id"] not in linked)}


def _content(tokens: list[str]) -> list[str]:
    return [t for t in tokens if t not in STOPWORDS]


def _score(node: dict[str, Any], tokens: list[str], content: set[str]) -> tuple[float, str]:
    name = norm_tokens(node["name"])
    if name and _phrase_in(name, tokens):
        return 5.0, "name"
    for alias in node.get("aliases", []):
        phrase = norm_tokens(alias)
        if phrase and _phrase_in(phrase, tokens):
            return 4.0, "other name"
    ident = norm_tokens(node["id"])
    if len(ident) > 1 and _phrase_in(ident, tokens):
        return 3.0, "id"
    for value in node.get("properties", {}).values():
        for v in (value if isinstance(value, list) else [value]):
            phrase = _content(norm_tokens(str(v))) if isinstance(v, str) else []
            if phrase and _phrase_in(phrase, tokens):
                return 2.0, "property"
    words = set(_content(name))
    shared = words & content
    if words and len(shared) / len(words) >= 0.5 and any(not w.isdigit() for w in shared):
        return 1.0 + len(shared) / len(words), "part of the name"
    return 0.0, ""


def _near(a: str, b: str) -> bool:
    """Two words of one stem as far as plain matching can tell: equal, or one starts with the other's first five letters."""
    return a == b or (len(a) >= 5 and len(b) >= 5 and a[:5] == b[:5])


def retrieve(record: dict[str, Any], question: str) -> dict[str, Any]:
    """The nodes a question names and the edges around them, ranked, numbered N1.. and E1.. for citations."""
    tokens = norm_tokens(question)
    content = set(_content(tokens))
    by_id = {n["id"]: n for n in record["nodes"]}
    scored = {n["id"]: s for n in record["nodes"] if (s := _score(n, tokens, content))[0] >= 1.5}
    types_named = {t for t in {n["type"] for n in record["nodes"]} if _phrase_in(norm_tokens(t), tokens)}
    if not scored and types_named:
        typed = [n for n in record["nodes"] if n["type"] in types_named][:CONTEXT_NODES]
        scored = {n["id"]: (0.75, "type") for n in typed}
    if not scored:
        return {"matched": [], "nodes": [], "edges": []}

    def edge_rank(e: dict[str, Any]) -> tuple[float, str]:
        s, t = scored.get(e["source"], (0.0, ""))[0], scored.get(e["target"], (0.0, ""))[0]
        rank = s + t
        other = by_id[e["target"]] if s >= t else by_id[e["source"]]
        if other["type"] in types_named:
            rank += 1
        if any(_near(w, q) for w in _content(norm_tokens(e["type"].replace("_", " "))) for q in content):
            rank += 1
        return (-rank, f'{by_id[e["source"]]["name"]} {e["type"]} {by_id[e["target"]]["name"]}'.casefold())

    edges = sorted((e for e in record["edges"] if e["source"] in scored or e["target"] in scored), key=edge_rank)[:CONTEXT_EDGES]
    order = sorted(scored, key=lambda i: (-scored[i][0], by_id[i]["name"].casefold()))
    ids = list(dict.fromkeys([*order, *(x for e in edges for x in (e["source"], e["target"]))]))[:CONTEXT_NODES]
    nodes = [{"ref": f"N{k}", **_node_out(by_id[i])} for k, i in enumerate(ids, 1)]
    return {"matched": [{"id": i, "name": by_id[i]["name"], "type": by_id[i]["type"], "matched_on": scored[i][1]} for i in order],
            "nodes": nodes, "edges": [{"ref": f"E{k}", **_edge_out(e, by_id)} for k, e in enumerate(edges, 1)]}


def _one_line(value: Any, limit: int) -> str:
    """Any text of the graph as one line, so it can never start a line of its own in the prompt."""
    return " ".join(str(value).split())[:limit]


def _properties_text(props: dict[str, Any]) -> str:
    parts = []
    for key, value in list(props.items())[:PROMPT_PROPERTIES]:
        text = ", ".join(str(v) for v in value) if isinstance(value, list) else str(value)
        parts.append(f"{_one_line(key, TYPE_MAX)}: {_one_line(text, PROMPT_VALUE_CHARS)}")
    return ". ".join(parts)


def prompt(question: str, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> tuple[str, str]:
    system = PROMPT_FILE.read_text(encoding="utf-8").strip()
    lines = [f"Question: {_one_line(question, QUESTION_MAX)}", "", "<graph_data>", "Nodes:"]
    for n in nodes:
        props = _properties_text(n["properties"])
        lines.append(f'{n["ref"]} {_one_line(n["name"], TEXT_MAX)} ({_one_line(n["type"], TYPE_MAX)}){". " + props if props else ""}')
    lines += ["", "Edges:"]
    for e in edges:
        props = _properties_text(e["properties"])
        lines.append(f'{e["ref"]} {_one_line(e["text"], 2 * TEXT_MAX + TYPE_MAX + 2)}{". " + props if props else ""}')
    lines.append("</graph_data>")
    return system, "\n".join(lines)


def checked_answer(text: str, refs: set[str]) -> tuple[str | None, int]:
    """The sentences of a model answer that cite at least one node or edge given to it, and how many were left out."""
    text = " ".join((text or "").split())
    if text.rstrip(".").casefold() == NO_ANSWER.rstrip(".").casefold():
        return NO_ANSWER, 0
    pieces: list[str] = []
    for piece in re.split(r"(?<=[.!?])\s+", text):
        lead = re.match(r"((?:\[[^\]]*\]\s*)+[.!?]?)\s*(.*)", piece)
        if pieces and lead:  # a citation written after the full stop belongs to the sentence before it
            pieces[-1] = f"{pieces[-1]} {lead.group(1).strip()}"
            piece = lead.group(2)
        if piece:
            pieces.append(piece)
    kept, dropped = [], 0
    for sentence in pieces:
        cited = {ref.strip() for m in CITATION.finditer(sentence) for ref in m.group(1).split(",")}
        if cited & refs:
            kept.append(sentence)
        else:
            dropped += 1
    return (" ".join(kept) or None), dropped


def _blocked_words(reason: str, record: dict[str, Any]) -> str:
    if "development only" in reason:
        return "the answer model is a cloud model, which is allowed in development only"
    if "synthetic" in reason:
        return "the graph is real data (synthetic is false), and the answer model is a cloud model, which reads invented data only"
    if "Confidential or Restricted" in reason:
        return f"the graph is {record['sensitivity']}, which the cloud answer model may not read"
    return reason


def ask(record: dict[str, Any], question: str, *, app_env: str, backend: Any = None,
        backend_factory: Callable[[], Any] | None = None) -> dict[str, Any]:
    """The edges around what a question names, and a written answer when the model policy allows the answer model for
    this graph. Every sentence of the answer cites the nodes or edges it rests on, and a sentence that cites none is left out."""
    from services.context import policy as model_policy
    from services.context.llm import make_caller
    from services.context.pii import strip_contact_details

    question, _ = strip_contact_details(" ".join(question.split())[:QUESTION_MAX])
    found = retrieve(record, question)
    out: dict[str, Any] = {"question": question, **found, "answer": None, "answer_note": None}
    if not found["nodes"]:
        out["answer_note"] = "Nothing in the graph matches the question. Name a node, another name or a type of the graph."
        return out
    choice = model_policy.choice_for("answer")
    ok, reason = model_policy.allowed(choice, app_env, {record["sensitivity"]}, bool(record["synthetic"]))
    if ok and backend is None:
        backend = backend_factory() if backend_factory else None
        if backend is None:
            out["answer_note"] = "No answer model is configured, so the nodes and edges are the answer."
            return out
    system, user_text = prompt(question, found["nodes"], found["edges"])
    edges = list(found["edges"])
    while model_policy.estimate_tokens(system + user_text) > choice.max_input_tokens and len(edges) > 1:
        edges = edges[:-1]
        system, user_text = prompt(question, found["nodes"], edges)
    calls: list[dict[str, Any]] = []
    call = make_caller(backend, app_env=app_env, trace_id=uuid.uuid4().hex, sensitivities={record["sensitivity"]},
                       all_synthetic=bool(record["synthetic"]), calls=calls)
    text = call("answer", system, user_text, PROMPT_VERSION)
    if not ok:
        out["answer_note"] = f"No written answer: {_blocked_words(reason, record)}. The nodes and edges are the answer."
        return out
    if text is None:
        out["answer_note"] = "The answer model did not answer, so the nodes and edges are the answer."
        return out
    refs = {n["ref"] for n in found["nodes"]} | {e["ref"] for e in edges}
    answer, dropped = checked_answer(text, refs)
    out["answer"] = answer
    if answer is None:
        out["answer_note"] = "The answer of the model cited no node or edge, so it is not shown. The nodes and edges are the answer."
    elif dropped:
        out["answer_note"] = f"{dropped} {'sentence' if dropped == 1 else 'sentences'} without a citation left out."
    return out
