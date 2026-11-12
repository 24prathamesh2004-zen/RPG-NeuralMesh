#!/usr/bin/env python3
"""Make RPG_NeuralMesh_API_How_It_Works_v1.html beside this folder.

Inputs, all in this folder: recorded.json (the calls record_calls.py sent to the running development API, with each
request and the answer it gave), routes.json (every REST route read from the code: method, path, who may call it,
parameters) and contract.json (the published context contract). The route tables below are checked against
routes.json, so a route that is added or removed in the code stops this script until the tables follow.
Run: python3 make_api_page.py"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "RPG_NeuralMesh_API_How_It_Works_v1.html"
CALLS = {c["id"]: c for c in json.loads((HERE / "recorded.json").read_text())}
ROUTES = json.loads((HERE / "routes.json").read_text())
CONTRACT = json.loads((HERE / "contract.json").read_text())
SENT_ON = "11 November 2026"
BASE = "http://127.0.0.1:8000"
e = html.escape


# ── the routes, one row each, in the order of the page ────────────────────────────────────────────────────────────
# (group, method, path, who, request, answer, check) where check is a recorded call id or the reason it was not sent
NOT_SENT = "Not sent: it changes data"
DEV_DEMO = "Signed in, development only, demo accounts"
R = [
    ("Health and sign-in", "GET", "/health", "Anyone", "Nothing", '<code>{"status": "ok", "version": "1.0.0"}</code>. The text is fixed', "health"),
    ("Health and sign-in", "GET", "/api/v1/auth/companies", "Anyone", "Nothing", "<code>companies</code>: the id and name of each company a person can sign up for", "companies"),
    ("Health and sign-in", "POST", "/api/v1/auth/signup", "Anyone",
     "<code>email</code> (5 to 254 characters), <code>password</code> (10 to 128), <code>display_name</code>, <code>company</code> (an id from companies). If wanted: <code>expert_opt_in</code>, <code>expert_title</code>, <code>expert_skills</code> (up to 20)",
     "<code>access_token</code>, <code>token_type</code>, <code>user</code>", "Not sent: it creates an account"),
    ("Health and sign-in", "POST", "/api/v1/auth/signin", "Anyone", "<code>email</code>, <code>password</code>",
     "<code>access_token</code> (valid 12 hours), <code>token_type</code> bearer, <code>user</code> with company and roles", "signin"),
    ("Health and sign-in", "GET", "/api/v1/auth/me", "Signed in", "Nothing", "The person: id, email, name, company, roles, expert profile", "me"),

    ("Ask and search the mesh", "POST", "/api/v1/mesh/query", "Signed in",
     "<code>question</code> (3 to 2,000 characters), <code>purpose</code> (problem_solving, compliance, bid_support, learning, career_mobility or inspection). If wanted: <code>nodes</code> (company ids, up to 16), <code>mode</code> (MD, SUM, RAG or LIVE), <code>as_of</code> (a date for the results blackout check)",
     "<code>status</code>, <code>answer</code>, <code>answer_status</code>, <code>citations</code>, <code>checks</code>, <code>evidence</code>, <code>withheld</code>, <code>also_found</code>, <code>relationships</code>, <code>routing</code>, <code>steps</code>, <code>node_results</code>, <code>model_calls</code>, <code>trace_id</code>", "ask"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/routing", "Signed in", "<code>q</code>: a question",
     "The concepts, companies, items and documents a question would go to. No company node is called", "routing"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/graph", "Signed in", "Nothing",
     "<code>nodes</code>, <code>edges</code>, <code>counts</code> of the mesh graph, with never-leave entities of other companies left out", "graph"),
    ("Ask and search the mesh", "POST", "/api/v1/mesh/graph/refresh", "Mesh admin", "Nothing",
     "<code>exports</code> per company node, <code>store</code> counts, <code>revision</code>, <code>checks</code>", "Not sent: it reloads the mesh graph"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/graph/search", "Signed in", "<code>q</code>: a word or phrase, up to 300 characters",
     "<code>results</code>: id, type, label, company, sharing rule and link counts of each entity found, <code>by_vector</code>, <code>total</code>", "search"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/graph/entity/{entity_id}", "Signed in", "The entity id in the path",
     "The entity with its properties, sharing rule and <code>related</code>: its neighbours by link type, one hop", "entity"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/domains", "Signed in", "Nothing", "Each domain's node types and edge types with live counts", "domains"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/applications", "Signed in", "Nothing", "The registered applications, what each may call and what it loaded", "applications"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/nodes", "Signed in", "Nothing", "<code>nodes</code>: each company node with its port, level, health and catalogue", "nodes"),
    ("Ask and search the mesh", "POST", "/api/v1/mesh/experts/search", "Signed in",
     "<code>query</code> (2 to 500 characters). If wanted: <code>purpose</code>, <code>nodes</code>",
     "<code>experts</code>: role, company, skills and evidence of each consented expert, never a name, and the answer of each company node", "experts"),
    ("Ask and search the mesh", "POST", "/api/v1/mesh/experts/{node_id}/intro", "Signed in",
     "<code>expert_id</code>, <code>justification</code> (10 to 500 characters). If wanted: <code>purpose</code>",
     "The access request the company node opened, waiting for its owner", "Not sent: it opens a request"),

    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/graph/links", "Signed in", "Nothing",
     "<code>links</code>: links between documents of two companies, with their status and approvals", "links"),
    ("Links, governance and the dashboard", "POST", "/api/v1/mesh/graph/links/{rel_id}/review", DEV_DEMO,
     "<code>decision</code>: approve or reject. If wanted: <code>subsidiary</code>", "The link after the review", NOT_SENT),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/proposals", "Signed in", "Nothing",
     "<code>groups</code>: the entries applications proposed, by application and link type, and <code>your_sides</code>", "proposals"),
    ("Links, governance and the dashboard", "POST", "/api/v1/mesh/proposals/review", DEV_DEMO,
     "<code>decision</code>: approve or reject. If wanted: <code>ids</code> (up to 2,000), <code>application</code>, <code>type</code>",
     "<code>reviewed</code>, <code>decision</code>", NOT_SENT),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/governance", "Signed in", "Nothing",
     "<code>pending</code> requests, the latest <code>audit</code> lines, <code>mode</code>", "governance"),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/governance/audit/verify", "Signed in", "Nothing",
     "Whether each company node's decision log is an unbroken hash chain, and <code>valid</code>", "verify"),
    ("Links, governance and the dashboard", "POST", "/api/v1/mesh/governance/{node_id}/requests/{request_id}/review", DEV_DEMO + " of the owning company",
     "<code>decision</code>: approve or deny. If wanted: <code>hours</code> (1 to 168, 24 when missing)", "The request after the review", NOT_SENT),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/admin", "Signed in", "Nothing",
     "Registry, vocabulary, graph counts, guardrails, model policy", "admin"),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/dashboard", "Signed in", "Nothing",
     "Company node health, search decisions, pending approvals, activity, <code>ingested_graphs</code>", "dashboard"),

    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads", "Signed in", "Nothing",
     "<code>uploads</code> (each document with its sharing rule and context graph), <code>graphs</code>, <code>kinds</code>, <code>formats</code>", "uploads"),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads", "Mesh admin",
     "A form with <code>file</code> (.txt, .md, .csv, .json, .pdf or .docx, up to 20 MB), <code>node_id</code>, <code>datapoint</code>, and <code>graph_id</code> of a graph or <code>graph_name</code> of a new one. If wanted: <code>kind</code>, <code>title</code>, <code>tags</code>, <code>version</code>, <code>kind_label</code>, <code>new_item_title</code>, <code>new_item_area</code>, and <code>synthetic</code>, true for invented data. A file sent without <code>synthetic</code> is real",
     "The upload record, the refresh of the company node and the graph part around the document", "Not sent: it keeps a document"),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/suggest", "Mesh admin",
     "A form with <code>file</code>. If wanted: <code>node_id</code>, <code>datapoint</code>",
     "The proposed <code>title</code>, <code>tags</code>, <code>kind</code>, <code>concepts</code> and <code>graph</code>. Nothing is kept", "suggest"),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/items/{node_id}", "Mesh admin", "The company id in the path",
     "<code>items</code>: the catalogue items an upload can go under, each with its sharing rule", "items"),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/graphs/{graph_id}", "Signed in",
     "If wanted: <code>format</code> (json, graphml, csv or pack) to get a file",
     "<code>documents</code>, <code>nodes</code>, <code>edges</code>, <code>counts</code> of the graph, or the file", "upload_graph"),
    ("Uploaded context graphs (Upload input)", "DELETE", "/api/v1/mesh/uploads/graphs/{graph_id}", "Mesh admin", "Nothing",
     "<code>removed</code> records, <code>rebuilt</code> and <code>failed</code> packs. The records stay, marked removed", NOT_SENT),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/{doc_id}/graph", "Signed in",
     "If wanted: <code>format</code> (json, graphml, csv or pack)", "The graph part around one uploaded document, or the file", "doc_graph"),
    ("Uploaded context graphs (Upload input)", "DELETE", "/api/v1/mesh/uploads/{doc_id}", "Mesh admin", "Nothing",
     "The record, marked removed", NOT_SENT),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/json-templates", "Signed in", "If wanted: <code>graph_id</code>",
     "The JSON structure every context graph is written in, and the fields it fills", "structure"),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/json-templates/render", "Signed in", "<code>graph_id</code>",
     "<code>output</code>: the graph in the JSON structure, as the person may see it", "render"),
    ("Uploaded context graphs (Upload input)", "PUT", "/api/v1/mesh/uploads/graphs/{graph_id}/template", "Mesh admin", "<code>template</code>",
     "Refused while one JSON structure for every graph is the rule", NOT_SENT),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/formats", "Mesh admin",
     "A download format: name, file extension, escaping, header, a line for each entity and each link, footer",
     "<code>format</code>, <code>export_format_list</code>", NOT_SENT),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/formats/file", "Mesh admin", "A form with <code>file</code> (up to 20,000 bytes)",
     "<code>format</code>, <code>export_format_list</code>", NOT_SENT),
    ("Uploaded context graphs (Upload input)", "DELETE", "/api/v1/mesh/uploads/formats/{format_id}", "Mesh admin", "Nothing",
     "<code>removed</code>, <code>export_format_list</code>", NOT_SENT),

    ("Ingested context graphs (Ingest data)", "POST", "/api/v1/context-graphs", "Signed in: own company, a mesh admin any",
     "The JSON (see Query a context graph). If wanted: <code>?check=true</code> to check and keep nothing",
     "201 created, or 200 replaced, unchanged or checked: <code>graph</code>, <code>filled</code>, <code>defaults</code>, <code>ignored</code>, <code>warnings</code>. 422 with <code>problems</code> when a field needs a change",
     "cg_check"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs", "Signed in", "Nothing", "<code>graphs</code>: a summary of each graph the person may see", "cg_list"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs/sample", "Signed in", "Nothing", "A small invented graph in the format, for the person's company", "cg_sample"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs/{graph_id}", "Signed in", "Nothing",
     "The graph in the format it was ingested in, with its <code>graph_id</code>, ready to change and send back", "cg_get"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs/{graph_id}/view", "Signed in", "Nothing",
     "<code>nodes</code> and <code>edges</code> for a drawing, with the graph's summary", "cg_view"),
    ("Ingested context graphs (Ingest data)", "POST", "/api/v1/context-graphs/{graph_id}/query", "Signed in",
     "One of <code>question</code>, <code>node</code>, <code>nodes</code>, <code>edges</code>, <code>path</code>, <code>similar</code>, <code>overview</code> (see Query a context graph)",
     "Depends on the kind of query. Every answer starts with <code>graph</code> and <code>kind</code>", "q_overview"),
    ("Ingested context graphs (Ingest data)", "DELETE", "/api/v1/context-graphs/{graph_id}", "Signed in: own company or a mesh admin", "Nothing",
     "<code>dropped</code>: id, name, company and counts. The file is deleted", "Not sent: it deletes a graph"),

    ("Help", "POST", "/api/v1/help/chat", "Signed in",
     "<code>question</code> (2 to 2,000 characters). If wanted: <code>history</code> (up to 20 turns), <code>page</code>",
     "<code>answer</code>, <code>sources</code>, <code>mode</code> (model or passages)", "help"),

    ("Applications: the context contract", "GET", "/api/v1/context/contract", "Service token", "Nothing",
     "The contract bundle: version 1.1, the request and answer schemas, statuses, problem codes, every tool and a <code>sha256</code> to compare", "contract"),
    ("Applications: the context contract", "POST", "/api/v1/context/{tool}", "Service token",
     "The envelope: <code>schema_version</code> 1.1, <code>tool</code>, <code>purpose</code>, <code>caller</code> (subsidiary, roles, user_ref for a person), <code>input</code>",
     "<code>status</code> (ok, partial, no_evidence, blocked, needs_input or refused), <code>records</code>, <code>answer</code>, <code>also_found</code>, <code>omitted</code>, <code>data</code>, <code>problem</code>, <code>trace_id</code>", "t_role"),
]


def _norm(path: str) -> str:
    return re.sub(r"\{(\w+):path\}", r"{\1}", path)


def check_routes() -> None:
    code = {(r["method"], _norm(r["path"])) for r in ROUTES}
    page = {(m, p) for _, m, p, *_ in R}
    if code != page or len(R) != len(ROUTES):
        sys.exit(f"The route tables do not match the code. Missing on the page: {sorted(code - page)}. Not in the code: {sorted(page - code)}")


# ── the Try tab: the recorded calls shown, in order ─────────────────────────────────────────────────────────────────
TRY = [
    ("Start", ["health", "signin", "me"]),
    ("Ask the mesh", ["ask", "routing", "search", "entity", "experts", "help"]),
    ("Query a context graph", ["q_overview", "q_nodes", "q_node", "q_edges", "q_path", "q_similar", "q_question", "q_missing", "q_scope"]),
    ("Keep a context graph", ["cg_sample", "cg_check", "cg_refused", "cg_list", "cg_get", "cg_view"]),
    ("Uploaded context graphs", ["uploads", "upload_graph", "render", "suggest"]),
    ("Applications", ["contract", "t_role", "t_entity", "t_related", "t_similar", "t_ask", "t_refused"]),
]
WHY = {
    "health": "Is the service up. No token is needed.",
    "signin": "The token for every later call. Write it into TOKEN for the curl commands.",
    "me": "Who the token belongs to: company and roles decide what the person may see.",
    "ask": "The flagship question. Routed to CEAT and Harrisons, answered from their documents with citations, and the restricted formulation is listed as withheld.",
    "routing": "Where a question would go, without calling any company node.",
    "search": "Entities of the mesh graph whose name, other name or tag holds the words.",
    "entity": "One entity with its neighbours by link type.",
    "experts": "Consented experts by skill, never a name.",
    "help": "The in-app help chat, answered from the help guides.",
    "q_overview": "What the graph holds: its node types and edge types with counts.",
    "q_nodes": "Nodes by type. name finds a part of a name, properties finds equal values.",
    "q_node": "One node, found by its other name here, with its neighbours and the edges walked.",
    "q_edges": "Relationships of one type that end at one node.",
    "q_path": "How two nodes are connected: the shortest way, edge by edge.",
    "q_similar": "Nodes of the same type ranked by the neighbours they share.",
    "q_question": "A question in plain words: the nodes it names, the edges around them, and a written answer that cites them.",
    "q_missing": "A name that is not in the graph gives 404 with the closest names.",
    "q_scope": "The same graph asked by a person of KEC: a CEAT graph with sharing company is not shown to them.",
    "cg_sample": "The sample JSON for the person's company.",
    "cg_check": "The sample checked with check=true: what would be kept, and nothing is kept.",
    "cg_refused": "A JSON with mistakes: each place to fix, and nothing is kept.",
    "cg_list": "The ingested graphs the person may see.",
    "cg_get": "One graph in the format it was ingested in, with its graph_id.",
    "cg_view": "Nodes and edges in the shape a drawing takes.",
    "uploads": "Every uploaded document the person may see, and the context graphs they form.",
    "upload_graph": "One uploaded context graph with its documents, entities and links.",
    "render": "That graph in the JSON structure, the file Upload input gives.",
    "suggest": "Read a file and propose the title, tags, kind and graph. Nothing is kept. Run the curl command in the folder that holds the file.",
    "contract": "The published contract an application pins by its sha256.",
    "t_role": "role_context: a role of a company with its required skills.",
    "t_entity": "entity: one entity of the mesh graph.",
    "t_related": "related: neighbours of an entity by link type.",
    "t_similar": "similar: computed similar roles with a reason and a score.",
    "t_ask": "ask: a cited answer for an end user of the application.",
    "t_refused": "A refusal is a normal answer that says what is needed: status refused with a problem.",
}


def trim(value, depth: int = 0):
    if isinstance(value, dict):
        return {k: trim(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        kept = [trim(v, depth + 1) for v in value[:3]]
        if len(value) > 3:
            kept.append(f"... {len(value) - 3} more not shown")
        return kept
    if isinstance(value, str) and len(value) > 320:
        return value[:320] + " ... (cut here)"
    return value


def sq(text: str) -> str:
    return "'" + text.replace("'", "'\\''") + "'"


def curl(c: dict) -> str:
    url = BASE + c["path"] + ("?" + urlencode(c["params"]) if c.get("params") else "")
    parts = [f"curl -s -X {c['method']} {sq(url)}"]
    token = {"person": "$TOKEN", "person (KEC)": "$KEC_TOKEN", "service": "$SERVICE_TOKEN"}.get(c["token"])
    if token:
        parts.append(f'-H "Authorization: Bearer {token}"')
    if c.get("multipart"):
        parts.append(f"-F {sq('file=@' + c['body']['file'])} -F {sq('node_id=' + c['body']['node_id'])}")
    elif c.get("body") is not None:
        parts.append("-H 'Content-Type: application/json'")
        parts.append("-d " + sq(json.dumps(c["body"], ensure_ascii=False)))
    return " \\\n  ".join(parts)


def try_data() -> list[dict]:
    out = []
    for group, ids in TRY:
        for cid in ids:
            c = CALLS[cid]
            url = c["path"] + ("?" + urlencode(c["params"]) if c.get("params") else "")
            out.append({"id": cid, "group": group, "title": c["title"], "why": WHY[cid], "line": f"{c['method']} {url}",
                        "auth": {"person": "Bearer token of the presenter (a mesh admin of Zensar)", "person (KEC)": "Bearer token of a KEC demo user",
                                 "service": "Service token of SkillForge", "none": "None"}[c["token"]],
                        "body": c.get("body"), "curl": curl(c), "status": c["status"], "answer": trim(c["response"])})
    return out


# ── the context graph query kinds, with their recorded examples ─────────────────────────────────────────────────────
KINDS = [
    ("What is in the graph", "overview", '{"overview": true}', "<code>nodes</code>, <code>edges</code>, <code>node_types</code> with counts, <code>edge_types</code> with count and the node types each joins, <code>nodes_without_edges</code>", "q_overview"),
    ("Find things by type, name or property", "nodes", '{"nodes": {"type": "Supplier", "name": "part of a name", "properties": {"material": "FKM"}}}', "<code>nodes</code> (up to 200) and <code>total</code>. Give one or more of type, name and properties", "q_nodes"),
    ("One thing and what is around it", "node", '{"node": "Mixer 1", "hops": 1}', "<code>node</code>, <code>neighbours</code>, <code>edges</code> walked. hops is 1 or 2", "q_node"),
    ("Relationships", "edges", '{"edges": {"type": "SUPPLIES", "source": "Supplier X", "target": "Rotor seal RS-200"}}', "<code>edges</code> (up to 500), each with its source and target, and <code>total</code>. Give one or more of type, source and target", "q_edges"),
    ("How two things are connected", "path", '{"path": {"from": "Supplier X", "to": "Plant A", "max_hops": 4}}', "<code>hops</code> and <code>paths</code>: up to 3 shortest ways, each a list of edges and a line of text. max_hops is 1 to 6, 4 when missing", "q_path"),
    ("What is similar to one thing", "similar", '{"similar": {"node": "Supplier X", "top": 5}}', "<code>similar</code>: nodes of the same type with <code>score</code> (shared neighbours divided by all the neighbours of the two), <code>shared</code> and <code>reason</code>. top is 1 to 20, 5 when missing", "q_similar"),
    ("A question in plain words", "question", '{"question": "Which suppliers supply the rotor seal?"}', "<code>matched</code> nodes, numbered <code>nodes</code> (N1 onwards) and <code>edges</code> (E1 onwards), <code>answer</code> that cites them when the model rules allow one, else <code>answer_note</code>", "q_question"),
]


def block(value) -> str:
    return f"<pre>{e(json.dumps(value, indent=1, ensure_ascii=False))}</pre>"


def routes_html() -> str:
    out, group = [], None
    for g, method, path, who, request, answer, check in R:
        if g != group:
            if group:
                out.append("</tbody></table>")
            out.append(f"<h3>{e(g)}</h3><table class='routes'><thead><tr><th>Method and path</th><th>Who</th><th>Request</th><th>Answer</th><th>Checked on {SENT_ON}</th></tr></thead><tbody>")
            group = g
        if check in CALLS:
            c = CALLS[check]
            checked = f"Sent: {c['status']}"
        else:
            checked = e(check)
        out.append(f"<tr><td><code>{method} {e(path)}</code></td><td>{e(who)}</td><td>{request}</td><td>{answer}</td><td>{checked}</td></tr>")
    out.append("</tbody></table>")
    return "\n".join(out)


def tools_html() -> str:
    rows = []
    for name, t in sorted(CONTRACT["tools"].items()):
        inp = t["input"]
        req = set(inp.get("required") or [])
        fields = ", ".join(f"<code>{k}</code>{'' if k in req else ' (if wanted)'}" for k in inp.get("properties", {})) or "Nothing"
        caller = {"person": "An end user", "service": "The application itself", "either": "Either"}[t["caller"]]
        purposes = ", ".join(t["purposes"]) if isinstance(t["purposes"], list) else "Any purpose of the application"
        mcp = "API only" if name == "import" else "REST and MCP"
        rows.append(f"<tr><td><code>{name}</code></td><td>{e(t['summary'])}</td><td>{caller}</td><td>{e(purposes)}</td><td>{fields}</td><td>{mcp}</td></tr>")
    return ("<table class='routes'><thead><tr><th>Tool</th><th>What it gives</th><th>Called for</th><th>Purposes</th><th>Input</th><th>Reached by</th></tr></thead><tbody>"
            + "\n".join(rows) + "</tbody></table>")


def kinds_html() -> str:
    rows = "\n".join(f"<tr><td>{e(want)}</td><td><code>{e(body)}</code></td><td>{gives}</td></tr>" for want, _, body, gives, _ in KINDS)
    cards = []
    for want, kind, _, _, cid in KINDS:
        c = CALLS[cid]
        cards.append(f"<details class='card'><summary><b>{e(want)}</b>: <code>{kind}</code>, the answer recorded on {SENT_ON}</summary>"
                     f"<p class='note'>Request</p>{block(c['body'])}<p class='note'>Answer, {c['status']}</p>{block(trim(c['response']))}</details>")
    return (f"<table class='routes'><thead><tr><th>What is asked</th><th>Body of the query</th><th>What comes back</th></tr></thead><tbody>{rows}</tbody></table>"
            + "\n".join(cards))


CSS = r"""
:root{color-scheme:light;--page:#f9f9f7;--surface:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--muted:#6f6d67;--border:rgba(11,11,11,.12);--s1:#2a78d6;--s2:#eb6834;--s3:#1baf7a;--wash:#eaf2fc;--code:#f0efea;--axis:#c3c2b7}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#a09e96;--border:rgba(255,255,255,.12);--s1:#3987e5;--s2:#ef7a4a;--s3:#27c08a;--wash:#15243a;--code:#232321;--axis:#383835}}
:root[data-theme="dark"]{color-scheme:dark;--page:#0d0d0d;--surface:#1a1a19;--ink:#f0efec;--ink2:#c3c2b7;--muted:#a09e96;--border:rgba(255,255,255,.12);--s1:#3987e5;--s2:#ef7a4a;--s3:#27c08a;--wash:#15243a;--code:#232321;--axis:#383835}
*{box-sizing:border-box}body{margin:0;background:var(--page);color:var(--ink);font:15px/1.55 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:28px;line-height:1.2;margin:0 0 6px}h2{font-size:21px;margin:30px 0 8px;padding-top:6px;border-top:1px solid var(--border)}h3{font-size:16px;margin:22px 0 6px}
p{margin:8px 0;color:var(--ink2)}ul,ol{margin:8px 0 8px 20px;color:var(--ink2)}li{margin:4px 0}b,strong{color:var(--ink)}
.sub{color:var(--ink2);font-size:16px;margin:0 0 16px}
.tabs{display:flex;flex-wrap:wrap;gap:6px;margin:12px 0 18px;border-bottom:1px solid var(--border);padding-bottom:10px}
.tab{background:var(--surface);color:var(--ink2);border:1px solid var(--border);border-radius:999px;padding:7px 14px;font:600 13.5px system-ui,sans-serif;cursor:pointer}
.tab[aria-selected="true"]{background:var(--s1);color:#fff;border-color:var(--s1)}.tab:hover{border-color:var(--s1)}
.panel{display:none}.panel.on{display:block}
.card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 16px;margin:10px 0}
details.card summary{cursor:pointer;color:var(--ink2)}
table{width:100%;border-collapse:collapse;font-size:13.5px;margin:10px 0;background:var(--surface)}th,td{text-align:left;vertical-align:top;padding:7px 10px;border-bottom:1px solid var(--border)}
th{background:var(--page);color:var(--ink);font-weight:600}td{color:var(--ink2)}
table.routes td:first-child{min-width:230px}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--code);padding:1px 5px;border-radius:4px;color:var(--ink);word-break:break-word}
pre{margin:6px 0;white-space:pre-wrap;word-break:break-word;font:12px/1.45 ui-monospace,Menlo,monospace;color:var(--ink);background:var(--code);padding:10px;border-radius:8px;max-height:460px;overflow:auto}
.hl{background:var(--wash);border:1px solid var(--s1);border-radius:12px;padding:12px 16px;margin:14px 0}.hl h3{margin:0 0 6px;color:var(--s1)}.hl ul{margin:0;padding-left:20px}
.note{font-size:13px;color:var(--muted)}
svg.diagram{width:100%;height:auto;display:block}svg.diagram .bx{fill:var(--surface);stroke:var(--axis);stroke-width:1.5}svg.diagram .hot{fill:var(--wash);stroke:var(--s1);stroke-width:2}
svg.diagram .t{fill:var(--ink);font:600 14px system-ui,sans-serif}svg.diagram .s{fill:var(--ink2);font:12.5px system-ui,sans-serif}svg.diagram .ln{fill:none;stroke:var(--ink2);stroke-width:1.6}svg.diagram .ah{fill:var(--ink2)}
.try{display:grid;grid-template-columns:330px 1fr;gap:16px}@media(max-width:900px){.try{grid-template-columns:1fr}table{display:block;overflow-x:auto}}
.calls h4{margin:14px 0 6px;font-size:13px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em}
.calls button{display:block;width:100%;text-align:left;margin:4px 0;background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:8px;padding:7px 10px;font:13px system-ui,sans-serif;cursor:pointer}
.calls button:hover,.calls button[aria-pressed="true"]{border-color:var(--s1);background:var(--wash)}
.calls button small{display:block;color:var(--muted);font:11.5px ui-monospace,Menlo,monospace;margin-top:2px;word-break:break-all}
.show{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:12px 16px;position:sticky;top:12px;max-height:92vh;overflow:auto}
.status{display:inline-block;margin-left:8px;padding:0 8px;border-radius:999px;font-size:12px;font-weight:600;border:1px solid currentColor}.status.ok{color:var(--s3)}.status.bad{color:var(--s2)}
.copy{background:var(--surface);color:var(--ink);border:1px solid var(--border);border-radius:6px;padding:3px 10px;font:600 12px system-ui,sans-serif;cursor:pointer;float:right}
dl.gl{display:grid;grid-template-columns:220px 1fr;gap:6px 18px;margin:10px 0}dl.gl dt{font-weight:600;color:var(--ink)}dl.gl dd{margin:0;color:var(--ink2)}@media(max-width:700px){dl.gl{grid-template-columns:1fr}}
"""

JS = r"""
const tabs=document.querySelectorAll('.tab'),panels=document.querySelectorAll('.panel')
tabs.forEach(t=>t.addEventListener('click',()=>{tabs.forEach(x=>x.setAttribute('aria-selected',x===t?'true':'false'));panels.forEach(p=>p.classList.toggle('on',p.id===t.dataset.tab));try{history.replaceState(null,'','#'+t.dataset.tab)}catch(_){}}))
const want=location.hash.slice(1);if(want){const t=[...tabs].find(x=>x.dataset.tab===want);if(t)t.click()}
const calls=JSON.parse(document.getElementById('trydata').textContent)
const list=document.getElementById('calls'),show=document.getElementById('show')
let group=null
calls.forEach((c,i)=>{if(c.group!==group){group=c.group;const h=document.createElement('h4');h.textContent=group;list.appendChild(h)}
 const b=document.createElement('button');b.type='button';b.dataset.i=i;b.setAttribute('aria-pressed','false')
 const strong=document.createElement('span');strong.textContent=c.title;const small=document.createElement('small');small.textContent=c.line
 b.append(strong,small);b.addEventListener('click',()=>pick(i));list.appendChild(b)})
function el(tag,cls,text){const x=document.createElement(tag);if(cls)x.className=cls;if(text!==undefined)x.textContent=text;return x}
function pick(i){const c=calls[i];document.querySelectorAll('#calls button').forEach(b=>b.setAttribute('aria-pressed',b.dataset.i==String(i)?'true':'false'))
 show.replaceChildren()
 const h=el('h3',null,c.title);const st=el('span','status '+(c.status<300?'ok':'bad'),String(c.status));h.appendChild(st);show.appendChild(h)
 show.appendChild(el('p',null,c.why))
 show.appendChild(el('p','note','Request'));show.appendChild(el('pre',null,c.line+'\nAuthorization: '+c.auth+(c.body!==null&&c.body!==undefined?'\n\n'+JSON.stringify(c.body,null,1):'')))
 const cp=el('button','copy','Copy');cp.type='button';cp.addEventListener('click',()=>{try{navigator.clipboard.writeText(c.curl);cp.textContent='Copied'}catch(_){cp.textContent='Select and copy'}})
 const lab=el('p','note','curl, for a terminal');lab.appendChild(cp);show.appendChild(lab);show.appendChild(el('pre',null,c.curl))
 show.appendChild(el('p','note','Answer of the running API, '+c.status+'. Long lists show their first 3 items'));show.appendChild(el('pre',null,JSON.stringify(c.answer,null,1)))}
pick(0)
"""


def page() -> str:
    check_routes()
    counts = {}
    for g, *_ in R:
        counts[g] = counts.get(g, 0) + 1
    group_list = ", ".join(f"{g.split(' (')[0].lower()} {n}" for g, n in counts.items())
    tools = sorted(CONTRACT["tools"])
    mcp_tools = [t for t in tools if t != "import"]
    node_tools = ["health", "describe_capabilities", "search", "summarize", "find_experts", "lookup", "aggregate", "export_graph", "request_access"]
    sent = sum(1 for *_, check in R if check in CALLS)
    tools_sent = sorted({c['path'].rsplit('/', 1)[1] for c in CALLS.values() if c['path'].startswith('/api/v1/context/') and c['path'] != '/api/v1/context/contract'})
    trydata = json.dumps(try_data(), ensure_ascii=False).replace("</", "<\\/")
    diagram = f"""<svg class="diagram" viewBox="0 0 1080 250" role="img" aria-label="Three ways in: people, applications and agents reach the API or the MCP gateway, which read the company nodes, the mesh graph and the ingested context graphs">
<defs><marker id="ar" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class="ah"/></marker></defs>
<rect x="10" y="20" width="230" height="58" rx="8" class="bx"/><text x="125" y="45" text-anchor="middle" class="t">People and scripts</text><text x="125" y="64" text-anchor="middle" class="s">token from sign-in</text>
<rect x="10" y="96" width="230" height="58" rx="8" class="bx"/><text x="125" y="121" text-anchor="middle" class="t">Applications</text><text x="125" y="140" text-anchor="middle" class="s">service token and envelope</text>
<rect x="10" y="172" width="230" height="58" rx="8" class="bx"/><text x="125" y="197" text-anchor="middle" class="t">AI agents</text><text x="125" y="216" text-anchor="middle" class="s">service token over MCP</text>
<rect x="330" y="40" width="300" height="96" rx="8" class="hot"/><text x="480" y="70" text-anchor="middle" class="t">NeuralMesh API, port 8000</text><text x="480" y="92" text-anchor="middle" class="s">/api/v1/auth, /mesh, /context-graphs, /help</text><text x="480" y="112" text-anchor="middle" class="s">/api/v1/context/&#123;tool&#125; for applications</text>
<rect x="330" y="172" width="300" height="58" rx="8" class="bx"/><text x="480" y="197" text-anchor="middle" class="t">MCP gateway, port 8100</text><text x="480" y="216" text-anchor="middle" class="s">13 context tools</text>
<rect x="730" y="20" width="340" height="58" rx="8" class="bx"/><text x="900" y="45" text-anchor="middle" class="t">Company nodes, ports 8101 to 8108</text><text x="900" y="64" text-anchor="middle" class="s">documents, search, policy, audit of each company</text>
<rect x="730" y="96" width="340" height="58" rx="8" class="bx"/><text x="900" y="121" text-anchor="middle" class="t">Mesh graph</text><text x="900" y="140" text-anchor="middle" class="s">entities and links, no document text</text>
<rect x="730" y="172" width="340" height="58" rx="8" class="bx"/><text x="900" y="197" text-anchor="middle" class="t">Ingested context graphs</text><text x="900" y="216" text-anchor="middle" class="s">the JSON graphs people wrote</text>
<path d="M240 49 H330" class="ln" marker-end="url(#ar)"/><path d="M240 125 H330" class="ln" marker-end="url(#ar)"/><path d="M240 201 H330" class="ln" marker-end="url(#ar)"/>
<path d="M630 70 H730" class="ln" marker-end="url(#ar)"/><path d="M630 110 H680 V125 H730" class="ln" marker-end="url(#ar)"/><path d="M630 125 H660 V201 H730" class="ln" marker-end="url(#ar)"/><path d="M630 201 H700 V150 H730" class="ln" marker-end="url(#ar)"/>
</svg>"""
    glossary = [
        ("API", "Application programming interface: the routes a program calls to use NeuralMesh."),
        ("Route", "One method and path of the API, for example POST /api/v1/context-graphs/{graph_id}/query."),
        ("Bearer token", "A signed text sent in the Authorization header as Bearer and the token. Sign-in gives one that is valid for 12 hours."),
        ("Service token", "The token of a registered application, with the role context_client. In development it comes from python -m scripts.issue_service_token in app/."),
        ("Envelope", "The one request body of the context contract: schema_version, tool, purpose, caller and input."),
        ("Context contract", "The published set of 14 tools that applications call, version 1.1. Its sha256 lets an application see that it changed."),
        ("Purpose", "Why a call is made: problem_solving, compliance, bid_support, learning, career_mobility or inspection. Company nodes release data by purpose."),
        ("Caller", "In the envelope, the end user's company (subsidiary), roles and, for a person, an opaque user reference (user_ref)."),
        ("Status", "The first word of a contract answer: ok, partial, no_evidence, blocked, needs_input or refused."),
        ("Problem", "The part of an answer that says what went wrong and what is needed, with a code such as not_found or invalid_input."),
        ("Mesh", "The company nodes of the group joined through one central service."),
        ("Company node", "The MCP server one company runs over its own documents, with its own policy and audit. Ports 8101 to 8108 in development. Not the same as a node of a graph."),
        ("Mesh graph", "The central graph of entities and links taken from the company nodes and the group vocabulary. It holds no document text."),
        ("Entity", "One item of the mesh graph: a company, an item, a document, a concept, a skill, a role, an expert or an asset."),
        ("Context graph", "A named graph of related inputs. Uploaded ones are made by Upload input from files. Ingested ones are written as JSON on Ingest data."),
        ("Node", "One thing in an ingested context graph, with a type and a name, for example a Supplier named Supplier X."),
        ("Edge", "One relationship between two nodes, with a type, a source and a target, for example Supplier X SUPPLIES Rotor seal RS-200. The page shows edges as links."),
        ("Hop", "One edge walked from a node to its neighbour."),
        ("Path", "A chain of edges that joins two nodes. The path query gives the shortest ones."),
        ("Jaccard index", "Shared neighbours of two nodes divided by all the neighbours of the two, from 0 to 1. The similar query ranks by it."),
        ("Sensitivity", "Public, Internal, Confidential or Restricted. A missing one is Restricted."),
        ("Sharing", "company: only the owning company and mesh admins see an ingested graph. group: every company sees it."),
        ("Never-leave", "Items shown as metadata only to other companies, such as formulations and pre-results finance."),
        ("Synthetic", "Data invented for testing. A cloud model may read synthetic data in development only."),
        ("Stand-in model", "The local model of the development stack. It writes answers from the evidence by fixed rules, with no cloud call."),
        ("MCP", "Model Context Protocol, the protocol AI agents use to call tools. The gateway serves it as Streamable HTTP."),
        ("curl", "A command-line program that sends one HTTP request. Each Try entry gives the curl command of its call."),
    ]
    gl = "\n".join(f"<dt>{e(t)}</dt><dd>{e(d)}</dd>" for t, d in glossary)
    sent_list = ", ".join(sorted({CALLS[c]['id'] for c in CALLS}))
    _ = sent_list
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RPG NeuralMesh API</title>
<meta name="description" content="Every route of the RPG NeuralMesh API with its request and answer, the queries of a context graph, a tab with real requests and answers to try, and a glossary.">
<style>{CSS}</style></head><body><main>
<h1>The RPG NeuralMesh API</h1>
<p class="sub">NeuralMesh answers questions across the RPG companies from each company's own node, and keeps the context graphs people ingest as JSON. This page lists every route with its request and answer, shows how to query a context graph, and gives real requests and answers to try.</p>
<div class="tabs" role="tablist">
<button class="tab" role="tab" data-tab="access" aria-selected="true">How to access</button>
<button class="tab" role="tab" data-tab="query" aria-selected="false">Query a context graph</button>
<button class="tab" role="tab" data-tab="routes" aria-selected="false">All routes</button>
<button class="tab" role="tab" data-tab="try" aria-selected="false">Try the API</button>
<button class="tab" role="tab" data-tab="glossary" aria-selected="false">Glossary</button>
</div>

<section class="panel on" id="access">
<h2>How to access NeuralMesh</h2>
<div class="hl"><h3>Highlights</h3><ul>
<li>{len(R)} REST routes in {len(counts)} groups ({group_list}), listed on All routes.</li>
<li>People sign in and send the token they get. Applications send a service token and one envelope to the {len(tools)} tools of the context contract, {len(mcp_tools)} of which AI agents also reach over MCP.</li>
<li>An ingested context graph is queried by its id in seven ways: overview, nodes, node, edges, path, similar and a question in plain words.</li>
<li>Every answer is scoped to the caller: a graph with sharing company answers 404 to other companies, and never-leave items stay with their company.</li>
<li>{sent} of the {len(R)} routes and {len(tools_sent)} of the {len(tools)} tools ({', '.join(tools_sent)}) were sent to the running development API on {SENT_ON}. The routes that change data were not sent. Every answer on this page is one the API gave, on invented data.</li>
</ul></div>
<h3>Three ways in</h3>
{diagram}
<table><thead><tr><th>Way in</th><th>For</th><th>How it signs</th><th>Address in development</th><th>What it covers</th></tr></thead><tbody>
<tr><td><b>REST for people</b></td><td>People and scripts that act for a person</td><td><code>Authorization: Bearer</code> and the token of <code>POST /api/v1/auth/signin</code></td><td><code>{BASE}/api/v1</code></td><td>Ask the mesh, search the mesh graph, uploaded and ingested context graphs, governance, the dashboard, the help chat</td></tr>
<tr><td><b>REST for applications</b></td><td>Registered applications: SkillForge, Snap and Score</td><td>Service token with the role context_client, and the envelope</td><td><code>{BASE}/api/v1/context/&#123;tool&#125;</code></td><td>The {len(tools)} tools of the context contract</td></tr>
<tr><td><b>MCP</b></td><td>AI agents</td><td>The same service token</td><td><code>http://127.0.0.1:8100/mcp</code></td><td>{len(mcp_tools)} tools: every tool except import</td></tr>
</tbody></table>
<p>A service token also opens the ingested context graph routes: its company is group, so it reads the graphs shared with the group and cannot ingest. The company nodes answer the centre only. Their tools are listed at the end of All routes.</p>
<h3>Start in three calls</h3>
<p>1. Sign in. The answer holds <code>access_token</code>.</p>
<pre>curl -s -X POST '{BASE}/api/v1/auth/signin' -H 'Content-Type: application/json' -d '{{"email": "presenter@neuralmesh.local", "password": "&lt;password&gt;"}}'
TOKEN=&lt;the access_token of the answer&gt;</pre>
<p>2. Ask the mesh a question.</p>
<pre>{e(curl(CALLS['ask']))}</pre>
<p>3. Query a context graph by its id. The id comes from <code>GET /api/v1/context-graphs</code> or from the answer of the ingest.</p>
<pre>{e(curl(CALLS['q_path']))}</pre>
<p>The API also describes itself at <code>{BASE}/docs</code>: open it in a browser, press Authorize, paste the token, and every route can be sent from there.</p>
<h3>Rules every call follows</h3>
<ul>
<li>Bodies and answers are JSON, except the file of an upload (a form) and a download with <code>format</code>.</li>
<li>The token goes in <code>Authorization: Bearer &lt;token&gt;</code>. A person's token is valid for 12 hours.</li>
<li>200 or 201 is a good answer. 401 is a missing or expired token, 403 a role the route needs, 404 an id that is not there or not shown to the caller, 409 a name that fits several nodes, 413 a body over 8,000,000 bytes, 422 a field to fix, with the reason, and 503 a company node that did not answer.</li>
<li>A contract call answers 200 also when it refuses: its status says refused and its problem says what is needed.</li>
<li>Each query of an ingested graph writes one line to the central audit: the caller, the graph id and the kind of query, never the question.</li>
</ul>
</section>

<section class="panel" id="query">
<h2>Query a context graph</h2>
<p>An ingested context graph is a graph a company wrote as JSON, with its own node types and edge types. It is kept with an id such as <code>cg-1cc11e1e</code>, and every query is <code>POST /api/v1/context-graphs/&#123;graph_id&#125;/query</code> with one key in the body. A node is named by its id, its name or another name, in any case. A name that fits several nodes answers 409 with the candidates, and a name that fits none answers 404 with the closest names. <code>relationships</code> is read as another name for <code>edges</code>.</p>
{kinds_html()}
<h3>How a written answer is made</h3>
<p>For a question, code finds the nodes the question names and the edges around them and numbers them N1 and E1 onwards. The answer model writes an answer only when the model rules allow it for the graph's sensitivity and synthetic flag, and every sentence must cite a given node or edge. A graph with synthetic false never reaches a cloud model. On the development stack the answer model is the stand-in model on the same machine.</p>
<h3>Keeping a graph: the JSON</h3>
<table><thead><tr><th>Field</th><th>Needed</th><th>Meaning</th></tr></thead><tbody>
<tr><td><code>graph</code></td><td>Yes</td><td>The name, 3 to 80 characters, one per company</td></tr>
<tr><td><code>company</code></td><td>Yes</td><td>The company that owns the data, by id or name. A person writes their own company, a mesh admin any company</td></tr>
<tr><td><code>nodes</code></td><td>Yes</td><td>Each with <code>type</code> and <code>name</code>. If wanted: <code>id</code> (made from type and name when missing), <code>aliases</code>, <code>properties</code></td></tr>
<tr><td><code>edges</code></td><td>Yes, can be empty</td><td>Each with <code>type</code>, <code>source</code> and <code>target</code> (node ids, or names). If wanted: <code>id</code> (made from the type when missing), <code>properties</code></td></tr>
<tr><td><code>sensitivity</code></td><td>No</td><td>Public, Internal, Confidential or Restricted. Restricted when missing</td></tr>
<tr><td><code>sharing</code></td><td>No</td><td>company (when missing) or group. group needs Internal or Public. A graph of Others needs group</td></tr>
<tr><td><code>synthetic</code></td><td>No</td><td>false when missing, so the data is treated as real. Only a mesh admin writes true</td></tr>
<tr><td><code>description</code></td><td>No</td><td>Up to 1,000 characters</td></tr>
<tr><td><code>graph_id</code></td><td>No</td><td>The id of a graph to replace. It keeps its id and its company</td></tr>
</tbody></table>
<p>When a needed field is missing or wrong, the answer is 422 with <code>problems</code>, one per place to fix, and nothing is kept. The samples in <code>Docs - rpg neuralmesh/01_Inputs_for_Testing/Ingest_Data_Samples</code> show each case.</p>
<h3>Uploaded context graphs</h3>
<p>A graph made by Upload input lives in the mesh graph. It is read with <code>GET /api/v1/mesh/uploads/graphs/&#123;graph_id&#125;</code>, written out in the JSON structure with <code>POST /api/v1/mesh/uploads/json-templates/render</code>, and its entities are found with the mesh graph search. The query route of ingested graphs does not read it.</p>
</section>

<section class="panel" id="routes">
<h2>All routes</h2>
<p>Every REST route of the API, read from the code. The last column says whether the route was sent to the running development API on {SENT_ON} and with which status, or why it was not.</p>
{routes_html()}
<h3>The {len(tools)} tools of the context contract</h3>
<p>Each tool is <code>POST /api/v1/context/&#123;tool&#125;</code> with the envelope, and the same tool over MCP takes the envelope without the tool name. SkillForge may call role_context, skill_context, ask, learning_sources, find_mentors, vocabulary_export, entity, related, similar and import. Snap and Score has its own list in its registry file.</p>
{tools_html()}
<h3>The tools of the company nodes</h3>
<p>Each company node serves these {len(node_tools)} MCP tools to the centre only, with a node token the centre makes for each call: {", ".join(f"<code>{t}</code>" for t in node_tools)}. Applications reach company data through the routes and tools above, never through a company node directly.</p>
</section>

<section class="panel" id="try">
<h2>Try the API: real requests and answers</h2>
<p>Each button shows one request, its curl command and the answer the running development API gave on {SENT_ON}, on invented data. The page itself sends nothing, so it works from a file. To send a call, run its curl command in a terminal after setting TOKEN (sign in), KEC_TOKEN (sign in as kec.expert@neuralmesh.local) or SERVICE_TOKEN (python -m scripts.issue_service_token skillforge in app/), or use <code>{BASE}/docs</code>.</p>
<div class="try"><div class="calls" id="calls"></div><div class="show" id="show" aria-live="polite"></div></div>
</section>

<section class="panel" id="glossary">
<h2>Glossary</h2>
<dl class="gl">{gl}</dl>
</section>
</main>
<script type="application/json" id="trydata">{trydata}</script>
<script>{JS}</script>
</body></html>"""


if __name__ == "__main__":
    OUT.write_text(page(), encoding="utf-8")
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
