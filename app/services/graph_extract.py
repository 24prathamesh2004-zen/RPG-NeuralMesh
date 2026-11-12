"""Entities and links taken from the text of an uploaded document, beside the links the upload already made.

An upload links its document to the concepts of the group vocabulary the text names (services.uploads.concepts_in). That
gives document to concept links only. This step adds what the text says between them, in two parts:

- By code, always: two known concepts named in the same sentence get a RELATED_TO link, with that sentence as evidence.
- By the model, when the model policy allows it for the item's sensitivity and the upload's real or invented mark: new
  entities (a machine, a part, a supplier) and named links between them and the known concepts. Code keeps an entity only
  when its name is in the text, and a link only when its evidence sentence is in the text and names both ends. A real
  upload gets no cloud model, so it gets the code part only.

Every link starts as "proposed". A mesh admin or a person of the owning company approves or rejects it. Nothing here
changes the upload record, the pack, the indexes or the links the upload made: the result is one file per document in
the node's ``extractions`` folder, read by the context graph view (services.uploads) and shown as proposed or approved
links. A new entity's id carries its company, so the same name in two companies stays two entities.
"""
from __future__ import annotations

import json
import os
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from knowledge import packgen
from services.mesh_graph import _phrase_in, norm_tokens

FOLDER = "extractions"
STATUSES = ("proposed", "approved", "rejected")
EVIDENCE_MAX = 300  # characters of the sentence kept as evidence
CODE_LINKS_MAX = 40
MODEL_TEXT_CHARS = 6_000  # the part of the text the model reads
ENTITIES_MAX = 30
MODEL_LINKS_MAX = 40
NAME_MAX = 80
TYPE_MAX = 30
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}|\n(?=[-*•\d])")


def folder(node: str) -> Path:
    return packgen.DATA / node / FOLDER


def _path(doc_id: str) -> Path:
    node, local = doc_id.split(":", 1)
    return folder(node) / f"{local}.json"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _line(text: str) -> str:
    return " ".join(str(text).split())


def sentences(text: str) -> list[str]:
    return [s for s in (_line(x) for x in SENTENCE.split(text or "")) if len(s) >= 12]


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60]


def _names(rt: Any, concept_ids: list[str]) -> dict[str, list[list[str]]]:
    """The known concepts of the document with their names as token lists."""
    g = rt.mesh.graph
    out = {}
    for cid in concept_ids:
        if cid in g:
            d = g.nodes[cid]
            names = [norm_tokens(x) for x in [d.get("label") or "", *(d.get("aliases") or [])]]
            out[cid] = [x for x in names if x]
    return out


def code_links(rt: Any, text: str, concept_ids: list[str]) -> list[dict[str, Any]]:
    """RELATED_TO between two known concepts named in the same sentence, the first such sentence as evidence."""
    names = _names(rt, concept_ids)
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for sentence in sentences(text):
        tokens = norm_tokens(sentence)
        here = sorted(cid for cid, phrases in names.items() if any(_phrase_in(p, tokens) for p in phrases))
        for i, a in enumerate(here):
            for b in here[i + 1:]:
                link = found.setdefault((a, b), {"source": a, "target": b, "type": "RELATED_TO", "evidence": sentence[:EVIDENCE_MAX],
                                                 "by": "code", "sentences": 0})
                link["sentences"] += 1
    links = sorted(found.values(), key=lambda x: -x["sentences"])
    return links[:CODE_LINKS_MAX]


def _parse(reply: str | None) -> dict[str, Any] | None:
    if not reply:
        return None
    cleaned = reply.strip().strip("`")
    cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    try:
        data = json.loads(cleaned[cleaned.find("{"): cleaned.rfind("}") + 1])
    except ValueError:
        return None
    return data if isinstance(data, dict) else None


def model_part(rt: Any, node: str, text: str, concept_ids: list[str], call_model: Callable | None) -> tuple[list[dict], list[dict], str]:
    """(entities, links, note). The model proposes, code keeps only what the text holds."""
    if call_model is None:
        return [], [], "no model"
    from services.context import prompts
    g = rt.mesh.graph
    known = {cid: g.nodes[cid].get("label") or cid for cid in concept_ids if cid in g}
    prompt = prompts.load("extract")
    user = "Known concepts:\n" + "\n".join(f"- {label}" for label in known.values()) + f"\n\nText:\n{text[:MODEL_TEXT_CHARS]}"
    data = _parse(call_model("extract", prompt.text, user, prompt.version))
    if data is None:
        return [], [], "the model was not asked or gave no usable reply"
    flat = _line(text).casefold()
    by_name: dict[str, str] = {label.casefold(): cid for cid, label in known.items()}
    entities: dict[str, dict[str, Any]] = {}
    for item in data.get("entities") or []:
        if not isinstance(item, dict):
            continue
        name = _line(item.get("name") or "")[:NAME_MAX]
        kind = _line(item.get("type") or "Entity")[:TYPE_MAX] or "Entity"
        if len(name) < 2 or name.casefold() not in flat or name.casefold() in by_name or not _slug(name):
            continue  # not in the text, or a known concept, which keeps its own id
        eid = f"entity:{node}:{_slug(name)}"
        entities.setdefault(eid, {"id": eid, "type": kind[:1].upper() + kind[1:], "name": name, "by": "model"})
        by_name[name.casefold()] = eid
        if len(entities) >= ENTITIES_MAX:
            break
    links: list[dict[str, Any]] = []
    seen = set()
    for item in data.get("links") or []:
        if not isinstance(item, dict):
            continue
        src, dst = _line(item.get("source") or ""), _line(item.get("target") or "")
        evidence = _line(item.get("evidence") or "")
        relation = re.sub(r"[^A-Z0-9]+", "_", str(item.get("relation") or "").upper()).strip("_")[:40]
        a, b = by_name.get(src.casefold()), by_name.get(dst.casefold())
        if not (a and b and a != b and len(relation) >= 3 and evidence and evidence.casefold() in flat
                and src.casefold() in evidence.casefold() and dst.casefold() in evidence.casefold()):
            continue  # an end that is not an entity, or evidence that is not in the text or does not name both ends
        if (a, relation, b) in seen:
            continue
        seen.add((a, relation, b))
        links.append({"source": a, "target": b, "type": relation, "evidence": evidence[:EVIDENCE_MAX], "by": "model"})
        if len(links) >= MODEL_LINKS_MAX:
            break
    used = {x for link in links for x in (link["source"], link["target"])}
    return [e for e in entities.values() if e["id"] in used], links, "made"


def extract(rt: Any, node: str, record: dict[str, Any], call_model: Callable | None = None) -> dict[str, Any]:
    """Make and keep the extraction of one accepted upload. Links of an earlier extraction keep their decision."""
    document = record["document"]
    text = document.get("body") or ""
    concepts = list(document.get("concepts") or [])
    entities, model_links, note = model_part(rt, node, text, concepts, call_model)
    before = {(link["source"], link["type"], link["target"]): link for link in (read(document["id"]) or {}).get("links", [])}
    links = []
    for link in [*code_links(rt, text, concepts), *model_links]:
        old = before.get((link["source"], link["type"], link["target"]))
        links.append({"id": old["id"] if old else f"x-{uuid.uuid4().hex[:10]}", **link,
                      "status": old["status"] if old else "proposed", **({"decided": old["decided"]} if old and old.get("decided") else {})})
    out = {"document": document["id"], "made": _now(), "model": note, "entities": entities, "links": links}
    path = _path(document["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return out


def read(doc_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_path(doc_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        return None


def summary(extraction: dict[str, Any] | None) -> dict[str, Any] | None:
    if not extraction:
        return None
    links = extraction.get("links", [])
    return {"entities": len(extraction.get("entities", [])), "links": len(links),
            "proposed": sum(1 for x in links if x["status"] == "proposed"), "model": extraction.get("model")}


def decide(doc_id: str, link_id: str, status: str, user: dict[str, Any]) -> dict[str, Any]:
    """Set a link to approved or rejected. KeyError when the document or the link has no extraction."""
    if status not in ("approved", "rejected"):
        raise ValueError("status is approved or rejected")
    data = read(doc_id)
    link = next((x for x in (data or {}).get("links", []) if x["id"] == link_id), None)
    if data is None or link is None:
        raise KeyError(link_id)
    link["status"] = status
    link["decided"] = {"at": _now(), "by_company": str(user.get("company") or ""),
                       "by_role": "Mesh admin" if "mesh_admin" in (user.get("roles") or []) else "User"}
    path = _path(doc_id)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)
    return link
