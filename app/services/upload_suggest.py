"""What the Add input form can fill in from a file before it is uploaded: the title, the tags, the kind, the concepts it
names and the context graph it fits. Nothing is kept: the file is read, compared with the graphs that exist, and
forgotten. The same title and tag rules apply when an upload leaves those fields empty."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

APPEND_AT = 2  # shared concepts needed to suggest appending to an existing graph rather than opening a new one
MAX_TAGS = 6
TITLE_MAX = 120


MONTHS = {m: m.capitalize() for m in ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "sept", "oct", "nov", "dec")}


def title_from_name(filename: str) -> str:
    """A readable title from a file name: no extension, no leading number, words for underscores and dashes, a
    company id written as the company's name, month abbreviations and quarters (q3) written with capitals."""
    from shared.registry import node as registered_node, node_ids
    stem = re.sub(r"^\d+[\s_-]+", "", Path(filename).stem)
    words = []
    for w in stem.replace("_", " ").replace("-", " ").split():
        low = w.lower()
        if low in node_ids():
            words.append(registered_node(low).display)
        elif low in MONTHS:
            words.append(MONTHS[low])
        elif re.fullmatch(r"q[1-4]", low):
            words.append(low.upper())
        else:
            words.append(w)
    text = " ".join(words)
    return (text[:1].upper() + text[1:]) or "Untitled"


def title_of(filename: str, text: str, fmt: str) -> str:
    """The title the document gives itself: a title or name field of a JSON file, otherwise the first line when it reads
    like a heading (3 to 120 characters, not a sentence of more than 15 words, not a row of a table). A table or a
    file without such a line takes its file name."""
    if fmt == "json":
        try:
            parsed = json.loads(text) if text.lstrip().startswith(("{", "[")) else None
        except ValueError:
            parsed = None
        first = text.split("\n", 1)[0]
        m = re.match(r"(?i)\s*(title|name|report|subject)\s*:\s*(.+)", first)
        if isinstance(parsed, dict) and isinstance(parsed.get("title") or parsed.get("name"), str):
            return str(parsed.get("title") or parsed.get("name"))[:TITLE_MAX]
        if m:
            return m.group(2).strip()[:TITLE_MAX]
        return title_from_name(filename)
    if fmt == "csv":
        return title_from_name(filename)
    for line in text.split("\n"):
        line = " ".join(line.split()).strip(" #*|")
        if not line:
            continue
        sentence = line.endswith(".") and len(line.split()) > 15
        if 3 <= len(line) <= TITLE_MAX and not sentence and line.count(",") < 4 and re.search(r"[A-Za-z]{3}", line):
            return line
        break
    return title_from_name(filename)


def strong_names(data: dict) -> list[str]:
    """The names of a concept that are specific enough to decide tags and the graph: its full name, and every other
    name of at least two words. A one-word other name such as "checklist" or "claims" still links the document to the
    concept, but is too common to say what the document is about."""
    from services.uploads import norm_tokens
    names = [data.get("label") or ""] + [a for a in (data.get("aliases") or []) if len(norm_tokens(a)) >= 2]
    return [n for n in names if norm_tokens(n)]


def ordered_concepts(rt: Any, text: str, matches: dict[str, str]) -> list[dict[str, Any]]:
    """The concepts found, each marked strong when its full name or an other name of two or more words appears in the
    text as a phrase. Strong ones first, each group in the order the text first names them."""
    from services.uploads import _phrase_in, norm_tokens
    tokens = norm_tokens(text)
    lower = text.lower()
    out = []
    for cid, how in matches.items():
        data = rt.mesh.graph.nodes[cid] if cid in rt.mesh.graph else {}
        label = str(data.get("label") or cid)
        hits = [n for n in strong_names(data) if _phrase_in(norm_tokens(n), tokens)] if data else []
        at = min([lower.find(n.lower()) for n in hits if lower.find(n.lower()) >= 0] or [len(lower)])
        out.append({"id": cid, "label": label, "how": how, "strong": bool(hits), "_at": at})
    out.sort(key=lambda c: (not c["strong"], c["_at"], c["label"]))
    return [{k: v for k, v in c.items() if k != "_at"} for c in out]


def tags_of(concepts: list[dict[str, Any]]) -> list[str]:
    """The tags of a document: its strong concepts, in the order the text names them."""
    from knowledge import packgen
    return [packgen._tag(c["label"]) for c in concepts if c.get("strong")][:MAX_TAGS]


def graph_for(concept_ids: set[str], title: str, records: list[tuple[str, dict]], graph_ref) -> dict[str, Any]:
    """The existing context graph that shares the most of the file's strong concepts (``concept_ids``), when it shares
    at least APPEND_AT, or a new graph named after the title. A graph of the same name is suggested for appending, since two graphs may not
    share a name."""
    graphs: dict[str, dict[str, Any]] = {}
    for _, record in records:
        ref = graph_ref(record)
        g = graphs.setdefault(ref["id"], {"id": ref["id"], "name": ref["name"], "concepts": set(), "latest": ""})
        g["concepts"] |= set(record.get("concept_matches") or {})
        g["latest"] = max(g["latest"], record["upload"]["at"])
    ranked = sorted(graphs.values(), key=lambda g: (len(g["concepts"] & concept_ids), g["latest"]), reverse=True)
    best = ranked[0] if ranked else None
    if best and len(best["concepts"] & concept_ids) >= APPEND_AT:
        return {"mode": "append", "id": best["id"], "name": best["name"], "shared": sorted(best["concepts"] & concept_ids),
                "reason": f"shares {len(best['concepts'] & concept_ids)} of the file's main concepts with it"}
    name = " ".join(title.split())[:80]
    same = next((g for g in graphs.values() if g["name"].casefold() == name.casefold()), None)
    if same:
        return {"mode": "append", "id": same["id"], "name": same["name"], "shared": sorted(same["concepts"] & concept_ids),
                "reason": "a graph of the same name exists"}
    return {"mode": "new", "id": None, "name": name, "shared": [],
            "reason": f"no graph shares {APPEND_AT} or more of the file's main concepts" if graphs else "there is no graph yet"}


# ── code proposes, the model confirms ───────────────────────────────────────
MEANING_TOP = 8          # concepts proposed by meaning, from the vocabulary vectors
MEANING_MIN = 0.30       # lower than the 0.45 of a question: a document says more, and the model confirms every candidate
MAX_CANDIDATES = 15      # concepts shown to the model
GRAPH_CANDIDATES = 5     # graphs shown to the model
FIRST_CHARS = 1200       # the part of the text the model reads
_CACHE: dict[str, dict[str, Any]] = {}


def meaning_candidates(rt: Any, text: str) -> dict[str, float]:
    """Concepts close in meaning to the opening of the text, from the vocabulary vectors the graph search uses."""
    from knowledge import embedder
    mesh = rt.mesh
    lock = getattr(mesh, "_lock", None)
    ids, vectors = getattr(mesh, "_vocab_ids", None), getattr(mesh, "_vocab_vectors", None)
    if lock is not None:
        with lock:
            ids, vectors = mesh._vocab_ids, mesh._vocab_vectors
    if vectors is None or not ids or not embedder.available():
        return {}
    q = embedder.embed([" ".join(text[:FIRST_CHARS].split())])[0]
    scores = vectors @ q
    out: dict[str, float] = {}
    for i in scores.argsort()[::-1][: MEANING_TOP * 3]:
        cid = ids[int(i)]
        if scores[i] >= MEANING_MIN and mesh.graph.nodes.get(cid, {}).get("type") == "Concept" and len(out) < MEANING_TOP:
            out[cid] = round(float(scores[i]), 2)
    return out


def graph_candidates(concept_ids: set[str], title: str, summary: str, records: list[tuple[str, dict]], graph_ref) -> list[dict[str, Any]]:
    """The graphs closest to the file: by shared candidate concepts, then by how close the graph's input titles are in
    meaning to the file's title and opening. At most GRAPH_CANDIDATES."""
    graphs: dict[str, dict[str, Any]] = {}
    for _, record in records:
        ref = graph_ref(record)
        g = graphs.setdefault(ref["id"], {"id": ref["id"], "name": ref["name"], "concepts": set(), "inputs": [], "latest": ""})
        g["concepts"] |= set(record.get("concept_matches") or {})
        g["inputs"].append(record["document"]["title"])
        g["latest"] = max(g["latest"], record["upload"]["at"])
    if not graphs:
        return []
    closeness: dict[str, float] = {}
    try:
        from knowledge import embedder
        if embedder.available():
            vecs = embedder.embed([f"{title}. {summary}"] + [f"{g['name']}. " + ". ".join(g["inputs"][:6]) for g in graphs.values()])
            for g, v in zip(graphs.values(), vecs[1:]):
                closeness[g["id"]] = float(v @ vecs[0])
    except Exception:  # noqa: BLE001 - without the embedding model the shared concepts rank alone
        pass
    ranked = sorted(graphs.values(), key=lambda g: (len(g["concepts"] & concept_ids), closeness.get(g["id"], 0.0), g["latest"]), reverse=True)
    return [{**g, "closeness": round(closeness.get(g["id"], 0.0), 2)} for g in ranked[:GRAPH_CANDIDATES]]


def map_prompt(filename: str, title: str, text: str, candidates: list[dict[str, Any]], graphs: list[dict[str, Any]], label) -> str:
    lines = [f"File name: {filename}", f"Title: {title}", "", "First lines:", text[:FIRST_CHARS], "", "Candidate concepts (id | name | found by):"]
    lines += [f"- {c['id']} | {c['label']} | {c['found_by']}" for c in candidates] or ["- none"]
    lines += ["", "Candidate graphs (id | name | its concepts | its inputs):"]
    lines += [f"- {g['id']} | {g['name']} | {', '.join(sorted(label(c) for c in g['concepts']))[:300]} | {'; '.join(g['inputs'][:5])[:300]}" for g in graphs] or ["- none"]
    return "\n".join(lines)


def last_json_object(reply: str) -> dict | None:
    """The last complete JSON object with a "kind" in a reply. Text around it, or an earlier answer the model corrected
    in the same reply, is left out."""
    decoder, found, i = json.JSONDecoder(), None, reply.find("{")
    while i != -1:
        try:
            value, end = decoder.raw_decode(reply, i)
            if isinstance(value, dict) and "kind" in value:
                found = value
            i = reply.find("{", end)
        except ValueError:
            i = reply.find("{", i + 1)
    return found


def confirm(call_model, filename: str, title: str, text: str, candidates: list[dict[str, Any]], graphs: list[dict[str, Any]],
            kinds: list[str], label, cache_key: str) -> dict[str, Any] | None:
    """One model call that names the kind, confirms concepts and picks a graph. Code checks the reply: only listed
    concepts and listed graphs count. Returns None when the model is not used or its reply cannot be used."""
    if call_model is None:
        return None
    if cache_key in _CACHE:
        return {**_CACHE[cache_key], "cached": True}
    from services.context import prompts
    try:
        prompt = prompts.load("map")
        reply = call_model("map", prompt.text, map_prompt(filename, title, text, candidates, graphs, label), prompt.version)
    except Exception:  # noqa: BLE001 - a step missing from the model policy, or a failed call: the code result stands
        return None
    if not reply:
        return None
    parsed = last_json_object(reply)
    if parsed is None:
        return None
    allowed_concepts = {c["id"] for c in candidates}
    allowed_graphs = {g["id"] for g in graphs}
    kind = str(parsed.get("kind", "")).strip()
    graph = str(parsed.get("graph", "")).strip()
    listed = parsed.get("concepts")
    if listed is not None and not isinstance(listed, list):
        return None  # the concepts are not given as a list: the reply cannot be used
    concepts = [c for c in listed or [] if isinstance(c, str) and c in allowed_concepts]
    if kind not in kinds or (graph != "new" and graph not in allowed_graphs):
        return None
    out = {"kind": kind, "label": " ".join(str(parsed.get("label") or "").split())[:60] if kind == "other" else "",
           "concepts": concepts, "graph": graph, "new_graph_name": " ".join(str(parsed.get("new_graph_name") or "").split())[:80],
           "reason": str(parsed.get("reason") or "")[:200]}
    if kind == "other" and len(out["label"]) < 2:
        return None
    if len(_CACHE) > 256:
        _CACHE.clear()
    _CACHE[cache_key] = out
    return out
