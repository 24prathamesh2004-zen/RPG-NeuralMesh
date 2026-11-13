"""Entities and links taken from the text of an uploaded document, beside the links the upload already made.

An upload links its document to the concepts of the group vocabulary the text names (services.uploads.concepts_in). That
gives document to concept links only. This step adds what the text says between them, in two parts:

- By code, always: two known concepts named in the same sentence get a link, with that sentence as evidence. When one of
  the relation words of RELATION_WORDS stands between the two names ("checklist depends on the cutover plan"), the link
  carries that relation and runs from the first name to the second. Otherwise it is RELATED_TO.
- By the model, when the model policy allows it for the item's sensitivity and the upload's real or invented mark: new
  entities (a machine, a part, a supplier) and named links between them and the known concepts. Code keeps an entity only
  when its name is in the text, and a link only when its evidence sentence is in the text and names both ends. A real
  upload gets no cloud model, so it gets the code part only.

- By code, always: the sentences of the text that state a decision, a next action or a risk in set wordings ("we agreed
  to", "the follow-up is", "my concern is") become entities of type Decision, Action or Risk, each linked from its
  document by HAS_DECISION, HAS_ACTION or HAS_RISK and to the known concepts the sentence names by ABOUT. A question is
  not a statement, and the name of a speaker in front of a sentence is left out.

A link is kept as "proposed". The graph view shows it as approved without a person when the text settles it (settled):
a link with a named relation, or two concepts the text names together in two sentences or more. A link the text names
once with no relation word stays proposed, and a mesh admin or a person of the owning company approves or rejects it.
A person's decision always stands over the rule. Nothing here
changes the upload record, the pack, the indexes or the links the upload made: the result is one file per document in
the node's ``extractions`` folder, read by the context graph view (services.uploads) and shown as proposed or approved
links. A new entity's id carries its company, so the same name in two companies stays two entities.
"""
from __future__ import annotations

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

from knowledge import packgen
from services.mesh_graph import _phrase_in, norm_tokens

FOLDER = "extractions"
STATUSES = ("proposed", "approved", "rejected")
EVIDENCE_MAX = 300  # characters of the sentence kept as evidence
CODE_LINKS_MAX = 40
MODEL_TEXT_CHARS = 6_000  # the text the model reads in one call
MODEL_PARTS = 40  # the most parts one document is read in, which is 240,000 characters. A longer text is read up to there
MODEL_WORKERS = 4  # parts of one document read at the same time
ENTITIES_MAX = 150
MODEL_LINKS_MAX = 200
FILE_THINGS_MAX = 25  # new things one document adds to its graph, the most linked first. A thing already in the graph does not count
EXISTING_MAX = 150  # things already in the graph shown to the model, so that it writes their names the same way
NAME_WORDS_MAX = 8  # a name longer than this is a description, not a name
# the types and the relations the model may use (prompt mesh_extract_v3). A type or a relation outside the lists is read
# through its synonym, and a thing whose type has none is left out, so that a graph does not fill with types used once
ENTITY_TYPES = ("System", "Team", "Role", "Process", "Form", "Policy", "Programme", "Service", "Asset", "Part", "Material",
                "Standard", "Defect", "Test", "Site", "Organisation")
TYPE_SYNONYMS = {
    "System": ("software", "portal", "platform", "application", "app", "tool", "website", "database", "dashboard", "system"),
    "Team": ("department", "group", "committee", "function", "unit", "team", "board", "cell", "office of"),
    "Role": ("role", "position", "job", "designation", "owner", "lead", "manager", "head", "officer"),
    "Process": ("process", "procedure", "workflow", "review", "step", "activity", "meeting", "cycle", "ritual", "practice", "event"),
    "Form": ("form", "document", "record", "checklist", "template", "letter", "report", "certificate", "ticket", "request", "file", "sheet", "plan document", "specification document"),
    "Policy": ("policy", "rule", "guideline", "regulation", "code of conduct", "law", "act", "agreement"),
    "Programme": ("programme", "program", "scheme", "benefit", "plan", "initiative", "insurance plan", "fund", "trust"),
    "Service": ("service", "service desk", "helpdesk", "help desk", "support"),
    "Asset": ("asset", "machine", "equipment", "product", "vehicle", "structure", "tyre", "tower", "device"),
    "Part": ("part", "component", "spare"),
    "Material": ("material", "compound", "consumable", "chemical", "rubber"),
    "Standard": ("standard", "specification", "clause", "norm"),
    "Defect": ("defect", "failure", "failure mode", "condition", "fault", "damage"),
    "Test": ("test", "check", "inspection", "measurement", "audit", "assessment", "evaluation"),
    "Site": ("site", "plant", "office", "warehouse", "location", "factory", "facility", "branch"),
    "Organisation": ("organisation", "organization", "company", "supplier", "vendor", "insurer", "customer", "client", "partner", "bank", "underwriter"),
}
RELATIONS = ("USES", "PART_OF", "CONTAINS", "OWNED_BY", "MANAGED_BY", "APPROVED_BY", "REQUIRES", "PRECEDES", "RAISED_ON",
             "ACCESSED_VIA", "PROVIDED_BY", "SUPPLIED_BY", "GOVERNED_BY", "APPLIES_TO", "PRODUCES", "TESTED_BY", "CAUSES",
             "AFFECTS", "REPLACES", "ASSIGNED_TO", "REPORTS_TO", "INSURED_UNDER", "INSPECTED_VIA")
RELATION_SYNONYMS = {
    "USED_BY": None, "USES_PART": "USES", "USED_THROUGH": "ACCESSED_VIA", "ACCESSIBLE_ON": "ACCESSED_VIA", "ACCESSIBLE_VIA": "ACCESSED_VIA",
    "AVAILABLE_ON": "ACCESSED_VIA", "ACCESSED_THROUGH": "ACCESSED_VIA", "ISSUED_THROUGH": "PROVIDED_BY", "ISSUED_BY": "PROVIDED_BY",
    "OFFERED_BY": "PROVIDED_BY", "RUN_BY": "MANAGED_BY", "HANDLED_BY": "MANAGED_BY", "MAINTAINED_BY": "MANAGED_BY",
    "OWNS": None, "APPROVES": None, "SIGNED_OFF_BY": "APPROVED_BY", "AUTHORISED_BY": "APPROVED_BY", "AUTHORIZED_BY": "APPROVED_BY",
    "NEEDS": "REQUIRES", "DEPENDS_ON": "REQUIRES", "REQUIRED_BEFORE": "PRECEDES", "FOLLOWS": None, "COMES_BEFORE": "PRECEDES",
    "SUBMITTED_ON": "RAISED_ON", "LOGGED_ON": "RAISED_ON", "FILED_ON": "RAISED_ON", "GOVERNS": None, "SUBJECT_TO": "GOVERNED_BY",
    "COVERS": "APPLIES_TO", "APPLIES_FOR": "APPLIES_TO", "INCLUDES": "CONTAINS", "HAS": "CONTAINS", "BELONGS_TO": "PART_OF",
    "TESTS": None, "CHECKED_AGAINST": "TESTED_BY", "LEADS_TO": "CAUSES", "RESULTS_IN": "CAUSES", "INSURED_BY": "INSURED_UNDER",
    "UNDERWRITTEN_BY": "INSURED_UNDER", "SUPERSEDES": "REPLACES", "ASSIGNED_BY": None, "REPORTS_INTO": "REPORTS_TO",
}
# a relation written from the other end ("Manager APPROVES Leave") is turned round to the listed one
REVERSE = {"OWNS": "OWNED_BY", "APPROVES": "APPROVED_BY", "FOLLOWS": "PRECEDES", "GOVERNS": "GOVERNED_BY", "TESTS": "TESTED_BY",
           "USED_BY": "USES", "ASSIGNED_BY": "ASSIGNED_TO", "MANAGES": "MANAGED_BY", "PROVIDES": "PROVIDED_BY", "SUPPLIES": "SUPPLIED_BY"}


def listed_type(kind: str) -> str | None:
    """The listed type a type the model wrote stands for, or None when it stands for none of them."""
    k = " ".join(str(kind or "").replace("_", " ").split()).casefold()
    if not k:
        return None
    for t in ENTITY_TYPES:
        if k == t.casefold():
            return t
    for t, words in TYPE_SYNONYMS.items():
        if k in words:
            return t
    head = k.split()[-1]  # "Insurance Plan" is a plan, "IS Service Desk Portal" a portal
    for t, words in TYPE_SYNONYMS.items():
        if head in words:
            return t
    return None


def listed_relation(relation: str) -> tuple[str, bool] | None:
    """(the listed relation, whether the two ends are turned round), or None when the relation stands for none of them."""
    r = re.sub(r"[^A-Z0-9]+", "_", str(relation or "").upper()).strip("_")
    if r in RELATIONS:
        return r, False
    if r in REVERSE:
        return REVERSE[r], True
    mapped = RELATION_SYNONYMS.get(r)
    return (mapped, False) if mapped else None


def thing_id(node: str, name: str) -> str:
    """The id of a thing taken from a text: its company and its name as words, so that "IS Service Desks" and
    "IS service desk" are one thing of the company."""
    return f"entity:{node}:{_slug(' '.join(norm_tokens(name)))}"
NAME_MAX = 80
TYPE_MAX = 30
SENTENCE = re.compile(r"(?<=[.!?])\s+|\n{2,}|\n(?=[-*•\d])")
RELATED = "RELATED_TO"  # two concepts named in one sentence, with no relation word between them
GAP_MAX = 8  # words between the two names within which a relation word names the link
SETTLED_AT = 2  # sentences that name both concepts, from which a RELATED_TO link needs no person
# the relation a link carries when one of these wordings stands between the two names. The first name is the source.
RELATION_WORDS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("DEPENDS_ON", ("depends on", "depend on", "dependent on", "relies on", "rely on", "requires", "require")),
    ("BLOCKED_BY", ("blocked by", "delayed by", "held up by", "waiting on", "waits on")),
    ("BLOCKS", ("blocks", "delays", "prevents", "holds up")),
    ("CAUSED_BY", ("caused by", "because of", "due to", "results from")),
    ("CAUSES", ("causes", "leads to", "lead to", "results in", "result in", "triggers")),
    ("PART_OF", ("is part of", "are part of", "part of", "belongs to", "belong to", "included in")),
    ("INCLUDES", ("includes", "include", "contains", "contain", "consists of", "covers")),
    ("USES", ("uses", "is based on", "based on", "built on", "runs on")),
    ("OWNED_BY", ("owned by", "managed by", "handled by", "approved by", "reviewed by", "led by", "run by")),
    ("REPLACES", ("replaces", "replace", "supersedes", "instead of")),
    ("FOLLOWS", ("follows", "comes after", "starts after")),
    ("PRECEDES", ("precedes", "comes before", "ahead of", "prior to")),
    ("IMPROVES", ("improves", "improve", "reduces", "reduce", "speeds up")),
    ("SUPPORTS", ("supports", "enables", "enable", "feeds into", "feeds")),
    ("MEASURED_BY", ("measured by", "tracked by", "tracked in", "reported in")),
)


_FILES = threading.RLock()  # one read-change-write of an extraction file at a time, so a person's decision is never lost


def _write(doc_id: str, data: dict[str, Any]) -> None:
    path = _path(doc_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


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


_RELATION_PHRASES = sorted(((norm_tokens(w), kind) for kind, words in RELATION_WORDS for w in words), key=lambda x: -len(x[0]))


def _span(phrases: list[list[str]], tokens: list[str]) -> tuple[int, int] | None:
    """Where the first of the names stands in the sentence: (first word, word after the last)."""
    best = None
    for p in phrases:
        n = len(p)
        for i in range(len(tokens) - n + 1):
            if tokens[i:i + n] == p and (best is None or i < best[0]):
                best = (i, i + n)
                break
    return best


def relation_between(tokens: list[str], first: tuple[int, int], second: tuple[int, int]) -> str | None:
    """The relation word that stands between two names of one sentence, the longest wording first. None when the names
    overlap, are more than GAP_MAX words apart, or no relation word stands between them."""
    gap = tokens[first[1]:second[0]]
    if second[0] < first[1] or len(gap) > GAP_MAX:
        return None
    for phrase, kind in _RELATION_PHRASES:
        if _phrase_in(phrase, gap):
            return kind
    return None


def code_links(rt: Any, text: str, concept_ids: list[str]) -> list[dict[str, Any]]:
    """One link for each two known concepts named in the same sentence, the sentence as evidence. The link carries the
    relation a sentence states between them and runs from the first name to the second. When no sentence states one it
    is RELATED_TO. "sentences" counts the sentences that name both."""
    names = _names(rt, concept_ids)
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for sentence in sentences(text):
        tokens = norm_tokens(sentence)
        spans = {cid: span for cid, phrases in names.items() if (span := _span(phrases, tokens))}
        here = sorted(spans)
        for i, a in enumerate(here):
            for b in here[i + 1:]:
                link = found.setdefault((a, b), {"source": a, "target": b, "type": RELATED, "evidence": sentence[:EVIDENCE_MAX],
                                                 "by": "code", "sentences": 0, "full_names": 0})
                link["sentences"] += 1
                if all(names[c] and _phrase_in(names[c][0], tokens) for c in (a, b)):  # both by their full name, not by another name or one word of it
                    link["full_names"] += 1
                    if link["full_names"] == 1 and link["type"] == RELATED:
                        link["evidence"] = sentence[:EVIDENCE_MAX]  # the sentence that names both in full is the better evidence
                if link["type"] == RELATED:  # the first sentence that states a relation names the link
                    first, second = (a, b) if spans[a][0] <= spans[b][0] else (b, a)
                    relation = relation_between(tokens, spans[first], spans[second])
                    if relation:
                        link.update(source=first, target=second, type=relation, evidence=sentence[:EVIDENCE_MAX])
    links = sorted(found.values(), key=lambda x: (x["type"] == RELATED, -x["sentences"]))
    return links[:CODE_LINKS_MAX]


STATEMENTS: tuple[tuple[str, str, re.Pattern[str]], ...] = (  # (entity type, link type, the wordings that state it)
    ("Decision", "HAS_DECISION", re.compile(r"\b(we (have )?agreed|agreed to|agreed that|working agreement|the decision is|decision was|decided to|decided that|was approved|is approved|signed off)\b", re.I)),
    ("Action", "HAS_ACTION", re.compile(r"\b(the follow[- ]up is|follow[- ]up action|next step is|action item|the action is)\b", re.I)),
    ("Risk", "HAS_RISK", re.compile(r"\b(concern is|the risk is|risk is that|dependency is|blocker is|blocked by|is blocked)\b", re.I)),
)
STATEMENT_LINKS = frozenset(link for _, link, _ in STATEMENTS)
STATEMENTS_EACH = 3  # statements of one kind kept for a document
STATEMENTS_MAX = 8  # statements kept for a document
STATEMENT_CHARS = (40, 260)  # a statement is one sentence of this length
STATEMENT_TOPICS = 3  # known concepts a statement is linked to
_SPEAKER = re.compile(r"^(?:[A-Z][\w.'-]+(?: [A-Z][\w.'-]+){0,3}:\s+)+")  # "Asha Rao: " in front of a line of a transcript, once or twice


STATEMENT_WORDS = 10  # words in the name of a statement. The whole sentence stays as its evidence
_LEAD = re.compile(r"^(?:that|to|is|are|was|were|the|a|an|of|on|for|we|our|:|,|-)\s+", re.I)


def short_statement(sentence: str, match: re.Match[str]) -> str:
    """The name of a statement: what follows its wording ("We agreed to move the review to Monday" gives "Move the review
    to Monday"), at most STATEMENT_WORDS words. The sentence itself when nothing follows the wording."""
    rest = sentence[match.end():].strip(" .,:;-")
    head, colon, tail = rest.partition(": ")
    if colon and len(head) <= 70 and len(tail.split()) >= 3:  # "working agreement, not a claim that the risk is gone: prioritize X" says X
        rest = tail
    while True:
        cut = _LEAD.sub("", rest)
        if cut == rest:
            break
        rest = cut
    words = (rest or sentence).rstrip(".").split()
    name = " ".join(words[:STATEMENT_WORDS])
    return (name[:1].upper() + name[1:]) + (" ..." if len(words) > STATEMENT_WORDS else "")


def statement_name(sentence: str) -> str | None:
    """The short name of a statement from its sentence, as code_statements writes it now."""
    m = next((found for _, _, pattern in STATEMENTS if (found := pattern.search(sentence))), None)
    return short_statement(sentence, m) if m else None


def code_statements(rt: Any, node: str, doc_id: str, text: str, concept_ids: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(entities, links): the decisions, next actions and risks a text states in the wordings of STATEMENTS, the first
    STATEMENTS_EACH of each kind and STATEMENTS_MAX in all. Each is an entity named by its sentence, linked from the
    document and to the known concepts the sentence names. The id of a statement comes from its sentence, so the same
    sentence keeps its id when the extraction is made again."""
    names = _names(rt, concept_ids)
    local = doc_id.split(":", 1)[1]
    entities: list[dict[str, Any]] = []
    links: list[dict[str, Any]] = []
    kept: dict[str, int] = {}
    seen: set[str] = set()
    for raw in sentences(text):
        sentence = _SPEAKER.sub("", raw).strip()
        if sentence.endswith("?") or not STATEMENT_CHARS[0] <= len(sentence) <= STATEMENT_CHARS[1] or sentence.casefold() in seen:
            continue
        hit = next(((kind, link, m) for kind, link, pattern in STATEMENTS if (m := pattern.search(sentence))), None)
        if hit is None or kept.get(hit[0], 0) >= STATEMENTS_EACH:
            continue
        seen.add(sentence.casefold())
        kept[hit[0]] = kept.get(hit[0], 0) + 1
        eid = f"entity:{node}:{_slug(local)}-{hit[0].lower()}-{hashlib.sha256(sentence.casefold().encode()).hexdigest()[:8]}"
        entities.append({"id": eid, "type": hit[0], "name": short_statement(sentence, hit[2]), "sentence": sentence, "by": "code"})
        links.append({"source": doc_id, "target": eid, "type": hit[1], "evidence": sentence[:EVIDENCE_MAX], "by": "code", "sentences": 1})
        tokens = norm_tokens(sentence)
        about = [cid for cid, phrases in sorted(names.items()) if any(_phrase_in(p, tokens) for p in phrases)][:STATEMENT_TOPICS]
        links += [{"source": eid, "target": cid, "type": "ABOUT", "evidence": sentence[:EVIDENCE_MAX], "by": "code", "sentences": 1} for cid in about]
        if len(entities) >= STATEMENTS_MAX:
            break
    return entities, links


def named(rt: Any, link: dict[str, Any]) -> dict[str, Any]:
    """A RELATED_TO link made by code before relations were read, with the relation its evidence sentence states. The
    link itself when the sentence states none."""
    if link.get("by") != "code" or link.get("type") != RELATED:
        return link
    tokens = norm_tokens(link.get("evidence") or "")
    names = _names(rt, [link["source"], link["target"]])
    spans = {cid: span for cid, phrases in names.items() if (span := _span(phrases, tokens))}
    if len(spans) != 2:
        return link
    first, second = sorted(spans, key=lambda c: spans[c][0])
    relation = relation_between(tokens, spans[first], spans[second])
    return {**link, "source": first, "target": second, "type": relation} if relation else link


def settled(link: dict[str, Any]) -> str | None:
    """Why the text settles a link made by code, so that no person is asked, or None when a person is asked.
    "relation": a sentence states a relation between the two names. "repeated": SETTLED_AT sentences or more name both
    topics by their full names. A topic found by another name or by one word of its name ("handling" for "Materials
    handling") does not count, because such a match may be about something else. A link kept before the full names were
    counted has no such count and is not settled. A link the model made is never settled by rule."""
    if link.get("by") != "code":
        return None
    if link.get("type") != RELATED:
        return "relation"
    return "repeated" if int(link.get("full_names") or 0) >= SETTLED_AT else None


def effective(link: dict[str, Any]) -> dict[str, Any]:
    """The link with the status the screens show, the first that applies:
    1. a person's decision as it is,
    2. approved by the rule of ``settled``, with its reason,
    3. the check of the model (``verify``): "supported" approves it, "not_supported" sets it aside,
    4. otherwise proposed, and a person is asked when its priority is high."""
    if link.get("status") != "proposed" or link.get("decided"):
        return link
    if (link.get("check") or {}).get("keep") is False:  # true or not, the model judged it noise: left out, a person may still approve it
        return {**link, "status": "rejected", "settled_by": "model", "settled_reason": "not_needed"}
    reason = settled(link)
    if reason:
        return {**link, "status": "approved", "settled_by": "rule", "settled_reason": reason}
    verdict = (link.get("check") or {}).get("verdict")
    if verdict == "supported":
        return {**link, "status": "approved", "settled_by": "model", "settled_reason": "checked"}
    if verdict == "not_supported":
        return {**link, "status": "rejected", "settled_by": "model", "settled_reason": "not_supported"}
    return link


# a link a person is asked about when the model is unsure of it: one that says who owns, approves or must do what, what
# a thing needs or is governed by, or one that touches a policy, a standard or a defect. Every other unsure link stays
# proposed, drawn dashed, without asking anyone
HIGH_RELATIONS = frozenset({"APPROVED_BY", "OWNED_BY", "MANAGED_BY", "REQUIRES", "GOVERNED_BY", "INSURED_UNDER", "ASSIGNED_TO",
                            "REPORTS_TO", "CAUSES", "REPLACES", "HAS_DECISION"})
HIGH_TYPES = frozenset({"Policy", "Standard", "Defect"})


def priority(link: dict[str, Any], types: dict[str, str]) -> str:
    """"high" or "low": whether a person is asked about a proposed link."""
    if link.get("type") in HIGH_RELATIONS or {types.get(link["source"]), types.get(link["target"])} & HIGH_TYPES:
        return "high"
    return "low"


VERIFY_BATCH = 25  # links checked in one call


def topic_sentence(rt: Any, text: str, concept_id: str) -> str | None:
    """The first sentence of the text that names a topic, by its label or another name, as a whole phrase. None when the
    topic was matched only by its words standing apart in the text."""
    phrases = _names(rt, [concept_id]).get(concept_id, [])
    for sentence in sentences(text):
        tokens = norm_tokens(sentence)
        if any(_phrase_in(p, tokens) for p in phrases):
            return sentence[:EVIDENCE_MAX]
    return None


def check_topics(rt: Any, record: dict[str, Any], call_model: Callable) -> dict[str, dict[str, str]]:
    # a topic the person tagged is theirs: it is never judged, so never taken off
    """Whether the document is about each topic it was linked to at upload. A topic whose name stands in no sentence was
    matched only by words that stand apart in the text, and is not supported. The others are judged by the model from
    the first sentence that names them. A topic a person kept is not asked about again."""
    from services.context import prompts
    doc = record["document"]
    g = rt.mesh.graph
    out: dict[str, dict[str, str]] = {}
    ask = []
    matches = record.get("concept_matches") or {}
    for cid in doc.get("concepts") or []:
        if cid not in g or matches.get(cid) == "tag":
            continue
        sentence = topic_sentence(rt, doc.get("body") or "", cid)
        if sentence is None:
            out[cid] = {"verdict": "not_supported", "reason": "the name of the topic stands in no sentence", "by": "code", "at": _now()}
        else:
            ask.append((cid, sentence))
    prompt = prompts.load("verify")
    for i in range(0, len(ask), VERIFY_BATCH):
        batch = ask[i:i + VERIFY_BATCH]
        user = "\n\n".join(f"id: t{n}\nsource: {doc['title']}\nrelation: IS_ABOUT\ntarget: {g.nodes[cid].get('label') or cid}\nsentence: {sentence}"
                            for n, (cid, sentence) in enumerate(batch))
        reply = call_model("verify", prompt.text, user, prompt.version)
        for item in re.findall(r"\{[^{}]*\}", reply or ""):
            try:
                v = json.loads(item)
            except ValueError:
                continue
            ref = str(v.get("id", "")) if isinstance(v, dict) else ""
            if ref.startswith("t") and ref[1:].isdigit() and int(ref[1:]) < len(batch) and v.get("verdict") in ("supported", "not_supported", "unsure"):
                cid, sentence = batch[int(ref[1:])]
                out[cid] = {"verdict": v["verdict"], "reason": _line(v.get("reason") or "")[:120], "sentence": sentence, "by": "model", "at": _now()}
    return out


def verify(rt: Any, doc_id: str, call_model: Callable | None) -> dict[str, int]:
    """Have the model check every link of a document that no person decided, against the sentence it was taken from, and
    keep its two answers on the link: whether the sentence states it (verdict) and whether it is worth keeping (keep).
    A link a rule settled is asked about too, for the second answer. Code then reads both (``effective``). A link
    already checked under both questions keeps its answers. Counts of the answers given now."""
    data = read(doc_id)
    if not data or call_model is None:
        return {}
    from services.context import prompts
    g = rt.mesh.graph
    names = {e["id"]: e["name"] for e in data.get("entities", [])}
    label = lambda i: names.get(i) or (str(g.nodes[i].get("label") or i) if i in g else i)  # noqa: E731
    pending = [link for link in data.get("links", []) if link.get("status") == "proposed" and not link.get("decided")
               and "keep" not in (link.get("check") or {})]
    if not pending:
        return {}
    prompt = prompts.load("verify")
    counts: Counter[str] = Counter()
    answers: dict[str, dict[str, Any]] = {}
    evidence = {link["id"]: link.get("evidence") for link in pending}
    for i in range(0, len(pending), VERIFY_BATCH):
        batch = pending[i:i + VERIFY_BATCH]
        user = "\n\n".join(f"id: {link['id']}\nsource: {label(link['source'])}\nrelation: {link['type']}\ntarget: {label(link['target'])}\nsentence: {link['evidence']}"
                            for link in batch)
        reply = call_model("verify", prompt.text, user, prompt.version)
        verdicts = {}
        for item in re.findall(r"\{[^{}]*\}", reply or ""):
            try:
                v = json.loads(item)
            except ValueError:
                continue
            if isinstance(v, dict) and v.get("verdict") in ("supported", "not_supported", "unsure"):
                verdicts[str(v.get("id"))] = v
        for link in batch:
            v = verdicts.get(link["id"])
            if v:
                keep = v.get("keep") is not False  # a reply without the answer keeps the link
                answers[link["id"]] = {"verdict": v["verdict"], "keep": keep, "reason": _line(v.get("reason") or "")[:120], "by": "model", "at": _now()}
                counts[v["verdict"]] += 1
                counts["not_needed"] += 0 if keep else 1
    with _FILES:  # the model was asked outside the lock: its answers go into the file as it is now, never over a person's decision
        current = read(doc_id)
        if current is None:
            return dict(counts)
        for link in current.get("links", []):
            if link["id"] in answers and not link.get("decided") and link.get("evidence") == evidence.get(link["id"]):
                link["check"] = answers[link["id"]]
        _write(doc_id, current)
    return dict(counts)


def _parse(reply: str | None) -> dict[str, Any] | None:
    """The reply of the model as {"entities": [...], "links": [...]}. A reply that is not one valid JSON object, for
    example one with a quotation mark inside an evidence sentence, is read object by object: every entity and every
    link that is valid by itself is kept, and only the broken one is lost."""
    if not reply:
        return None
    cleaned = reply.strip().strip("`")
    cleaned = cleaned[4:] if cleaned.lower().startswith("json") else cleaned
    try:
        data = json.loads(cleaned[cleaned.find("{"): cleaned.rfind("}") + 1])
        if isinstance(data, dict):
            return data
    except ValueError:
        pass
    entities, links = [], []
    for piece in re.findall(r"\{[^{}]*\}", cleaned):
        try:
            item = json.loads(piece)
        except ValueError:
            continue
        if isinstance(item, dict) and "source" in item and "target" in item:
            links.append(item)
        elif isinstance(item, dict) and "name" in item:
            entities.append(item)
    return {"entities": entities, "links": links} if entities or links else None


def _words(text: str) -> str:
    """The text as its words in a row, " storage ageing check ", so that one text is found in another whatever the
    capitals, the punctuation, the line breaks and a plural s."""
    return f" {' '.join(norm_tokens(text))} "


RESERVED_TYPES = {"document": "Record", "datapoint": "Item", "subsidiary": "Company", "concept": "Term", "expert": "Role"}


def entity_type(kind: str) -> str:
    """The type of a thing taken from a text. A type the graph itself uses, such as Document for an uploaded input,
    gets another word, so that a form named in a text is not counted as an input."""
    kind = " ".join(str(kind or "Entity").split())[:TYPE_MAX] or "Entity"
    return RESERVED_TYPES.get(kind.casefold(), kind[:1].upper() + kind[1:])


def _parts(text: str) -> list[str]:
    """The whole text as the model reads it: one part when it fits one call, otherwise parts of up to MODEL_TEXT_CHARS
    that follow each other without a gap, each ended at a line break or, where there is none, at the end of a sentence,
    so that no sentence is cut in two. At most MODEL_PARTS parts."""
    out, start = [], 0
    while start < len(text) and len(out) < MODEL_PARTS:
        end = min(len(text), start + MODEL_TEXT_CHARS)
        if end < len(text):
            cut = max(text.rfind("\n", start + MODEL_TEXT_CHARS // 2, end), text.rfind(". ", start + MODEL_TEXT_CHARS // 2, end) + 1)
            end = cut + 1 if cut > start else end
        out.append(text[start:end])
        start = end
    return out or [text]


def model_part(rt: Any, node: str, text: str, concept_ids: list[str], call_model: Callable | None,
               existing: list[tuple[str, str]] = ()) -> tuple[list[dict], list[dict], str]:
    """(entities, links, note). The model proposes, code keeps only what the text holds. A text longer than one call is
    read in parts (_parts), and what the parts give is put together under the same checks. ``existing`` are the things
    already in the graph as (name, type): the model is asked to write their names the same way, and a thing it names so
    takes the id it already has, which joins the documents of a graph and makes a new upload add to what is there.

    Code keeps a thing only with a listed type (listed_type) and a short name, a link only with a listed relation
    (listed_relation) and with evidence that is in the text and names both ends, and at most FILE_THINGS_MAX new things
    for one document, the most linked first."""
    if call_model is None:
        return [], [], "no model"
    from services.context import prompts
    g = rt.mesh.graph
    known = {cid: g.nodes[cid].get("label") or cid for cid in concept_ids if cid in g}
    prompt = prompts.load("extract")
    parts = _parts(text)

    shown = list(dict.fromkeys(existing))[:EXISTING_MAX]
    head = "Known concepts:\n" + "\n".join(f"- {label}" for label in known.values())
    if shown:
        head += "\n\nThings already in the graph:\n" + "\n".join(f"- {name} ({kind})" for name, kind in shown)

    def read(part: str) -> dict[str, Any] | None:
        user = f"{head}\n\nText:\n{part}"
        return _parse(call_model("extract", prompt.text, user, prompt.version))

    if len(parts) == 1:
        answers = [read(parts[0])]
    else:  # the parts are read side by side and put together in the order of the text
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=MODEL_WORKERS) as pool:
            answers = list(pool.map(read, parts))
    replies = [data for data in answers if data is not None]
    if not replies:
        return [], [], "the model was not asked or gave no usable reply"
    flat = _words(text)
    by_name: dict[str, str] = {label.casefold(): cid for cid, label in known.items()}
    old_ids = {thing_id(node, name) for name, _ in shown}
    for name, kind in shown:
        by_name.setdefault(name.casefold(), thing_id(node, name))
    entities: dict[str, dict[str, Any]] = {}
    old_kind = {thing_id(node, name): kind for name, kind in shown}
    for item in (x for data in replies for x in data.get("entities") or []):
        if not isinstance(item, dict):
            continue
        name = _line(item.get("name") or "")[:NAME_MAX]
        kind = listed_type(item.get("type") or "")
        eid = thing_id(node, name) if _slug(" ".join(norm_tokens(name))) else ""
        if eid in old_ids:  # a thing already in the graph keeps its id and its type
            by_name[name.casefold()] = eid
            continue
        if (kind is None or len(name) < 2 or len(name.split()) > NAME_WORDS_MAX or not eid or not _words(name).strip()
                or _words(name) not in flat or name.casefold() in by_name):
            continue  # a type outside the list, a description for a name, not in the text, or a known concept, which keeps its own id
        if len(entities) >= ENTITIES_MAX:
            break
        entities.setdefault(eid, {"id": eid, "type": kind, "name": name, "by": "model"})
        by_name[name.casefold()] = eid
    links: list[dict[str, Any]] = []
    seen = set()
    for item in (x for data in replies for x in data.get("links") or []):
        if not isinstance(item, dict):
            continue
        src, dst = _line(item.get("source") or ""), _line(item.get("target") or "")
        evidence = _line(item.get("evidence") or "")
        listed = listed_relation(item.get("relation") or "")
        a, b = by_name.get(src.casefold()), by_name.get(dst.casefold())
        said = _words(evidence)
        if not (listed and a and b and a != b and len(said) > 2 and said in flat and _words(src) in said and _words(dst) in said):
            continue  # a relation outside the list, an end that is not a thing, or evidence that is not in the text, word for word, or does not name both ends
        relation, turned = listed
        if turned:
            a, b = b, a
        if (a, relation, b) in seen:
            continue
        seen.add((a, relation, b))
        links.append({"source": a, "target": b, "type": relation, "evidence": evidence[:EVIDENCE_MAX], "by": "model"})
        if len(links) >= MODEL_LINKS_MAX:
            break
    # at most FILE_THINGS_MAX new things for the document, the most linked first, and only the links between things kept
    degree = Counter(x for link in links for x in (link["source"], link["target"]) if x in entities)
    keep = {eid for eid, _ in sorted(degree.items(), key=lambda x: (-x[1], list(entities).index(x[0])))[:FILE_THINGS_MAX]}
    things = set(known) | old_ids | keep
    links = [link for link in links if link["source"] in things and link["target"] in things]
    used = {x for link in links for x in (link["source"], link["target"])}
    reused = [{"id": eid, "type": old_kind[eid], "name": next(n for n, _ in shown if thing_id(node, n) == eid), "by": "model", "existing": True}
              for eid in sorted(used & old_ids)]
    note = "made" if len(parts) == 1 else f"made, {len(replies)} of {len(parts)} parts read" + ("" if sum(len(p) for p in parts) >= len(text) else f", the text after {MODEL_PARTS * MODEL_TEXT_CHARS:,} characters not read")
    return [e for e in entities.values() if e["id"] in used] + reused, links, note


def extract(rt: Any, node: str, record: dict[str, Any], call_model: Callable | None = None,
            existing: list[tuple[str, str]] = ()) -> dict[str, Any]:
    """Make and keep the extraction of one accepted upload. Links of an earlier extraction keep their decision.
    ``existing`` are the things already in the graph of the upload, as (name, type), which the model reuses."""
    document = record["document"]
    text = document.get("body") or ""
    concepts = list(document.get("concepts") or [])
    entities, model_links, note = model_part(rt, node, text, concepts, call_model, existing)
    statements, statement_links = code_statements(rt, node, document["id"], text, concepts)
    entities = [*entities, *statements]
    found = [*code_links(rt, text, concepts), *statement_links, *model_links]
    with _FILES:  # the decisions are read when the file is written, so one a person made meanwhile is kept
        earlier = (read(document["id"]) or {}).get("links", [])
        out = {"document": document["id"], "made": _now(), "model": note, "entities": entities, "links": _carry(found, earlier)}
        _write(document["id"], out)
    return out


def _carry(found: list[dict[str, Any]], earlier: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The links found now, each with the id, the decision and the check its earlier self had."""
    before = {(link["source"], link["type"], link["target"]): link for link in earlier}
    plain = {frozenset((link["source"], link["target"])): link for link in earlier if link.get("by") == "code" and link["type"] == RELATED}
    links = []
    for link in found:
        # a link kept as RELATED_TO before relations were read keeps its id and its decision under its new name
        old = before.get((link["source"], link["type"], link["target"])) or (plain.get(frozenset((link["source"], link["target"]))) if link["by"] == "code" else None)
        links.append({"id": old["id"] if old else f"x-{uuid.uuid4().hex[:10]}", **link,
                      "status": old["status"] if old else "proposed", **({"decided": old["decided"]} if old and old.get("decided") else {}),
                      **({"check": old["check"]} if old and old.get("check") and old.get("evidence") == link["evidence"] else {})})
    return links


def read(doc_id: str) -> dict[str, Any] | None:
    try:
        return json.loads(_path(doc_id).read_text(encoding="utf-8"))
    except (OSError, ValueError, IndexError):
        return None


def summary(extraction: dict[str, Any] | None) -> dict[str, Any] | None:
    if not extraction:
        return None
    links = [effective(x) for x in extraction.get("links", [])]
    return {"entities": len(extraction.get("entities", [])), "links": len(links),
            "proposed": sum(1 for x in links if x["status"] == "proposed"),
            "checked": sum(1 for x in links if x.get("settled_by") == "model" and x["status"] == "approved"),
            "set_aside": sum(1 for x in links if x.get("settled_by") == "model" and x["status"] == "rejected" and x.get("settled_reason") != "not_needed"),
            "not_needed": sum(1 for x in links if x.get("settled_reason") == "not_needed"), "model": extraction.get("model")}


def decide(doc_id: str, link_id: str, status: str, user: dict[str, Any]) -> dict[str, Any]:
    """Set a link to approved or rejected. KeyError when the document or the link has no extraction."""
    if status not in ("approved", "rejected"):
        raise ValueError("status is approved or rejected")
    with _FILES:
        data = read(doc_id)
        link = next((x for x in (data or {}).get("links", []) if x["id"] == link_id), None)
        if data is None or link is None:
            raise KeyError(link_id)
        link["status"] = status
        link["decided"] = {"at": _now(), "by_company": str(user.get("company") or ""),
                           "by_role": "Mesh admin" if "mesh_admin" in (user.get("roles") or []) else "User"}
        _write(doc_id, data)
    return link
