"""What a context graph is about, in a few lines, and the graphs a question is about.

Every context graph has a description. A graph ingested as JSON carries the one its JSON gives. A graph made by Upload
input gets one in three ways, the first that exists being shown:

1. A person wrote it: a mesh admin, or a person of a company that keeps an input in the graph.
2. The model wrote it (``refresh``), from the facts of the graph: its inputs, the things and the relations taken from
   their text, what they state and the topics they name. Never from the raw text. It is kept with a fingerprint of the
   inputs and their extractions and is shown only while that fingerprint still holds.
3. Code wrote it from the inputs: how many and whose, their kinds, the topics most of them name, their titles, when
   they were uploaded and how far they are shared.

The first two are kept in one small file each per graph and are shown only to people who see the whole graph and may
read its text: a mesh admin and the companies that keep its inputs. Anyone else gets the description made by code from
the inputs they may see.

``match`` names the context graphs a question is about, from what the person may see: by a thing of the graph the
question names in full ("ZenFusion"), by the concepts the question and the graph both name, by the words the question
shares with the name, the description and the titles, and, when none of these finds a graph, by the meaning of the
question against the descriptions (the same vectors the vocabulary uses). Ask
NeuralMesh shows these graphs with the answer and asks their companies when the wording alone points to no company.
"""
from __future__ import annotations

import json
import re
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.mesh_graph import norm_tokens

APP_ROOT = Path(__file__).resolve().parents[1]
TEXT_MAX = 1_000
TEXT_MIN = 20
TOPICS = 6  # topics named in a description made by code
TITLES = 4  # titles named in a description made by code
MATCH_TOP = 3
WORDS_AT = 2  # words of the question a graph has to share when they share no concept
MEANING_MIN = 0.45  # the cosine from which a description answers a question by meaning, as for a concept of the vocabulary
STOPWORDS = frozenset("a an the of to for in on at by with and or is are was were be been do doe does did which what who whom whose "
                      "how many much when where why this that these those it its their them they there from into about any all "
                      "list show give tell me us our we you your can could should would will has have had not no".split())
_lock = threading.RLock()
_vectors: dict[str, tuple[str, Any]] = {}  # graph id -> (the text that was embedded, its vector)


class Refused(ValueError):
    pass


def folder() -> Path:
    return Path(os.getenv("NEURALMESH_GRAPH_NOTES", str(APP_ROOT / ".neuralmesh" / "graph_notes")))


def _file(graph_id: str) -> Path:
    return folder() / f"{''.join(c for c in graph_id if c.isalnum() or c in '-_.:').replace(':', '__')}.json"


def written(graph_id: str) -> dict[str, Any] | None:
    """The description a person wrote for the graph, or None."""
    try:
        data = json.loads(_file(graph_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("text") else None


def write(graph_id: str, text: str, user: dict[str, Any]) -> dict[str, Any] | None:
    """Keep the description a person wrote. An empty text takes it away, so the one made by code shows again."""
    text = " ".join(str(text or "").split())
    path = _file(graph_id)
    with _lock:
        if not text:
            path.unlink(missing_ok=True)
            return None
        if not TEXT_MIN <= len(text) <= TEXT_MAX:
            raise Refused(f"A description has {TEXT_MIN} to {TEXT_MAX:,} characters. This one has {len(text):,}.")
        note = {"graph": graph_id, "text": text, "by_company": str(user.get("company") or ""),
                "by_role": "Mesh admin" if "mesh_admin" in (user.get("roles") or []) else "User",
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(note, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return note


# ── the description the model writes ────────────────────────────────────────

FACT_THINGS = 70  # things named in the facts given to the model
FACT_LINKS = 45
FACT_STATEMENTS = 10
MODEL_MIN, MODEL_MAX = 120, 1_000


def fingerprint(records: list[tuple[str, dict]]) -> str:
    """What a model description rests on: the inputs of the graph and the time each one's extraction was made."""
    import hashlib
    from services import graph_extract
    parts = sorted(f'{r["document"]["id"]}@{(graph_extract.read(r["document"]["id"]) or {}).get("made", "")}' for _, r in records)
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _model_file(graph_id: str) -> Path:
    return _file(graph_id).with_suffix(".model.json")


def by_model(graph_id: str, records: list[tuple[str, dict]]) -> dict[str, Any] | None:
    """The description the model wrote, when it was written for the inputs and extractions the graph has now."""
    try:
        data = json.loads(_model_file(graph_id).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and data.get("text") and data.get("fingerprint") == fingerprint(records) else None


def facts(rt: Any, name: str, records: list[tuple[str, dict]]) -> str:
    """The facts of a graph as the model reads them: no raw text of a file, only what was taken from it."""
    from collections import defaultdict
    from services import graph_extract, uploads
    from services.json_templates import KIND_WORDS
    g = rt.mesh.graph
    docs = [r for _, r in records]
    kinds = Counter(str(d["document"].get("kind_label") or KIND_WORDS.get(d["document"].get("kind", ""), d["document"].get("kind", "other"))).lower() for d in docs)
    lines = [f"Graph: {name}", f"Companies: {_listed(sorted({uploads.company_label(node) for node, _ in records}))}",
             f"Kinds of input: {_listed([_count(n, k) for k, n in kinds.most_common()])}",
             "Titles of the inputs: " + " | ".join(d["document"]["title"] for d in docs[:12])]
    names: dict[str, tuple[str, str]] = {}
    degree: Counter[str] = Counter()
    stated, said = [], []
    for record in docs:
        data = graph_extract.read(record["document"]["id"]) or {}
        gone = {x["concept"] for x in record.get("topics_set_aside") or []}
        for e in data.get("entities", []):
            names[e["id"]] = (e["name"], graph_extract.entity_type(e["type"]))
        for link in data.get("links", []):
            if graph_extract.effective(link)["status"] == "rejected" or {link["source"], link["target"]} & gone:
                continue  # rejected by a person, set aside by the model's check, or about a topic taken off the document
            if link["type"] in graph_extract.STATEMENT_LINKS:
                said.append(f'{link["type"][4:].capitalize()}: {names.get(link["target"], ("", ""))[0][:160]}')
            elif link["type"] not in ("ABOUT", graph_extract.RELATED):
                stated.append(link)
                degree.update((link["source"], link["target"]))
    label = lambda i: names[i][0] if i in names else str(g.nodes[i].get("label") or i) if i in g else i  # noqa: E731
    by_type: dict[str, list[str]] = defaultdict(list)
    for i, _ in degree.most_common(FACT_THINGS):
        if i in names and names[i][1] not in ("Decision", "Action", "Risk"):
            by_type[names[i][1]].append(names[i][0])
    if by_type:
        lines.append("Things the inputs name, the most linked first:")
        lines += [f"- {kind}: {', '.join(found[:14])}" for kind, found in sorted(by_type.items(), key=lambda x: -len(x[1]))[:14]]
    if stated:
        lines.append("What the inputs state between them:")
        lines += [f'- {label(x["source"])} {x["type"].lower().replace("_", " ")} {label(x["target"])}' for x in stated[:FACT_LINKS]]
    if said:
        lines.append("Decisions, actions and risks the inputs state:")
        lines += [f"- {x}" for x in said[:FACT_STATEMENTS]]
    main = topics(rt, records, 8)
    if main:
        lines.append("Topics of the group vocabulary the inputs name: " + ", ".join(lbl for _, lbl, _ in main))
    return "\n".join(lines)


def refresh(rt: Any, graph_id: str) -> dict[str, Any] | None:
    """Have the model write the description of an uploaded graph again and keep it. None when the graph has no input, no
    model is configured, the model policy keeps the model away from the graph, or the reply is not a usable paragraph.
    The description made by code then stays."""
    from services import uploads
    from services.context import prompts
    records = [(node, r) for node, r in uploads._all_records() if uploads.graph_ref(r)["id"] == graph_id]
    if not records:
        return None
    levels = [uploads.datapoints_of(node).get(r["document"]["datapoint"].split(":", 1)[1], {}).get("sensitivity") or "Restricted" for node, r in records]
    worst = max(levels, key=lambda x: uploads.SENSITIVITY_ORDER.index(x) if x in uploads.SENSITIVITY_ORDER else len(uploads.SENSITIVITY_ORDER))
    call = uploads._extract_caller(rt, worst, all(r.get("synthetic") is True for _, r in records))
    if call is None:
        return None
    prompt = prompts.load("describe")
    reply = call("describe", prompt.text, facts(rt, uploads.graph_ref(records[0][1])["name"], records)[:11_000], prompt.version)
    text = " ".join(str(reply or "").replace("*", "").replace("#", "").split())
    if len(text) > MODEL_MAX:  # a longer reply is cut at the last whole sentence that fits
        cut = text.rfind(". ", 0, MODEL_MAX)
        text = text[:cut + 1] if cut > 0 else text
    if not MODEL_MIN <= len(text) <= MODEL_MAX or any(c in text for c in "{}") or len(re.findall(r"[.!?](?:\s|$)", text)) < 2:
        return None  # not a paragraph of plain sentences: the description made by code stays
    note = {"graph": graph_id, "text": text, "fingerprint": fingerprint(records), "prompt": prompt.version,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    path = _model_file(graph_id)
    with _lock:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(json.dumps(note, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    return note


def _count(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else many or one + 's'}"


def _listed(names: list[str]) -> str:
    return names[0] if len(names) == 1 else f"{', '.join(names[:-1])} and {names[-1]}"


def topics(rt: Any, records: list[tuple[str, dict]], top: int = TOPICS) -> list[tuple[str, str, int]]:
    """(concept id, label, inputs that name it) for the concepts most inputs of the graph name."""
    g = rt.mesh.graph
    counts = Counter(c for _, r in records for c in dict.fromkeys(r["document"].get("concepts") or []))
    ranked = sorted(counts.items(), key=lambda x: (-x[1], str(g.nodes[x[0]].get("label") if x[0] in g else x[0]).casefold()))
    return [(c, str(g.nodes[c].get("label") or c), n) for c, n in ranked if c in g][:top]


def generated(rt: Any, records: list[tuple[str, dict]]) -> str:
    """The description made by code from the inputs given: five or six short sentences."""
    from services import uploads
    from services.json_templates import KIND_WORDS, sharing_words
    from shared.registry import is_shared
    docs = [r for _, r in records]
    companies = sorted({uploads.company_label(node) for node, _ in records})
    items: dict[tuple[str, str], dict] = {}
    for node, r in records:
        code = r["document"]["datapoint"].split(":", 1)[1]
        items.setdefault((node, code), uploads.datapoints_of(node).get(code, {}))
    item_names = list(dict.fromkeys(str(dp.get("title") or code) for (_, code), dp in items.items()))
    lines = [f"{_count(len(docs), 'input')} from {_listed(companies)}, kept under the catalogue {'item' if len(item_names) == 1 else 'items'} {_listed(item_names)}."]
    kinds = Counter(str(d["document"].get("kind_label") or KIND_WORDS.get(d["document"].get("kind", ""), d["document"].get("kind", "other"))).lower() for d in docs)
    lines.append(f"Kinds of input: {_listed([_count(n, k) for k, n in kinds.most_common()])}.")
    main = topics(rt, records)
    if main:
        lines.append(f"Main topics: {_listed([label for _, label, _ in main])}.")
    else:
        lines.append("The inputs name no known topic of the group vocabulary.")
    titles = [d["document"]["title"] for d in sorted(docs, key=lambda d: d["upload"]["at"])]
    more = len(titles) - TITLES
    lines.append(f"Inputs: {', '.join(titles[:TITLES])}{f', and {more} more' if more > 0 else ''}.")
    days = sorted({d["upload"]["at"][:10] for d in docs})
    lines.append(f"Uploaded on {days[0]}." if len(days) == 1 else f"Uploaded from {days[0]} to {days[-1]}.")
    rules = list(dict.fromkeys(sharing_words(dp, uploads.company_label(node), is_shared(node)) for (node, _), dp in items.items()))
    rules = [r for r in rules if r]
    if rules:
        lines.append(f"Sharing: {_listed(rules)}.")
    return " ".join(lines)


def of(rt: Any, graph_id: str, shown: list[tuple[str, dict]], whole: bool, company: str, roles: list[str]) -> dict[str, Any]:
    """The description of an uploaded graph for one person. ``shown`` are the inputs the person sees, and ``whole`` says
    that these are all inputs of the graph. ``can_write`` says the person may write the description."""
    can_write = "mesh_admin" in roles or any(node == company for node, _ in shown)
    note = written(graph_id) if whole and can_write else None
    if note:
        return {"text": note["text"], "by": "person", "at": note["at"], "can_write": can_write}
    from services import uploads
    may_read_all = all(uploads._may_read_text(node, r, company, roles) for node, r in shown)
    made = by_model(graph_id, shown) if whole and can_write and may_read_all else None  # it rests on the text of every input
    if made:
        return {"text": made["text"], "by": "model", "at": made["at"], "can_write": can_write}
    return {"text": generated(rt, shown), "by": "code", "can_write": can_write}


# ── the graphs a question is about ──────────────────────────────────────────

def _content(text: str) -> set[str]:
    return {t for t in norm_tokens(text) if t not in STOPWORDS and len(t) > 2}


def _uploaded(rt: Any, company: str, roles: list[str]) -> list[dict[str, Any]]:
    """Every uploaded graph the person sees an input of: its inputs, its concepts and the text that describes it."""
    from services import uploads
    by_graph: dict[str, list[tuple[str, dict]]] = {}
    sizes: Counter[str] = Counter()
    for node, r in uploads._all_records():
        ref = uploads.graph_ref(r)
        sizes[ref["id"]] += 1
        if uploads._visible(rt, r["document"]["id"], company, roles):
            by_graph.setdefault(ref["id"], []).append((node, r))
    from services import graph_extract
    out = []
    for graph_id, records in by_graph.items():
        text = of(rt, graph_id, records, len(records) == sizes[graph_id], company, roles)["text"]
        things: dict[str, list[str]] = {}  # the things taken from the text of the inputs the person may read, by name
        for node, r in records:
            if uploads._may_read_text(node, r, company, roles):
                for e in (graph_extract.read(r["document"]["id"]) or {}).get("entities", []):
                    if e.get("type") not in ("Decision", "Action", "Risk") and len(e["name"]) >= 4:
                        things.setdefault(e["name"], norm_tokens(e["name"]))
        out.append({"id": graph_id, "name": uploads.graph_ref(records[0][1])["name"], "kind": "uploaded", "description": text,
                    "nodes": sorted({node for node, _ in records}), "things": things,
                    "concepts": {c for _, r in records for c in r["document"].get("concepts") or []},
                    "words": _content(f'{uploads.graph_ref(records[0][1])["name"]} {text} {" ".join(r["document"]["title"] for _, r in records)} {" ".join(things)}')})
    return out


def _ingested(company: str, roles: list[str]) -> list[dict[str, Any]]:
    from services import context_graph_ingest as ingested
    out = []
    for r in ingested.records():
        if not ingested.may_see(r, company, roles) or r.get("corrects"):
            continue  # a corrected drawing belongs to its uploaded graph, which is matched by its inputs
        names = " ".join(n["name"] for n in r["nodes"][:400])
        out.append({"id": r["id"], "name": r["name"], "kind": "ingested", "description": r.get("description") or "", "nodes": [r["company"]],
                    "things": {n["name"]: norm_tokens(n["name"]) for n in r["nodes"][:2000] if len(n["name"]) >= 4},
                    "concepts": set(), "words": _content(f'{r["name"]} {r.get("description") or ""} {names}')})
    return out


def _by_meaning(question: str, graphs: list[dict[str, Any]]) -> dict[str, float]:
    """The cosine of the question with the description of each graph. Empty when the vectors cannot be made."""
    try:
        import numpy as np
        from knowledge import embedder
        with _lock:
            todo = [g for g in graphs if _vectors.get(g["id"], ("", None))[0] != f'{g["name"]}. {g["description"]}']
        if todo:
            made = embedder.embed([f'{g["name"]}. {g["description"]}' for g in todo])
            with _lock:
                for g, v in zip(todo, made):
                    _vectors[g["id"]] = (f'{g["name"]}. {g["description"]}', v)
        q = embedder.embed([question])[0]
        out = {}
        with _lock:
            for g in graphs:
                v = _vectors[g["id"]][1]
                norm = float(np.linalg.norm(q) * np.linalg.norm(v))
                out[g["id"]] = float(np.dot(q, v) / norm) if norm else 0.0
        return out
    except Exception:  # noqa: BLE001 - no vectors: the concepts and the words decide alone
        return {}


def match(rt: Any, question: str, concept_ids: set[str] | list[str], company: str, roles: list[str], top: int = MATCH_TOP,
          meaning: bool = True) -> list[dict[str, Any]]:
    """The context graphs a question is about, the best first, from what the person may see. Each says why: the
    concepts the question and the graph share, the words they share, or the closeness of the question to the description."""
    graphs = _uploaded(rt, company, roles) + _ingested(company, roles)
    from services.mesh_graph import _phrase_in
    asked, words = set(concept_ids), _content(question)
    tokens = norm_tokens(question)
    g = rt.mesh.graph
    found = []
    for item in graphs:
        shared = sorted(asked & item["concepts"])
        same = sorted(words & item["words"])
        # a thing of the graph the question names in full. A name of one common word, such as "ticket", is not enough
        named = sorted(name for name, phrase in item.get("things", {}).items() if phrase and _phrase_in(phrase, tokens)
                       and (len(phrase) > 1 or any(c.isupper() or c.isdigit() for c in name[1:])))  # one word counts only as a proper name: ZenFusion, PRIDE
        if not shared and not named and len(same) < WORDS_AT:
            continue
        score = (0.6 * len(shared) / len(asked) if asked else 0.0) + (0.4 * len(same) / len(words) if words else 0.0) + (0.5 if named else 0.0)
        found.append({**item, "score": round(score, 3), "matched_on": "things" if named else "concepts" if shared else "words", "shared_things": named[:6],
                      "shared_concepts": [str(g.nodes[c].get("label") or c) for c in shared if c in g], "shared_words": same[:8]})
    if not found and meaning and graphs and question.strip():
        close = _by_meaning(question, graphs)
        found = [{**item, "score": round(close[item["id"]], 3), "matched_on": "meaning", "shared_things": [], "shared_concepts": [], "shared_words": []}
                 for item in graphs if close.get(item["id"], 0.0) >= MEANING_MIN]
    found.sort(key=lambda x: (-x["score"], x["name"].casefold()))
    return [{k: v for k, v in x.items() if k not in ("concepts", "words", "things")} for x in found[:top]]


# ── the graph a question is about, chosen by the model ──────────────────────────────────────────────────────────────

LISTED_MAX = 30  # graphs the model reads for one question. Beyond this, the ones code finds closest are listed first
DESCRIPTION_CHARS = 600
TITLES_SHOWN = 15
INTENTS = ("clear", "unclear", "off_topic", "greeting")


def model_caller(backend: Any, app_env: str):
    """The caller for the choose step. The descriptions it reads may be of real, restricted graphs, so the model policy
    lets only a model that may read real data (the group gateway, or the local testing switch) make it."""
    if backend is None:
        return None
    import uuid
    from services.context.llm import make_caller
    return make_caller(backend, app_env=app_env, trace_id=f"choose-{uuid.uuid4().hex[:8]}", sensitivities={"Restricted"}, all_synthetic=False, calls=[])


def _titles(rt: Any, graph_ids: list[str], company: str, roles: list[str]) -> dict[str, list[str]]:
    """The titles of the inputs of uploaded graphs the person sees."""
    from services import uploads
    out: dict[str, list[str]] = {}
    wanted = set(graph_ids)
    for _, r in uploads._all_records():
        gid = uploads.graph_ref(r)["id"]
        if gid in wanted and uploads._visible(rt, r["document"]["id"], company, roles):
            out.setdefault(gid, []).append(r["document"]["title"].replace("Meeting Title:", "").strip())
    return out


def _line(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def choose(rt: Any, question: str, concept_ids: set[str] | list[str], company: str, roles: list[str], call_model=None) -> dict[str, Any]:
    """What a person means by a question and which of the graphs they may see holds the answer, decided by the model.

    Code only decides what the model may read: the graphs the person may see, each with its name, description and input
    titles. Up to LISTED_MAX of them, the closest by code first when there are more. The model returns the intent
    (clear, unclear, off_topic or greeting), the question as it understood it, the graphs, and for a question that is
    not clear, up to three full questions the person could ask instead. Code then keeps only graphs from the list and
    suggestions of plain text. Without a model nothing is chosen, and the reply says why.

    {"chosen": [...], "close": [...], "by": "model" | "none", "intent", "understood_as", "suggestions", "reason"}"""
    from services.context import prompts
    question = " ".join(str(question or "").split())
    nothing = {"chosen": [], "close": [], "by": "none", "intent": "unknown", "understood_as": question, "suggestions": [], "reason": ""}
    graphs = _uploaded(rt, company, roles) + _ingested(company, roles)
    if not graphs:
        return {**nothing, "reason": "no context graph is shown to you"}
    if call_model is None:
        return {**nothing, "reason": "choosing a graph needs the model, which is not available"}
    if len(graphs) > LISTED_MAX:  # too many to list: the closest by names, topics, words and meaning come first
        order = {g["id"]: i for i, g in enumerate(match(rt, question, concept_ids, company, roles, top=LISTED_MAX, meaning=False))}
        close = _by_meaning(question, graphs)
        graphs = sorted(graphs, key=lambda g: (order.get(g["id"], LISTED_MAX), -close.get(g["id"], 0.0)))[:LISTED_MAX]
    titles = _titles(rt, [g["id"] for g in graphs], company, roles)
    listed = [{k: v for k, v in g.items() if k not in ("concepts", "words", "things")} for g in graphs]
    user = f"Question: {question[:500]}\n\n" + "\n\n".join(
        f"G{i}: {g['name']}\n{_line(g.get('description'), DESCRIPTION_CHARS)}"
        + (f"\nInputs: {' | '.join(titles[g['id']][:TITLES_SHOWN])}" if titles.get(g["id"]) else "")
        for i, g in enumerate(listed, 1))
    prompt = prompts.load("choose")
    reply = call_model("choose", prompt.text, user, prompt.version)
    try:
        data = json.loads(reply[reply.find("{"): reply.rfind("}") + 1]) if reply else None
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return {**nothing, "reason": "the model gave no usable reply"}

    def pick(refs: Any) -> list[dict[str, Any]]:
        out = []
        for ref in refs if isinstance(refs, list) else []:
            n = str(ref).strip().upper().lstrip("G")
            if n.isdigit() and 0 < int(n) <= len(listed) and listed[int(n) - 1] not in out:
                out.append(listed[int(n) - 1])
        return out

    intent = data.get("intent") if data.get("intent") in INTENTS else "unclear"
    reason = _line(data.get("reason"), 160)
    understood = _line(data.get("understood_as"), 500) or question
    suggestions = [_line(x, 200) for x in (data.get("suggestions") or []) if isinstance(x, str) and _line(x, 200)][:3] if intent != "clear" else []
    graphs_named = pick(data.get("graphs"))[:2]
    if intent == "clear":
        return {"chosen": [{**g, "why": reason} for g in graphs_named], "close": [], "by": "model", "intent": intent,
                "understood_as": understood, "suggestions": [], "reason": reason}
    # a question that is not clear is not restated: the model describes it there, and the suggestions are what to ask
    return {"chosen": [], "close": graphs_named, "by": "model", "intent": intent, "understood_as": question, "suggestions": suggestions, "reason": reason}
