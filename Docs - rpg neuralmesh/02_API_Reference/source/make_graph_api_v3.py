"""Make the context graph API guide and workbook, version 3, beside this folder:

    RPG_NeuralMesh_Context_Graph_API_v3.html   tabs Start here, Inputs and limits, API details, Try the API, Planned APIs
    RPG_NeuralMesh_Context_Graph_API_v3.xlsx   sheets Steps, Inputs and limits, APIs, JSON fields, Ask kinds, Errors, Planned APIs

A short guide for the team of another application: five steps with one request and one short answer each, the two kinds
of input with their limits, the three APIs (create, ask, read a graph), and the planned APIs that take the input from
Azure Blob storage, marked as not built. Both files come from the lists below, so they cannot differ. The examples are
answers of the running API from graph_recorded.json (record_graph_calls.py), cut to the fields a reader needs. Needs
openpyxl. Run from this folder:  python make_graph_api_v3.py
"""
from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_api_page as v1page  # noqa: E402  the page style and trim
import make_api_sheet as v1sheet  # noqa: E402  the query kinds, the JSON fields and the table writer

OUT_HTML = HERE.parent / "RPG_NeuralMesh_Context_Graph_API_v3.html"
OUT_XLSX = HERE.parent / "RPG_NeuralMesh_Context_Graph_API_v3.xlsx"
CALLS = {c["id"]: c for c in json.loads((HERE / "graph_recorded.json").read_text(encoding="utf-8"))}
RECORDED_ON = "12 November 2026"
BASE = v1page.BASE
e = html.escape
J = lambda value: json.dumps(value, indent=1, ensure_ascii=False)  # noqa: E731


def pick(value: dict, *keys: str) -> dict:
    return {k: value[k] for k in keys if k in value}


def _examples() -> dict[str, tuple[str, str]]:
    """(request, answer) of each step, from the recorded calls, cut to the fields a reader needs."""
    signin, check, refused, ask, read = (CALLS[k] for k in ("signin", "cg_check", "cg_refused", "q_question", "cg_get"))
    auth = "\nAuthorization: Bearer <token>\n\n"
    body = check["body"]  # the first 2 nodes and the first edge, so the example stays short
    sample = {**{k: v for k, v in body.items() if k not in ("nodes", "edges")}, "nodes": body["nodes"][:2] + ["..."], "edges": body["edges"][:1] + ["..."]}
    q = ask["response"]
    r = read["response"]
    return {
        "signin": ("POST /api/v1/auth/signin\n\n" + J(signin["body"]), J(pick(signin["response"], "access_token", "token_type"))),
        "check": ("POST /api/v1/context-graphs?check=true" + auth + J(sample),
                  J({"graph": pick(check["response"]["graph"], "id", "name", "company_name", "nodes", "edges", "sensitivity", "sharing"),
                     "checked_only": True, **pick(check["response"], "filled", "defaults")})),
        "refused": ("", J({"detail": refused["response"]["detail"], "problems": refused["response"]["problems"][:3]})),
        "create": ("POST /api/v1/context-graphs" + auth + "the same JSON", ""),
        "ask": (f"POST {ask['path']}" + auth + J(ask["body"]),
                J({**pick(q, "answer", "answer_note"), "edges": [pick(x, "ref", "text") or pick(x, "ref", "type") for x in q["edges"][:3]]})),
        "read": (f"GET {read['path']}\nAuthorization: Bearer <token>",
                 J({**pick(r, "graph_id", "graph", "company", "sensitivity", "sharing"), "nodes": v1page.trim(r["nodes"])[:2] + ["..."], "edges": v1page.trim(r["edges"])[:1] + ["..."]})),
    }


GRAPH_ID = CALLS["cg_get"]["response"]["graph_id"]
STEPS = [  # (title, what to do, example key, what comes back)
    ("Sign in", "Send your email and password once. Keep access_token and send it with every other call as Authorization: Bearer <token>. It is valid for 12 hours.",
     "signin", "access_token, the token for the next calls."),
    ("Check your JSON", "Send the graph with ?check=true. Nothing is kept. Fix each place listed under problems and send it again, until the answer has no problems.",
     "check", "The counts of the graph, what was filled in and the defaults used. graph.id is null, because nothing is kept."),
    ("Create the graph", "Send the same JSON without check. The graph is kept.",
     "create", f"Status 201 and the same answer, now with graph.id, for example {GRAPH_ID}. Keep this id."),
    ("Ask the graph", "Send a question, or one of the six other query kinds, to the graph by its id.",
     "ask", "The edges that answer the question, and a written answer when the model rules allow one for the graph. If not, answer_note says why."),
    ("Read or change the graph", "Read the whole graph by its id. To change it, change this JSON and send it to step 3. It carries its graph_id, so the graph is replaced, not made twice.",
     "read", "The graph in the same format as you sent it, with its graph_id."),
]

INPUTS = [  # (input, how it is sent, limits)
    ("Documents (files)", "Send one folder for your application, with one subfolder for each topic. A mesh admin loads it on the Upload input page. Each subfolder becomes one context graph. No API takes files from another application today.",
     ".txt, .md, .csv, .json, .pdf or .docx. Up to 20 MB for each file. At least 40 characters of text. A PDF must hold text that can be selected, not a scanned page."),
    ("A graph as JSON", "Send it yourself with the Create API (step 3). One JSON for each topic.",
     "Up to 8,000,000 bytes. Up to 5,000 nodes and 20,000 edges. Graph name of 3 to 80 characters. Needed: graph, company, nodes (type, name), edges (type, source, target)."),
]
LIMITS = [
    ("Token", "Valid for 12 hours. Sign in again after that."),
    ("Question", "Up to 2,000 characters."),
    ("Answer of a question", "Up to 30 nodes and 40 edges."),
    ("Answer of a nodes or edges query", "Up to 200 nodes and 500 edges."),
    ("Real data", "A graph without \"synthetic\": true is treated as real data. No cloud model reads it, so a question gets the nodes and edges without a written answer."),
]
WHO = [
    ("Mesh admin token", "Creates a graph for any company. Asks and reads every graph."),
    ("Company user token", "Creates a graph for their own company. Asks and reads the graphs of their company and the graphs shared with the group."),
    ("Application service token", "Asks and reads the graphs shared with the group. It cannot create a graph today."),
]
APIS = [
    ("1", "Create a graph", "POST", "/api/v1/context-graphs", "The graph as JSON. Add ?check=true to check it and keep nothing.",
     "graph (id, name, counts, sharing), filled, defaults, ignored, warnings", "201 created. 200 replaced, unchanged or checked. 422 refused"),
    ("2", "Ask a graph", "POST", "/api/v1/context-graphs/{graph_id}/query", "One query kind, for example {\"question\": \"...\"}.",
     "graph, kind and the answer of that kind", "200 answered. 404 not found. 422 wrong body"),
    ("3", "Read a graph", "GET", "/api/v1/context-graphs/{graph_id}", "None.",
     "graph_id, graph, company, sensitivity, sharing, nodes, edges", "200 read. 404 not found"),
]
ERRORS = [
    ("401", "No token, or the token is expired.", "Sign in again."),
    ("404", "No graph with this id is shown to your token, or the query names a node that is not in the graph.", "Check the graph id. For a node, use one of the close names the answer gives."),
    ("409", "The name in the query names more than one node.", "Send the id of one of the candidates the answer lists."),
    ("413", "The JSON has more than 8,000,000 bytes.", "Split the graph by topic."),
    ("422", "The JSON or the query body cannot be used. Nothing is kept.", "Fix each place listed under problems. Places count from 0, so nodes[0] is the first node."),
]
PLANNED_NOTE = "Planned. Not built yet. The paths and the fields can change when they are built. Today a large input is split by topic, or handed over as a folder."
PLANNED = [  # (name, method and path, what it will do, request, answer)
    ("Create a graph from a JSON file in Azure Blob storage", "POST /api/v1/context-graphs/from-storage",
     "For a JSON above the 8,000,000 byte limit. You put the JSON file in your Azure Blob container and send its URL with a read-only access signature that expires. "
     "NeuralMesh fetches the file, runs the same check as Create and keeps the graph.",
     J({"source_url": "https://<storage account>.blob.core.windows.net/<container>/onboarding_buddy/first_week.json?<access signature>", "check": False}),
     J({"graph": {"id": "cg-<8 characters>", "name": "Onboarding: first week", "nodes": 4200, "edges": 9100},
        "use": "/api/v1/context-graphs/cg-<8 characters>/query"})),
    ("Create graphs from a folder of files in Azure Blob storage", "POST /api/v1/context-graphs/from-storage-folder",
     "For documents. You put the folder of your application in your Azure Blob container, with one subfolder for each topic and the list file inputs.csv, and send the URL of the folder. "
     "NeuralMesh fetches the files, reads each one and makes one context graph for each subfolder.",
     J({"source_url": "https://<storage account>.blob.core.windows.net/<container>/onboarding_buddy/?<access signature>", "company": "Zensar"}),
     J({"status": "reading", "files": 12, "graphs": [{"id": "g-<8 characters>", "name": "Leave and attendance", "inputs": 2}]})),
]


TRY = [  # the recorded calls a reader can open, by API
    ("Sign in", ["signin"]),
    ("1 Create a graph", ["cg_check", "cg_refused"]),
    ("2 Ask a graph", ["q_question", "q_overview", "q_nodes", "q_node", "q_edges", "q_path", "q_similar", "q_missing", "q_scope"]),
    ("3 Read a graph", ["cg_get"]),
]
AUTH = {"person": "Bearer token of a mesh admin", "person (KEC)": "Bearer token of a KEC user", "none": "None"}


def try_data() -> list[dict]:
    from urllib.parse import urlencode
    out = []
    for group, ids in TRY:
        for cid in ids:
            c = CALLS[cid]
            line = f"{c['method']} {c['path']}" + ("?" + urlencode(c["params"]) if c.get("params") else "")
            out.append({"id": cid, "group": group, "title": c["title"], "why": v1page.WHY[cid], "line": line, "auth": AUTH[c["token"]],
                        "body": c.get("body"), "curl": v1page.curl(c), "status": c["status"], "answer": v1page.trim(c["response"])})
    return out


def fields() -> list[tuple]:
    words = {"graph_id": "The id of a graph to replace, as Read gives it. Without it a new graph is made."}
    return [(f[0], f[2], words.get(f[0], f[3]), f[5]) for f in v1sheet.FIELDS]


def kinds() -> list[tuple]:
    return [(k[0], k[2]) for k in v1sheet.QUERIES]


def check_facts() -> None:
    assert CALLS["cg_check"]["status"] == 200 and CALLS["cg_check"]["response"]["graph"]["id"] is None
    assert CALLS["cg_refused"]["status"] == 422 and CALLS["q_question"]["status"] == 200 and GRAPH_ID.startswith("cg-")
    everything = json.dumps([_examples(), STEPS, INPUTS, LIMITS, WHO, APIS, ERRORS, PLANNED, try_data()])
    assert "MeshPilot" not in everything and "eyJ" not in everything, "a password or a token"


def table(headers: list[str], rows: list, mono: set[int] = frozenset()) -> str:
    head = "".join(f"<th>{e(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{'<code>' + e(str(v)) + '</code>' if i in mono else e(str(v))}</td>" for i, v in enumerate(r)) + "</tr>" for r in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def page() -> str:
    check_facts()
    ex = _examples()
    steps = ""
    for i, (title, do, key, back) in enumerate(STEPS, 1):
        request, answer = ex[key]
        steps += (f'<div class="card"><h3>Step {i}: {e(title)}</h3><p>{e(do)}</p><p class="note">Request</p><pre>{e(request)}</pre>'
                  f'<p><b>What comes back.</b> {e(back)}</p>' + (f"<pre>{e(answer)}</pre>" if answer else ""))
        if key == "check":
            steps += f'<p class="note">When something has to be fixed, the answer is 422 and names each place</p><pre>{e(ex["refused"][1])}</pre>'
        steps += "</div>"
    start = (f"<p>Your application gives NeuralMesh its content as a graph, and then asks that graph. Every call goes to <code>{e(BASE)}</code> on the development stack. "
             "A body is JSON, sent with <code>Content-Type: application/json</code>.</p>" + steps)
    inputs = ("<h2>Two kinds of input</h2>" + table(["Input", "How it is sent", "Limits"], INPUTS)
              + "<h2>Other limits</h2>" + table(["What", "Limit"], LIMITS)
              + "<h2>Who may call what</h2>" + table(["Token", "What it may do"], WHO))
    details = ("<h2>The three APIs</h2>" + table(["", "API", "Method", "Path", "Body", "Answer", "Status codes"], APIS, {3})
               + "<h2>Fields of the graph JSON</h2>" + table(["Field", "Needed", "What it holds", "Example"], fields(), {0, 3})
               + "<h2>The seven ways to ask</h2><p>The body of Ask holds exactly one of these.</p>" + table(["What it asks", "Body"], kinds(), {1})
               + "<h2>Errors</h2>" + table(["Code", "What it means", "What to do"], ERRORS))
    planned = f'<div class="hl"><h3>Planned</h3><p>{e(PLANNED_NOTE)}</p></div>' + "".join(
        f'<div class="card"><h3>{e(name)}</h3><p><code>{e(path)}</code></p><p>{e(does)}</p><p class="note">Request (sample)</p><pre>{e(request)}</pre>'
        f'<p class="note">Answer (sample)</p><pre>{e(answer)}</pre></div>' for name, path, does, request, answer in PLANNED)
    calls = try_data()
    trying = (f"<p>Choose a call to see its request, its curl command and the answer the running API gave on {RECORDED_ON}. "
              f"The {len(calls)} calls are recorded, so nothing is sent from this page. To run one yourself, copy its curl command into a terminal, "
              "with your token in TOKEN.</p>"
              '<div class="try"><div class="calls" id="calls" aria-label="Calls"></div><div class="show" id="show" aria-live="polite"></div></div>')
    tabs = [("start", "Start here", start), ("inputs", "Inputs and limits", inputs), ("details", "API details", details), ("try", "Try the API", trying), ("planned", "Planned APIs", planned)]
    nav = "".join(f'<button type="button" class="tab" data-tab="{t}" aria-selected="{str(i == 0).lower()}">{e(name)}</button>' for i, (t, name, _) in enumerate(tabs))
    panels = "".join(f'<section class="panel{" on" if i == 0 else ""}" id="{t}">{body}</section>' for i, (t, _, body) in enumerate(tabs))
    trydata = json.dumps(calls, ensure_ascii=False).replace("</", "<\\/")
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>Context Graph API</title><style>{v1page.CSS}</style></head><body><main>"
            f'<h1>RPG NeuralMesh: Context Graph API</h1><p class="sub">Five steps to create a graph, ask it and read it. The examples are answers of the running API, recorded on {RECORDED_ON}.</p>'
            f'<div class="tabs" role="tablist">{nav}</div>{panels}</main><script type="application/json" id="trydata">{trydata}</script><script>{v1page.JS}</script></body></html>')


def workbook():
    from openpyxl import Workbook
    ex = _examples()
    wb = Workbook()
    wb.remove(wb.active)
    sheets = [  # one table on each sheet, so every sheet has one frozen header row
        ("Steps", "Five steps to create a graph, ask it and read it", ["Step", "What to do", "Request", "What comes back", "Answer (short)"],
         [[f"{i}. {title}", do, ex[key][0], back, ex[key][1]] for i, (title, do, key, back) in enumerate(STEPS, 1)], [22, 50, 54, 44, 60], {3, 5}),
        ("Inputs and limits", "The two kinds of input, the limits, and who may call what", ["Topic", "What applies", "Limits"],
         [list(x) for x in INPUTS] + [[a, b, ""] for a, b in LIMITS] + [[a, b, ""] for a, b in WHO], [28, 80, 70], set()),
        ("APIs", "The three APIs", ["#", "API", "Method", "Path", "Body", "Answer", "Status codes"], [list(a) for a in APIS], [4, 16, 8, 40, 44, 44, 40], {4}),
        ("JSON fields", "Fields of the graph JSON sent to Create", ["Field", "Needed", "What it holds", "Example"], [list(f) for f in fields()], [24, 14, 70, 40], {1, 4}),
        ("Ask kinds", "The seven ways to ask. The body of Ask holds exactly one", ["What it asks", "Body"], [list(k) for k in kinds()], [40, 90], {2}),
        ("Errors", "Status codes that are not a success", ["Code", "What it means", "What to do"], [list(x) for x in ERRORS], [8, 70, 70], set()),
        ("Planned APIs", PLANNED_NOTE, ["API", "Method and path", "What it will do", "Request (sample)", "Answer (sample)"],
         [[name, path, does, request, answer] for name, path, does, request, answer in PLANNED], [30, 44, 60, 60, 50], {2, 4, 5}),
    ]
    for name, note, headers, rows, widths, mono in sheets:
        ws = wb.create_sheet(name)
        v1sheet.title(ws, name, note)
        v1sheet.write_table(ws, 4, headers, rows, widths, mono)
    return wb


if __name__ == "__main__":
    text = page()
    prose = re.sub(r"<style>.*?</style>|<script[^>]*>.*?</script>|<(pre|code)>.*?</\1>", "", text, flags=re.S)
    assert ";" not in re.sub(r"&[a-z#0-9]+;", "", re.sub(r"<[^>]+>", "", prose)), "a semicolon in the prose"
    OUT_HTML.write_text(text, encoding="utf-8")
    workbook().save(OUT_XLSX)
    print(f"wrote {OUT_HTML.name} and {OUT_XLSX.name}")
