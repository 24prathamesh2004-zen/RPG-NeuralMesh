"""Documents a mesh admin uploads from the screens, grouped into named context graphs.

A file (text, Markdown, CSV, PDF or Word) becomes one document of the catalogue item the admin chose, on the node of
the company chosen, or on the shared inputs node ("Others") for a file that belongs to no one company. The text is read
out of the file, cut into the rows the node indexes, and linked to the concepts of the group vocabulary whose names
appear in it. The record is kept at ``data_pack/<node>/contributions/<doc>.json``, the pack of the item's domain is
rebuilt with it (knowledge.packgen.rebuild_domain_pack), the node reads the rebuilt pack without a restart and the
central graph is refreshed from the node export. A failed check removes the record again and nothing changes.

Every upload belongs to one context graph: a name the admin gives with the first input, that later inputs are added to.
The graph is the union of the parts its inputs made in the central graph. Dropping a graph removes every input in it.

In this development build the API process writes into the node folders on the same machine, as the talent import does.
A deployment with one node per company network moves the writing into a node tool.
"""
from __future__ import annotations

import functools
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from knowledge import packgen
from services import export_formats, graph_extract
from knowledge.validator import PackCheckFailed
from services.mesh_graph import _phrase_in, norm_tokens
from shared.registry import is_shared, node as registered_node, node_ids

KINDS = ["sop", "rca", "playbook", "post_mortem", "standard", "report", "policy", "wiki", "aggregate", "note", "study_material", "role_profile", "other"]
KIND_LABEL_MAX = 60
# The areas a new catalogue item can be added to, by the first letter of its code. Talent, mesh and shared-input items
# are not added at upload.
NEW_ITEM_AREAS = {"E": "engineering", "O": "operations", "C": "commercial", "R": "research", "F": "corporate", "L": "lessons"}
NEW_ITEM_TITLE_MAX = 120
# A catalogue item named at upload starts with the strictest rule: nothing of it leaves the company.
NEW_ITEM_RULE = {"sensitivity": "Restricted", "ceiling": "MD", "never_leave": True, "owner_role": "Node owner"}
FORMATS = {".txt": "text", ".md": "markdown", ".csv": "csv", ".json": "json", ".pdf": "pdf", ".docx": "word"}
MAX_BYTES = 20_000_000
MIN_CHARS = 40
SUMMARY_CHARS = 400
GRAPH_NAME_MAX = 80
# a PDF or Word file often stores "fi", "fl" and "ff" as one joined letter, which the search and the linking read as no letter at all
JOINED_LETTERS = str.maketrans({"\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl", "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "st", "\ufb06": "st"})
EXPORT_FORMATS = export_formats.FIXED  # the formats written by code. services.export_formats adds the template formats


TOO_DEEP = "The JSON file is nested too deeply to be read."
# One change of the upload records at a time. Two uploads at the same moment would take the same document id, and a
# rebuild would read the records while another change writes them. The routes run these functions in worker threads.
_WRITES = threading.RLock()


def _one_at_a_time(fn):
    @functools.wraps(fn)
    def held(*args: Any, **kwargs: Any) -> Any:
        with _WRITES:
            return fn(*args, **kwargs)
    return held


class UploadRefused(Exception):
    """The upload was not kept. The message says why in plain words."""


def extract_text(filename: str, data: bytes) -> tuple[str, str]:
    """The text of the file and the name of its format. A knowledge pack is refused here: it goes through the import tool."""
    ext = Path(filename).suffix.lower()
    fmt = FORMATS.get(ext)
    if fmt is None:
        raise UploadRefused(f"{ext or 'a file without an extension'} is not read. Upload .txt, .md, .csv, .json, .pdf or .docx.")
    if len(data) > MAX_BYTES:
        raise UploadRefused(f"The file is larger than {MAX_BYTES // 1_000_000} MB.")
    if fmt == "pdf":
        from pypdf import PdfReader
        try:
            reader = PdfReader(io.BytesIO(data))
            pages = [(page.extract_text() or "").strip() for page in reader.pages]
        except Exception as exc:  # noqa: BLE001 - a broken file is refused with the library's words
            raise UploadRefused(f"The PDF could not be read: {type(exc).__name__}.") from exc
        text = "\n\n".join(p for p in pages if p)
    elif fmt == "word":
        import docx
        try:
            document = docx.Document(io.BytesIO(data))
        except Exception as exc:  # noqa: BLE001
            raise UploadRefused(f"The Word file could not be read: {type(exc).__name__}.") from exc
        parts = [p.text.strip() for p in document.paragraphs if p.text.strip()]
        for table in document.tables:
            for row in table.rows:
                cells = [c.text.strip() for c in row.cells if c.text.strip()]
                if cells:
                    parts.append(" | ".join(cells))
        text = "\n\n".join(parts)
    else:
        text = data.decode("utf-8", errors="replace")
        if fmt == "json":
            try:
                parsed = json.loads(text)
            except RecursionError as exc:
                raise UploadRefused(TOO_DEEP) from exc
            except ValueError as exc:
                raise UploadRefused("The JSON file could not be parsed.") from exc
            if isinstance(parsed, dict) and parsed.get("format") == "neuralmesh.knowledge-pack":
                raise UploadRefused("This is a knowledge pack. A pack is sent through the import tool of the context contract, not uploaded.")
            try:
                text = _json_text(parsed)
            except RecursionError as exc:
                raise UploadRefused(TOO_DEEP) from exc
        elif fmt == "markdown":
            # heading marks, list markers and emphasis are layout, not words: the summary and the index keep the words only
            text = re.sub(r"^\s{0,3}#{1,6}\s+", "", text, flags=re.M)
            text = re.sub(r"^\s*[-*+]\s+", "", text, flags=re.M)
            text = text.replace("**", "").replace("__", "")
    text = text.replace("\r\n", "\n").translate(JOINED_LETTERS).strip()
    if len(text) < MIN_CHARS:
        raise UploadRefused(f"The file holds {len(text)} characters of text. At least {MIN_CHARS} are needed.")
    return text, fmt


def _json_text(value: Any, depth: int = 0) -> str:
    """JSON as readable lines: one paragraph per top-level entry, "key: value" inside."""
    if isinstance(value, dict):
        lines = [f"{k}: {_json_text(v, depth + 1)}" for k, v in value.items()]
        return ("\n\n" if depth == 0 else ", ").join(lines)
    if isinstance(value, list):
        return ("\n\n" if depth == 0 else ", ").join(_json_text(v, depth + 1) for v in value)
    return str(value)


def summary_of(text: str, limit: int = SUMMARY_CHARS) -> str:
    """The first sentences of the text, up to ``limit`` characters."""
    flat = " ".join(text.split())
    if len(flat) <= limit:
        return flat
    cut = flat.rfind(". ", 0, limit)
    return (flat[: cut + 1] if cut > limit // 3 else flat[:limit].rstrip() + "…").strip()


def datapoints_of(node: str) -> dict[str, dict[str, Any]]:
    """The catalogue items of a node from its pack files: code -> datapoint fields plus ``domain``."""
    out: dict[str, dict[str, Any]] = {}
    for path in sorted((packgen.DATA / node / "packs").glob("*/pack.json")):
        try:
            pack = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for dp in pack.get("datapoints", []):
            out[dp["catalogue_id"]] = {**dp, "domain": pack["pack"]["domain"]}
    return out


def _folder(node: str) -> Path:
    return packgen.DATA / node / packgen.CONTRIBUTIONS


def new_item_areas(node: str) -> list[dict[str, str]]:
    """The areas a new catalogue item of the node can go to: those of NEW_ITEM_AREAS the node has a pack for. The
    shared inputs node gets none, because every input there goes under its one shared item."""
    if is_shared(node):
        return []
    have = {dp["domain"] for dp in datapoints_of(node).values()}
    return [{"letter": letter, "domain": domain, "title": packgen.DOMAIN_TITLES[domain]} for letter, domain in NEW_ITEM_AREAS.items() if domain in have]


def _new_item(node: str, title: str, domain: str, user: dict, synthetic: bool = False) -> tuple[str, dict, Path]:
    """Name a new catalogue item of the node in the area ``domain`` and keep it under added_items. The item takes the
    next free code of the area's letter and the rule NEW_ITEM_RULE. Returns the code, the item with its domain, and the
    file written, so that a failed upload can take it back."""
    title = " ".join((title or "").split())
    if is_shared(node):
        raise UploadRefused("Every input of the shared node goes under its one shared item. A new item is added to a company.")
    if len(title) < 3:
        raise UploadRefused("The name of a new catalogue item has at least 3 characters.")
    if len(title) > NEW_ITEM_TITLE_MAX:
        raise UploadRefused(f"The name of a new catalogue item has at most {NEW_ITEM_TITLE_MAX} characters.")
    areas = {a["domain"]: a["letter"] for a in new_item_areas(node)}
    if domain not in areas:
        raise UploadRefused(f"{registered_node(node).display} has no {domain} area for a new item. Areas: {', '.join(areas) or 'none'}.")
    items = datapoints_of(node)
    for code, dp in items.items():
        if dp["title"].casefold() == title.casefold():
            raise UploadRefused(f'{registered_node(node).display} has the item {code} named "{dp["title"]}". Choose it from the list.')
    taken = set(items) | set(packgen.added_items_of(node))
    letter = areas[domain]
    number = next(n for n in range(1, 100) if f"{letter}-{n:02d}" not in taken)
    code = f"{letter}-{number:02d}"
    item = {"code": code, "title": title, **NEW_ITEM_RULE, "synthetic": bool(synthetic),  # the mark of the upload that named it
            "added": {"by_role": "Mesh admin", "by_company": str(user.get("company", "")), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    path = packgen.DATA / node / packgen.ADDED_ITEMS / f"{code}.json"
    _write_atomic(path, item)
    return code, {**item, "domain": domain}, path


def _next_id(node: str, code: str) -> str:
    taken = {r["document"]["id"] for status in ("accepted", "rejected", "removed") for r in packgen.contributions_of(node, status)}
    n = 1
    while f"{node}:{code}-U{n:03d}" in taken:
        n += 1
    return f"{node}:{code}-U{n:03d}"


def concepts_in(rt: Any, text: str, tags: list[str] | None = None) -> dict[str, str]:
    """The concepts of the group vocabulary the text is linked to, each with how it matched: "phrase" when the label or
    an alias appears in the text as a whole phrase, "words" when every word of the label appears somewhere in the text,
    "tag" when a tag of the upload is the label or an alias, or inside one."""
    tokens = norm_tokens(text)
    present = set(tokens)
    tag_phrases = [norm_tokens(t.replace("-", " ")) for t in (tags or [])]
    found: dict[str, str] = {}
    for n, d in rt.mesh.graph.nodes(data=True):
        if d.get("type") != "Concept" or d.get("retired"):
            continue
        names = [norm_tokens(x) for x in [d.get("label") or "", *(d.get("aliases") or [])]]
        names = [x for x in names if x]
        if any(_phrase_in(phrase, tokens) for phrase in names):
            found[n] = "phrase"
        elif any(tp and (_phrase_in(tp, phrase) or _phrase_in(phrase, tp)) for phrase in names for tp in tag_phrases):
            found[n] = "tag"
        elif names and all(w in present for w in names[0]):
            found[n] = "words"
    return dict(sorted(found.items()))


def _tags(raw: str | list[str] | None) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,\n]", raw or "")
    return list(dict.fromkeys(t for t in (packgen._tag(x) for x in items) if t))


def _write_atomic(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


# ── context graphs: the named groups of uploads ──────────────────────────────
def graph_ref(record: dict) -> dict[str, str]:
    """The context graph an upload belongs to. An upload kept before graphs had names is its own graph, named after
    its title, with the document id as the graph id."""
    ref = record.get("context_graph")
    if isinstance(ref, dict) and ref.get("id") and ref.get("name"):
        return {"id": str(ref["id"]), "name": str(ref["name"])}
    return {"id": record["document"]["id"], "name": record["document"]["title"]}


def _all_records(statuses: tuple[str, ...] = ("accepted",)) -> list[tuple[str, dict]]:
    """(node, record) for every upload of every node with one of the statuses."""
    return [(node, record) for node in node_ids() for status in statuses for record in packgen.contributions_of(node, status)]


def _graph_for(graph_id: str | None, graph_name: str | None, title: str) -> dict[str, str]:
    """The context graph a new upload joins: an existing one by id, a new one by name, or, when neither is given, the
    graph named after the title (joined when it exists, opened when it does not)."""
    existing = {graph_ref(r)["id"]: graph_ref(r) for _, r in _all_records(("accepted", "removed"))}
    by_name = {graph_ref(r)["name"].casefold(): graph_ref(r) for _, r in _all_records()}
    graph_id = (graph_id or "").strip()
    graph_name = " ".join((graph_name or "").split())
    if graph_id:
        if graph_id not in existing:
            raise UploadRefused(f"There is no context graph {graph_id} to add to. Choose one from the list, or open a new one with a name.")
        return existing[graph_id]
    if graph_name:
        if len(graph_name) > GRAPH_NAME_MAX:
            raise UploadRefused(f"The name of a context graph has at most {GRAPH_NAME_MAX} characters.")
        if graph_name.casefold() in by_name:
            raise UploadRefused(f'A context graph named "{graph_name}" exists. Choose it to add this input to it, or give the new graph another name.')
        return {"id": f"g-{uuid.uuid4().hex[:8]}", "name": graph_name}
    name = " ".join(title.split())[:GRAPH_NAME_MAX].strip()
    return by_name.get(name.casefold()) or {"id": f"g-{uuid.uuid4().hex[:8]}", "name": name}


def upload_graph_info(graph_id: str) -> dict[str, Any] | None:
    """An uploaded context graph that a JSON may correct (services.context_graph_ingest): its id, its name and whether
    every input kept in it is marked invented, and the nodes that keep its inputs. None when no kept input carries the id."""
    found = [(node, r) for node, r in _all_records() if graph_ref(r)["id"] == graph_id]
    if not found:
        return None
    records = [r for _, r in found]
    return {"id": graph_id, "name": graph_ref(records[0])["name"], "synthetic": all(r.get("synthetic") is True for r in records),
            "nodes": sorted({node for node, _ in found})}


def graphs_of(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The context graphs of the listed uploads, newest first: id, name, how many inputs are in it and how many were
    removed, the nodes and companies that keep its inputs, and the time of the latest upload."""
    out: dict[str, dict[str, Any]] = {}
    for item in items:
        ref = item["context_graph"]
        g = out.setdefault(ref["id"], {"id": ref["id"], "name": ref["name"], "inputs": 0, "removed": 0, "nodes": set(), "companies": set(),
                                       "latest": item["upload"]["at"]})
        if item["status"] == "accepted":
            g["inputs"] += 1
            g["nodes"].add(item["node_id"])
            g["companies"].add(item["company"])
        elif item["status"] == "removed":
            g["removed"] += 1
        g["latest"] = max(g["latest"], item["upload"]["at"])
    graphs = [{**g, "nodes": sorted(g["nodes"]), "companies": sorted(g["companies"])} for g in out.values()]
    graphs.sort(key=lambda g: g["latest"], reverse=True)
    return graphs


AUTO_KIND = "auto"  # the kind choice that leaves the kind to services.upload_kind


def _extract_caller(rt: Any, sensitivity: str | None, synthetic: bool):
    """The model caller for the extract step, bound to the item's sensitivity and the upload's real or invented mark, so
    the model policy keeps a cloud model away from real data. None when no model is configured."""
    orchestrator = getattr(rt, "orchestrator", None)
    backend = getattr(orchestrator, "backend", None)
    if backend is None:
        return None
    from services.context.llm import make_caller
    return make_caller(backend, app_env=getattr(orchestrator, "app_env", "development"), trace_id=f"extract-{uuid.uuid4().hex[:8]}",
                       sensitivities={sensitivity} if sensitivity else set(), all_synthetic=bool(synthetic), calls=[])


def extract_record(rt: Any, node: str, record: dict) -> dict[str, Any] | None:
    """Make the extraction of an accepted upload (services.graph_extract) and return its counts. A failure is returned,
    never raised: the upload is kept either way, and the extraction can be made again."""
    try:
        dp = datapoints_of(node).get(record["document"]["datapoint"].split(":", 1)[1], {})
        made = graph_extract.extract(rt, node, record, _extract_caller(rt, dp.get("sensitivity"), record.get("synthetic") is True))
        return graph_extract.summary(made)
    except Exception as exc:  # noqa: BLE001 - reported with the upload
        return {"failed": type(exc).__name__}


def _kind_caller(rt: Any, sensitivity: str | None):
    """The model caller for the kind step, bound to the item's sensitivity, or None when no model is configured."""
    orchestrator = getattr(rt, "orchestrator", None)
    backend = getattr(orchestrator, "backend", None)
    if backend is None:
        return None
    from services.context.llm import make_caller
    return make_caller(backend, app_env=getattr(orchestrator, "app_env", "development"), trace_id=f"upload-{uuid.uuid4().hex[:8]}",
                       sensitivities={sensitivity} if sensitivity else set(), all_synthetic=True, calls=[])


@_one_at_a_time
def add_upload(rt: Any, user: dict, node: str, code: str, kind: str, title: str, filename: str, data: bytes,
               tags: str | list[str] | None = None, version: str | None = None, build_vectors: bool = True,
               graph_id: str | None = None, graph_name: str | None = None, kind_label: str | None = None,
               new_item_title: str | None = None, new_item_area: str | None = None, synthetic: bool = False) -> dict[str, Any]:
    """Keep one uploaded file as a document of ``node``'s item ``code`` in a context graph, and rebuild the pack of its
    domain. Returns the record without the body, with the rebuild counts. Raises UploadRefused with the reason when
    nothing was kept. ``synthetic`` says the file is invented data. The record keeps it, and a file sent without it is
    real (the real data plan, step 1). The model gate does not read the mark yet."""
    if node not in node_ids():
        raise UploadRefused(f"{node} is not a registered company.")
    if kind not in KINDS and kind != AUTO_KIND:
        raise UploadRefused(f"{kind} is not a document kind. Kinds: {', '.join(KINDS)}, or {AUTO_KIND} to detect it.")
    kind_label = " ".join((kind_label or "").split())
    if kind == "other" and not 2 <= len(kind_label) <= KIND_LABEL_MAX:
        raise UploadRefused(f"Name the kind of the document, in 2 to {KIND_LABEL_MAX} characters.")
    new_item = bool(" ".join((new_item_title or "").split()))
    items = datapoints_of(node)
    if not new_item:
        if code not in items:
            raise UploadRefused(f"{node} has no catalogue item {code}.")
        if items[code]["ceiling"] == "LIVE":
            raise UploadRefused(f"{code} is a live item, answered from the company's own system. A document is not kept under it.")
    from services import upload_suggest
    text, fmt = extract_text(filename, data)
    title = " ".join((title or "").split()) or upload_suggest.title_of(filename, text, fmt)  # empty: the title the file gives itself
    version = (version or datetime.now(timezone.utc).strftime("%Y-%m")).strip()
    if not re.fullmatch(r"\d{4}-\d{2}", version):
        raise UploadRefused("The version is a month, written as YYYY-MM.")
    graph = _graph_for(graph_id, graph_name, title[:200])
    item_file: Path | None = None
    if new_item:  # named last, so that a refusal above leaves no item behind
        code, dp, item_file = _new_item(node, str(new_item_title), str(new_item_area or ""), user, synthetic)
    else:
        dp = items[code]
    detected = None
    if kind == AUTO_KIND:
        from services import upload_kind
        detected = upload_kind.detect(title[:200], Path(filename).name, text, KINDS, fmt=fmt, call_model=_kind_caller(rt, dp.get("sensitivity")))
        kind, kind_label = detected["kind"], detected["label"]
    doc_id = _next_id(node, code)
    document: dict[str, Any] = {"id": doc_id, "datapoint": f"{node}:{code}", "title": title[:200], "kind": kind, "version": version,
                                "tags": _tags(tags), "summary": summary_of(text), "body": text}
    if kind == "other":
        document["kind_label"] = kind_label
    matches = concepts_in(rt, text, document["tags"])
    if not document["tags"]:  # empty: the concepts the text names, in the order it names them
        document["tags"] = upload_suggest.tags_of(upload_suggest.ordered_concepts(rt, text, matches))
    if matches:
        document["concepts"] = list(matches)
    record = {"status": "accepted", "synthetic": bool(synthetic), "context_graph": graph, "document": document, "concept_matches": matches,
              **({"kind_detected": {"by": detected["by"], "reason": detected["reason"]}} if detected else {}),
              "upload": {"file": Path(filename).name, "format": fmt, "chars": len(text), "sha256": hashlib.sha256(data).hexdigest(),
                         "by_role": "Mesh admin", "by_company": str(user.get("company", "")), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}}
    path = _folder(node) / f"{doc_id.split(':', 1)[1]}.json"
    _write_atomic(path, record)
    try:
        built = packgen.rebuild_domain_pack(node, dp["domain"], build_vectors=build_vectors)
    except PackCheckFailed as exc:
        path.unlink(missing_ok=True)
        if item_file:
            item_file.unlink(missing_ok=True)
        _rebuild_without(node, dp["domain"], doc_id)
        raise UploadRefused(str(exc).removeprefix("Pack validation failed: ")) from exc
    except Exception:
        path.unlink(missing_ok=True)
        if item_file:
            item_file.unlink(missing_ok=True)
        _rebuild_without(node, dp["domain"], doc_id)
        raise
    return {**public(record, node), "rebuild": built, "extraction": extract_record(rt, node, record), **({"new_item": {"code": code, "title": dp["title"], "domain": dp["domain"]}} if item_file else {})}


def _rebuild_without(node: str, domain: str, doc_id: str) -> None:
    """After a failed upload whose record is gone: its index rows are deleted and the pack is built again without it,
    so that no document stays in the pack or the index without a record. The vectors are left to the next successful
    build, which drops any chunk that is no longer wanted."""
    try:
        connection = sqlite3.connect(packgen.DATA / node / "index.db")
        try:
            connection.execute("DELETE FROM idx WHERE doc_id = ? OR doc_id LIKE ?", (doc_id, doc_id + "#%"))
            connection.commit()
        finally:
            connection.close()
        packgen.rebuild_domain_pack(node, domain, build_vectors=False)
    except Exception:  # noqa: BLE001 - the error of the upload itself is the one reported
        pass


def suggest(rt: Any, filename: str, data: bytes, node: str | None = None, code: str | None = None) -> dict[str, Any]:
    """What the Add input form fills in from a file before the upload. Nothing is kept.

    Code proposes: the title, candidate concepts by words (full names and other names of the vocabulary) and by
    meaning (the vocabulary vectors), and the closest context graphs. One model call names the kind, confirms which
    candidates are main topics and picks a candidate graph or a new one, and code accepts only listed concepts and
    listed graphs. When the model may not see the item's sensitivity, is not configured or gives no usable reply, the
    code result stands: the kind by word rules, the strong word matches as concepts, the graph sharing 2 of them."""
    import hashlib
    from services import upload_kind, upload_suggest as us
    text, fmt = extract_text(filename, data)
    name = Path(filename).name
    title = us.title_of(filename, text, fmt)
    words = us.ordered_concepts(rt, text, concepts_in(rt, text))
    meaning = us.meaning_candidates(rt, text)
    label = lambda cid: str(rt.mesh.graph.nodes[cid].get("label") or cid) if cid in rt.mesh.graph else cid  # noqa: E731
    candidates = [{"id": c["id"], "label": c["label"], "strong": True, "found_by": "full name or a name of two or more words"} for c in words if c["strong"]]
    seen = {c["id"] for c in candidates}
    candidates += [{"id": cid, "label": label(cid), "strong": False, "found_by": f"meaning {score:.2f}"} for cid, score in meaning.items() if cid not in seen]
    seen |= set(meaning)
    candidates += [{"id": c["id"], "label": c["label"], "strong": False, "found_by": "a one-word name only"} for c in words if c["id"] not in seen]
    candidates = candidates[: us.MAX_CANDIDATES]
    records = _all_records()
    graphs = us.graph_candidates({c["id"] for c in candidates if c["strong"] or c["found_by"].startswith("meaning")}, title, summary_of(text), records, graph_ref)
    dp = datapoints_of(node).get(code or "", {}) if node in node_ids() else {}
    # an item that is not in the catalogue, a new one or none chosen yet, is read under the rule of a new item
    call = _kind_caller(rt, dp.get("sensitivity") or NEW_ITEM_RULE["sensitivity"])
    key = hashlib.sha256(data).hexdigest() + "|" + ",".join(c["id"] for c in candidates) + "|" + ",".join(g["id"] for g in graphs)
    model = us.confirm(call, name, title, text, candidates, graphs, KINDS, label, key)
    strong = [c["id"] for c in candidates if c["strong"]]
    if model:
        confirmed = model["concepts"]
        kind = {"kind": model["kind"], "label": model["label"], "by": "model", "reason": model["reason"]}
        if model["graph"] == "new":
            graph = us.graph_for(set(), model["new_graph_name"] or title, records, graph_ref)  # a new graph, unless one of that name exists
        else:
            g = next(g for g in graphs if g["id"] == model["graph"])
            graph = {"mode": "append", "id": g["id"], "name": g["name"], "shared": sorted(g["concepts"] & set(confirmed)), "reason": model["reason"]}
    else:
        confirmed = strong
        kind = upload_kind.by_rules(title, name, text, fmt)
        graph = us.graph_for(set(strong), title, records, graph_ref)
    order = {c["id"]: i for i, c in enumerate(candidates)}
    confirmed = sorted(set(confirmed), key=lambda c: order.get(c, 99))
    concepts = [{"id": c, "label": label(c)} for c in confirmed]
    return {"title": title, "tags": [packgen._tag(c["label"]) for c in concepts][: us.MAX_TAGS], "kind": kind, "concepts": concepts,
            "graph": graph, "decided_by": "model" if model else "code", "candidates": candidates,
            "graph_candidates": [{"id": g["id"], "name": g["name"], "closeness": g["closeness"]} for g in graphs], "format": fmt, "chars": len(text)}


def company_label(node: str | None) -> str:
    """The name of a company as the screens print it. An id that is no node is printed as it is."""
    return registered_node(node).display if node in node_ids() else str(node or "")


def public(record: dict, node: str) -> dict[str, Any]:
    """The record as the screens show it: everything but the body text, plus the company name and the context graph."""
    doc = {k: v for k, v in record["document"].items() if k != "body"}
    return {"node_id": node, "company": registered_node(node).display, "status": record["status"], "synthetic": record.get("synthetic") is True,
            "context_graph": graph_ref(record),
            "document": doc, "upload": {**record["upload"], "by_company_name": company_label(record["upload"].get("by_company"))}, "concept_matches": record.get("concept_matches", {}),
            **({"kind_detected": record["kind_detected"]} if record.get("kind_detected") else {}),
            "extraction": graph_extract.summary(graph_extract.read(record["document"]["id"])),
            "sharing": {"ceiling": None, "never_leave": False, "shared": is_shared(node)}}


def list_uploads(rt: Any, company: str, roles: list[str]) -> list[dict[str, Any]]:
    """Every upload a person may see: all of them for a mesh admin, the own company's and the shared node's for anyone
    else. Each says whether its document is in the central graph now and which sharing rule its item applies."""
    out = []
    g = rt.mesh.graph
    for node in node_ids():
        shared = is_shared(node)
        if "mesh_admin" not in roles and node != company and not shared:
            continue
        items = datapoints_of(node)
        for status in ("accepted", "removed"):
            for record in packgen.contributions_of(node, status):
                item = public(record, node)
                item["removed"] = record.get("removed")
                dp = items.get(record["document"]["datapoint"].split(":", 1)[1], {})
                item["sharing"] = {"ceiling": dp.get("ceiling"), "never_leave": bool(dp.get("never_leave")), "item_title": dp.get("title"), "shared": shared}
                item["in_graph"] = record["document"]["id"] in g and not g.nodes[record["document"]["id"]].get("retired")
                out.append(item)
    out.sort(key=lambda r: r["upload"]["at"], reverse=True)
    return out


def _around(rt: Any, doc_id: str, company: str, roles: list[str]) -> set[str]:
    """The document, its item and company, and every entity one link away that the caller may see."""
    g = rt.mesh.graph
    keep = {doc_id}
    for a, b, d in list(g.out_edges(doc_id, data=True)) + list(g.in_edges(doc_id, data=True)):
        other = b if a == doc_id else a
        if d["status"] != "retired" and not g.nodes[other].get("retired") and rt.mesh.shown_to(other, company, roles):
            keep.add(other)
    datapoint = g.nodes[doc_id].get("datapoint")
    if datapoint in g:
        keep.add(datapoint)
        sub = g.nodes[datapoint].get("subsidiary")
        if sub and f"org:{sub}" in g:
            keep.add(f"org:{sub}")
    return keep


def _view(rt: Any, keep: set[str]) -> dict[str, Any]:
    g = rt.mesh.graph
    nodes = [{"id": n, "type": g.nodes[n].get("type"), "label": g.nodes[n].get("label") or n, "subsidiary": g.nodes[n].get("subsidiary")} for n in sorted(keep)]
    edges = [{"id": d["id"], "type": d["type"], "source": a, "target": b, "status": d["status"]}
             for a, b, d in g.edges(data=True) if a in keep and b in keep and d["status"] != "retired"]
    counts: dict[str, int] = {}
    for n in nodes:
        counts[n["type"]] = counts.get(n["type"], 0) + 1
    return {"nodes": nodes, "edges": edges, "counts": counts}


def _visible(rt: Any, doc_id: str, company: str, roles: list[str]) -> bool:
    g = rt.mesh.graph
    return doc_id in g and not g.nodes[doc_id].get("retired") and rt.mesh.shown_to(doc_id, company, roles)


def graph_of(rt: Any, doc_id: str, company: str, roles: list[str]) -> dict[str, Any]:
    """The part of the central graph around one uploaded document."""
    if not _visible(rt, doc_id, company, roles):
        raise KeyError(doc_id)
    return {**_view(rt, _around(rt, doc_id, company, roles)), "centre": doc_id}


def context_graph_view(rt: Any, graph_id: str, company: str, roles: list[str]) -> dict[str, Any]:
    """One context graph: every input in it that the caller may see, with the items, the companies and the entities one
    link away from any of them, and the links among all of these. A concept two inputs share appears once."""
    records = [(node, r) for node, r in _all_records() if graph_ref(r)["id"] == graph_id]
    if not records:
        raise KeyError(graph_id)
    documents = [r["document"]["id"] for _, r in records if _visible(rt, r["document"]["id"], company, roles)]
    if not documents:
        raise KeyError(graph_id)
    keep: set[str] = set()
    for doc_id in documents:
        keep |= _around(rt, doc_id, company, roles)
    shown = [(node, r) for node, r in records if r["document"]["id"] in documents]
    view = _with_extractions(_view(rt, keep), shown, company, roles)
    return {"id": graph_id, "name": graph_ref(records[0][1])["name"], "documents": documents, **view, "quality": graph_quality(shown, view)}


def _may_read_text(node: str, record: dict, company: str, roles: list[str]) -> bool:
    """Whether the person may read what the text of the record says: the rule of pack_documents for the whole text."""
    if "mesh_admin" in roles or node == company or is_shared(node):
        return True
    dp = datapoints_of(node).get(record["document"]["datapoint"].split(":", 1)[1], {})
    return not dp.get("never_leave") and dp.get("ceiling") == "RAG"


def _with_extractions(view: dict[str, Any], records: list[tuple[str, dict]], company: str, roles: list[str]) -> dict[str, Any]:
    """The view with the entities and the links taken from the text of each input the person may read, proposed and
    approved. A rejected link is left out, and so is a link whose end the view does not show."""
    ids = {n["id"] for n in view["nodes"]}
    for node, record in records:
        data = graph_extract.read(record["document"]["id"])
        if not data or not _may_read_text(node, record, company, roles):
            continue
        entities = {e["id"]: e for e in data.get("entities", [])}
        for link in data.get("links", []):
            ends = (link["source"], link["target"])
            if link["status"] == "rejected" or not all(x in ids or x in entities for x in ends):
                continue
            for end in ends:
                if end not in ids:
                    e = entities[end]
                    view["nodes"].append({"id": end, "type": e["type"], "label": e["name"], "subsidiary": node})
                    view["counts"][e["type"]] = view["counts"].get(e["type"], 0) + 1
                    ids.add(end)
            view["edges"].append({"id": link["id"], "type": link["type"], "source": link["source"], "target": link["target"], "status": link["status"],
                                  "evidence": link["evidence"], "by": link["by"], "document": record["document"]["id"]})
    return view


NEAR_COPY = 0.85  # the share of words two inputs have in common above which one is taken as a copy of the other


def graph_quality(records: list[tuple[str, dict]], view: dict[str, Any]) -> list[dict[str, str]]:
    """Points to look at in a context graph made by Upload input, from the inputs the person sees: an input linked to no
    known concept, two inputs with the same file or nearly the same text, an input that shares no concept with the
    others, and the links taken from the text that wait for review. One "ok" line when there is none."""
    docs = [r for _, r in records]
    title = lambda r: f'"{r["document"]["title"]}"'  # noqa: E731
    notes: list[dict[str, str]] = []
    bare = [title(r) for r in docs if not r["document"].get("concepts")]
    if bare:
        notes.append({"level": "warn", "text": f"{len(bare)} {'input links' if len(bare) == 1 else 'inputs link'} to no known concept, so nothing joins {'it' if len(bare) == 1 else 'them'} to the rest of the mesh: {', '.join(bare)}"})
    words = [(r, set(norm_tokens(r["document"].get("body") or ""))) for r in docs]
    for i, (a, wa) in enumerate(words):
        for b, wb in words[i + 1:]:
            if a["upload"].get("sha256") and a["upload"].get("sha256") == b["upload"].get("sha256"):
                notes.append({"level": "warn", "text": f"{title(a)} and {title(b)} are the same file"})
            elif len(wa) >= 20 and len(wb) >= 20 and len(wa & wb) / len(wa | wb) >= NEAR_COPY:
                notes.append({"level": "warn", "text": f"{title(a)} and {title(b)} have nearly the same text"})
    if len(docs) >= 2:
        alone = [title(r) for r in docs if r["document"].get("concepts")
                 and not set(r["document"]["concepts"]) & {c for o in docs if o is not r for c in o["document"].get("concepts") or []}]
        if alone:
            notes.append({"level": "note", "text": f"Shares no concept with the other inputs of the graph: {', '.join(alone)}"})
    waiting = sum(1 for e in view["edges"] if e.get("status") == "proposed" and e.get("by"))
    if waiting:
        notes.append({"level": "note", "text": f"{waiting} {'link' if waiting == 1 else 'links'} found in the text {'waits' if waiting == 1 else 'wait'} for review"})
    return notes or [{"level": "ok", "text": "Every input links to a known concept, and no input repeats another"}]


def pack_documents(records: list[dict], company: str, roles: list[str]) -> list[dict[str, Any]]:
    """The documents of the records as a knowledge pack may carry them to this person: whole for a mesh admin, for the
    own company and for the shared node, otherwise what the item's ceiling releases: the text of a full-text item, the
    summary of a summary item, the title alone of a title-only item."""
    out = []
    for record in records:
        doc = dict(record["document"])
        node = doc["id"].split(":", 1)[0]
        if "mesh_admin" in roles or node == company or is_shared(node):
            out.append(doc)
            continue
        dp = datapoints_of(node).get(doc["datapoint"].split(":", 1)[1], {})
        if dp.get("never_leave") or dp.get("ceiling") not in ("SUM", "RAG"):
            doc.pop("body", None)
            doc.pop("summary", None)
        elif dp.get("ceiling") == "SUM":
            doc.pop("body", None)
        out.append(doc)
    return out


def export(view: dict[str, Any], fmt: str, documents: list[dict] | None = None) -> tuple[str, str, str]:
    """The graph part in one of the formats: (content, media type, file extension). The pack format carries
    ``documents``, the output of pack_documents."""
    if fmt == "json":
        return json.dumps({"nodes": view["nodes"], "edges": view["edges"]}, indent=2, ensure_ascii=False), "application/json", "json"
    if fmt == "csv":
        lines = ["kind,id,type,label,subsidiary,source,target,status"]
        for n in view["nodes"]:
            lines.append(",".join(_csv(x) for x in ("node", n["id"], n["type"], n["label"], n.get("subsidiary") or "", "", "", "")))
        for e in view["edges"]:
            lines.append(",".join(_csv(x) for x in ("edge", e["id"], e["type"], "", "", e["source"], e["target"], e["status"])))
        return "\n".join(lines) + "\n", "text/csv", "csv"
    if fmt == "graphml":
        from xml.sax.saxutils import escape
        out = ['<?xml version="1.0" encoding="UTF-8"?>',
               '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
               '  <key id="type" for="all" attr.name="type" attr.type="string"/>',
               '  <key id="label" for="node" attr.name="label" attr.type="string"/>',
               '  <key id="subsidiary" for="node" attr.name="subsidiary" attr.type="string"/>',
               '  <key id="status" for="edge" attr.name="status" attr.type="string"/>',
               '  <graph id="neuralmesh" edgedefault="directed">']
        for n in view["nodes"]:
            out.append(f'    <node id="{escape(n["id"], {chr(34): "&quot;"})}"><data key="type">{escape(str(n["type"]))}</data>'
                       f'<data key="label">{escape(n["label"])}</data><data key="subsidiary">{escape(n.get("subsidiary") or "")}</data></node>')
        for e in view["edges"]:
            out.append(f'    <edge id="{escape(e["id"], {chr(34): "&quot;"})}" source="{escape(e["source"], {chr(34): "&quot;"})}" '
                       f'target="{escape(e["target"], {chr(34): "&quot;"})}"><data key="type">{escape(e["type"])}</data>'
                       f'<data key="status">{escape(e["status"])}</data></edge>')
        out += ["  </graph>", "</graphml>"]
        return "\n".join(out) + "\n", "application/xml", "graphml"
    if fmt in export_formats.templates():
        return export_formats.render(fmt, view, lambda s: company_label(s) if s else "")
    if fmt == "pack":
        if not documents:
            raise KeyError("pack")
        return json.dumps({**packgen.FORMAT, "documents": documents}, indent=2, ensure_ascii=False), "application/json", "pack.json"
    raise KeyError(fmt)


def file_name(text: str) -> str:
    """A name as a file name: letters, digits and underscores."""
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_") or "graph"


def _csv(value: Any) -> str:
    text = str(value)
    return '"' + text.replace('"', '""') + '"' if any(c in text for c in ',"\n') else text


def record_of(node: str, doc_id: str) -> dict | None:
    for status in ("accepted", "rejected", "removed"):
        for record in packgen.contributions_of(node, status):
            if record["document"]["id"] == doc_id:
                return record
    return None


def _mark_removed(node: str, record: dict, user: dict) -> None:
    """The record stays with status "removed", who removed it and when, so the upload history is complete."""
    record["status"] = "removed"
    record["removed"] = {"by_role": "Mesh admin", "by_company": str(user.get("company", "")), "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    _write_atomic(_folder(node) / f"{record['document']['id'].split(':', 1)[1]}.json", record)


def _domain_of_record(node: str, record: dict) -> str | None:
    return datapoints_of(node).get(record["document"]["datapoint"].split(":", 1)[1], {}).get("domain")


@_one_at_a_time
def remove_upload(node: str, doc_id: str, user: dict, build_vectors: bool = True) -> dict[str, Any]:
    """Take one uploaded document out of the pack, the index and the export. Raises KeyError when there is no such upload."""
    record = record_of(node, doc_id)
    if record is None:
        raise KeyError(doc_id)
    _mark_removed(node, record, user)
    domain = _domain_of_record(node, record)
    if domain:
        packgen.rebuild_domain_pack(node, domain, build_vectors=build_vectors)
    return public(record, node)


@_one_at_a_time
def drop_graph(graph_id: str, user: dict, build_vectors: bool = True) -> dict[str, Any]:
    """Take every input of a context graph out of the packs, the indexes and the export, with one rebuild per pack. Each
    record stays, marked removed. A pack whose rebuild fails is named in ``failed`` and the other packs are still
    rebuilt. A second drop of the same graph removes nothing more and rebuilds its packs again, which repairs a failed
    one. Raises KeyError when no record carries the graph id."""
    accepted = [(node, r) for node, r in _all_records() if graph_ref(r)["id"] == graph_id]
    removed_before = [(node, r) for node, r in _all_records(("removed",)) if graph_ref(r)["id"] == graph_id]
    if not accepted and not removed_before:
        raise KeyError(graph_id)
    removed = []
    for node, record in accepted:
        _mark_removed(node, record, user)
        removed.append(public(record, node))
    packs = {(node, domain) for node, record in accepted + removed_before if (domain := _domain_of_record(node, record))}
    rebuilt, failed = [], {}
    for node, domain in sorted(packs):
        try:
            packgen.rebuild_domain_pack(node, domain, build_vectors=build_vectors)
            rebuilt.append(f"{node}.{domain}")
        except Exception as exc:  # noqa: BLE001 - the other packs are still rebuilt, and the failure is reported
            failed[f"{node}.{domain}"] = str(exc).removeprefix("Pack validation failed: ") or type(exc).__name__
    return {"graph": graph_ref((accepted or removed_before)[0][1]), "removed": removed, "rebuilt": rebuilt, "failed": failed}
