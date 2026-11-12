"""Structured JSON output of a context graph, shaped by a template the person can read and edit.

A template is JSON. A string such as "{title}" is a value filled from the graph. An object with "$each" set to
"document", "node", "edge", "concept" or "link" becomes a list: its other keys are written once for each item. The block
may be written inside [ ], the way the output looks. Code checks a template
before it is used: an unknown field or an unknown "$each" is refused with the place named. The data comes from the
context graph as the person may see it, so the output never holds more than the page shows.

Every context graph gives the one standard template, DEFAULT (decided 2026-11-10 after a review: one structure for all
graphs, only the values differ). A value a graph does not have is written as null and an empty list as [], so no key is
ever left out, and an edge whose end is not among the nodes brings that end in as a node of type "Unknown", so the
output is always a whole graph.

NOTE, kept and switched off: a template of its own for each context graph (one file for each graph in ``folder()``,
sent with the upload as ``output_template`` or set with PUT /uploads/graphs/{id}/template, built 2026-11-10). The code
and its test stay. ``per_graph()`` turns it back on with NEURALMESH_TEMPLATE_PER_GRAPH=1, and the Add input form then
shows Edit and Upload again."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

APP_ROOT = Path(__file__).resolve().parents[1]
FIELDS: dict[str, dict[str, str]] = {
    "graph": {"graph.name": "the name of the context graph", "graph.id": "its id", "graph.companies": "the companies of its inputs, a list",
              "graph.inputs": "how many inputs it holds"},
    "document": {"id": "the document id", "title": "its title", "company": "the company that keeps it", "kind": "its kind",
                 "item": "its catalogue item code", "item_title": "the name of the catalogue item", "sharing": "what leaves the company",
                 "uploaded": "the upload date", "file": "the uploaded file name", "tags": "its tags, a list",
                 "summary": "its first sentences, when the person may read them", "concepts": "the concepts it names, a list"},
    "concept": {"id": "the concept id", "label": "its name", "mentioned_by": "the titles of the documents that name it, a list"},
    "link": {"id": "the link id", "type": "the kind of link", "source": "the id it starts from", "target": "the id it points to",
             "source_label": "the name it starts from", "target_label": "the name it points to", "status": "approved or proposed"},
    "node": {"id": "the node id", "type": "what the node is: Document, Concept and so on, or Unknown for the end of an edge that is not among the nodes",
             "label": "its name", "company": "the company it belongs to, null for a node of the whole group"},
}
FIELDS["edge"] = FIELDS["link"]  # "edge" is the graph word for a link: the same items and the same fields
EACH = ("document", "node", "edge", "concept", "link")
DEFAULT: dict[str, Any] = {
    "graph_id": "{graph.id}",  # loaded back in Upload input, the changed file replaces the graph it came from
    "graph": "{graph.name}",
    "companies": "{graph.companies}",
    "documents": [{"$each": "document", "id": "{id}", "title": "{title}", "company": "{company}", "kind": "{kind}", "catalogue_item": "{item_title}",
                   "sharing": "{sharing}", "uploaded": "{uploaded}", "concepts": "{concepts}"}],
    "nodes": [{"$each": "node", "id": "{id}", "type": "{type}", "name": "{label}", "company": "{company}"}],
    "edges": [{"$each": "edge", "id": "{id}", "type": "{type}", "source": "{source}", "target": "{target}",
               "from": "{source_label}", "to": "{target_label}", "status": "{status}"}],
}
MAX_CHARS = 20_000
PLACE = re.compile(r"\{([a-z_.]+)\}")
KIND_WORDS = {"sop": "Procedure", "rca": "Root cause analysis", "playbook": "Playbook", "post_mortem": "Post-mortem", "standard": "Standard",
              "report": "Report", "policy": "Policy", "wiki": "Wiki page", "aggregate": "Aggregate figures", "note": "Note",
              "study_material": "Study material", "role_profile": "Role profile"}


class TemplateRefused(ValueError):
    pass


def folder() -> Path:
    return Path(os.getenv("NEURALMESH_JSON_TEMPLATES", str(APP_ROOT / ".neuralmesh" / "json_templates")))


def check(template: Any) -> list[str]:
    """Every problem of a template, each with its place, for example "documents.title: {titel} is not a field"."""
    problems: list[str] = []
    if not isinstance(template, dict):
        return ["the template is a JSON object, written in { }"]
    if len(json.dumps(template)) > MAX_CHARS:
        problems.append(f"the template has more than {MAX_CHARS:,} characters")

    def walk(value: Any, scope: str, path: str) -> None:
        if isinstance(value, dict):
            if "$each" in value:
                each = value["$each"]
                if scope != "graph":
                    problems.append(f'{path}: a "$each" inside another "$each" is not used. Write the list at the top level')
                elif each not in EACH:
                    problems.append(f'{path}.$each: "{each}" is not a list of the graph. Use document, node, edge, concept or link')
                else:
                    for k, v in value.items():
                        if k != "$each":
                            walk(v, each, f"{path}.{k}" if path else k)
                return
            for k, v in value.items():
                walk(v, scope, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, v in enumerate(value):
                walk(v, scope, path if len(value) == 1 and isinstance(v, dict) and "$each" in v else f"{path}[{i}]")
        elif isinstance(value, str):
            allowed = set(FIELDS["graph"]) | (set(FIELDS[scope]) if scope != "graph" else set())
            for name in PLACE.findall(value):
                if name not in allowed:
                    where = f"a {scope}" if scope != "graph" else 'the graph (outside a "$each")'
                    problems.append(f"{path or 'value'}: {{{name}}} is not a field of {where}. Fields: {', '.join('{' + f + '}' for f in sorted(allowed))}")
    walk(template, "graph", "")
    return problems


def _fill(text: str, values: dict[str, Any]) -> Any:
    whole = PLACE.fullmatch(text)
    if whole:  # one field alone keeps its type: a list stays a list, a number a number
        value = values.get(whole.group(1))
        return None if value in ("", None) else value  # a value the graph does not have is null, and the key stays
    return PLACE.sub(lambda m: ", ".join(map(str, v)) if isinstance(v := values.get(m.group(1), ""), list) else "" if v is None else str(v), text)


def render(template: dict[str, Any], data: dict[str, Any]) -> Any:
    problems = check(template)
    if problems:
        raise TemplateRefused("; ".join(problems))
    graph_values = {k: v for k, v in data["graph"].items()}

    def walk(value: Any, values: dict[str, Any]) -> Any:
        if isinstance(value, dict):
            if "$each" in value:
                body = {k: v for k, v in value.items() if k != "$each"}
                return [walk(body, {**graph_values, **item}) for item in data[value["$each"] + "s"]]
            return {k: walk(v, values) for k, v in value.items()}
        if isinstance(value, list):
            if len(value) == 1 and isinstance(value[0], dict) and "$each" in value[0]:
                return walk(value[0], values)  # written as a list of one block, the way the output looks: [ { "$each": ... } ]
            return [walk(v, values) for v in value]
        if isinstance(value, str):
            return _fill(value, values)
        return value
    return walk(template, graph_values)


def sharing_words(dp: dict, company: str, shared: bool) -> str:
    if shared:
        return "Shared with every connected company"
    if dp.get("never_leave"):
        return f"Never leaves {company}"
    return {"MD": f"Title only leaves {company}", "SUM": f"Summary leaves {company}", "RAG": f"Full text leaves {company}",
            "LIVE": f"Asked live from {company}"}.get(str(dp.get("ceiling") or "").upper(), "")


def data_of(rt: Any, graph_id: str, company: str, roles: list[str]) -> dict[str, Any]:
    """The context graph as the person may see it, in the fields of FIELDS."""
    from shared.registry import is_shared
    from services import uploads
    view = uploads.context_graph_view(rt, graph_id, company, roles)
    labels = {n["id"]: n["label"] for n in view["nodes"]}
    known = set(labels)
    # an edge whose end is not among the nodes: the end comes in as a node of type "Unknown", so the edges always fit the nodes
    missing = [end for e in view["edges"] for end in (e["source"], e["target"]) if end not in known]
    documents, titles = [], {}
    for doc_id in view["documents"]:
        node = doc_id.split(":", 1)[0]
        record = uploads.record_of(node, doc_id)
        if not record:
            continue
        doc = record["document"]
        released = uploads.pack_documents([record], company, roles)[0]  # the summary only when the person may read it
        code = doc["datapoint"].split(":", 1)[1]
        dp = uploads.datapoints_of(node).get(code, {})
        name = uploads.company_label(node)
        titles[doc_id] = doc["title"]
        documents.append({"id": doc_id, "title": doc["title"], "company": name, "kind": doc.get("kind_label") or KIND_WORDS.get(doc.get("kind", ""), doc.get("kind", "")),
                          "item": code, "item_title": dp.get("title", code), "sharing": sharing_words(dp, name, is_shared(node)),
                          "uploaded": record["upload"]["at"][:10], "file": record["upload"]["file"], "tags": list(doc.get("tags") or []),
                          "summary": released.get("summary", ""), "concepts": [labels.get(c, c) for c in doc.get("concepts") or [] if c in labels]})
    concepts = []
    for n in view["nodes"]:
        if n["type"] == "Concept":
            mentioned = sorted({titles[e["source"]] for e in view["edges"] if e["target"] == n["id"] and e["source"] in titles})
            concepts.append({"id": n["id"], "label": n["label"], "mentioned_by": mentioned})
    links = [{"id": e["id"], "type": e["type"], "source": e["source"], "target": e["target"], "source_label": labels.get(e["source"], ""),
              "target_label": labels.get(e["target"], ""), "status": e.get("status", "")} for e in view["edges"]]
    graph = {"graph.name": view["name"], "graph.id": graph_id, "graph.companies": sorted({d["company"] for d in documents}), "graph.inputs": len(documents)}
    nodes = [{"id": n["id"], "type": n["type"], "label": n["label"], "company": uploads.company_label(n["subsidiary"]) if n.get("subsidiary") else ""}
             for n in view["nodes"]]
    nodes += [{"id": end, "type": "Unknown", "label": "", "company": ""} for end in dict.fromkeys(missing)]
    return {"graph": graph, "documents": documents, "concepts": concepts, "links": links, "nodes": nodes, "edges": links}


def per_graph() -> bool:
    """Whether a context graph may have a template of its own. Off: every graph gives the standard template (see the note
    at the top of this file)."""
    return os.environ.get("NEURALMESH_TEMPLATE_PER_GRAPH", "").strip().lower() in ("1", "true", "yes")


STANDARD_ONLY = "Every context graph gives its JSON in the standard structure, so a template of its own is not kept."


def _graph_file(graph_id: str) -> Path:
    return folder() / (re.sub(r"[^A-Za-z0-9_.-]+", "_", graph_id) + ".json")


def of_graph(graph_id: str) -> tuple[dict[str, Any], bool]:
    """The template a context graph gives its output in, and whether it is the graph's own. A graph without its own
    template follows the suggested one."""
    if graph_id and per_graph():
        try:
            item = json.loads(_graph_file(graph_id).read_text(encoding="utf-8"))
            if isinstance(item, dict) and item.get("graph_id") == graph_id and not check(item.get("template")):
                return item["template"], True
        except (OSError, ValueError):
            pass
    return DEFAULT, False


def set_for_graph(graph_id: str, template: Any, by: str) -> tuple[dict[str, Any], bool]:
    """Keep a template with its context graph. The suggested template is not written: the graph then has none of its own.
    Refused while ``per_graph()`` is off."""
    if not per_graph():
        raise TemplateRefused(STANDARD_ONLY)
    problems = check(template)
    if problems:
        raise TemplateRefused("; ".join(problems))
    path = _graph_file(graph_id)
    if template == DEFAULT:
        path.unlink(missing_ok=True)
        return DEFAULT, False
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"graph_id": graph_id, "template": template, "set_by": by}, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return template, True
