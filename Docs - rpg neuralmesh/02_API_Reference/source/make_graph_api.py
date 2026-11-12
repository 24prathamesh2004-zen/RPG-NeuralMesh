"""Make the context graph API page and workbook, version 2, beside this folder:

    RPG_NeuralMesh_Context_Graph_API_v2.html   tabs How to access, Graph APIs, Queries by graph id, Ingest JSON fields, Try the API
    RPG_NeuralMesh_Context_Graph_API_v2.xlsx   sheets Read me, Graph APIs, Queries by graph id, Ingest JSON fields, Errors

Both come from one list, APIS below, so the page and the workbook cannot differ. The list holds only the APIs behind
the three tabs of the Context graph page (Uploaded inputs, Upload input, Ingest data), the sign-in that gives the
token, and the query of a graph by its id. The wording of each route comes from the route rows of make_api_sheet.py,
with the changes of the evening of 2026-11-11 added here. The examples come from graph_recorded.json, written by
record_graph_calls.py. Needs openpyxl. Run from this folder:  python make_graph_api.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import make_api_page as v1page  # noqa: E402  the style, the script, trim and curl of the page
import make_api_sheet as v1sheet  # noqa: E402  the route rows, the query kinds, the JSON fields and the table writer

from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font  # noqa: E402

OUT_HTML = HERE.parent / "RPG_NeuralMesh_Context_Graph_API_v2.html"
OUT_XLSX = HERE.parent / "RPG_NeuralMesh_Context_Graph_API_v2.xlsx"
CALLS = {c["id"]: c for c in json.loads((HERE / "graph_recorded.json").read_text(encoding="utf-8"))}
SENT_ON = "11 November 2026"
BASE = v1page.BASE
e = html.escape
QUERY_TAB = "Queries by graph id"

# (page tab, method, path, recorded call, the request shown when the call is not sent because it changes data)
APIS = [
    ("Sign in", "POST", "/api/v1/auth/signin", "signin", None),
    ("Uploaded inputs", "GET", "/api/v1/mesh/uploads", "uploads", None),
    ("Uploaded inputs", "GET", "/api/v1/context-graphs", "cg_list", None),
    ("Uploaded inputs", "GET", "/api/v1/mesh/graph/search", "search", None),
    ("Uploaded inputs", "GET", "/api/v1/mesh/graph/entity/{entity_id}", "entity", None),
    ("Uploaded inputs", "GET", "/api/v1/mesh/uploads/graphs/{graph_id}", "upload_graph", None),
    ("Uploaded inputs", "POST", "/api/v1/mesh/uploads/json-templates/render", "render", None),
    ("Uploaded inputs", "GET", "/api/v1/context-graphs/{graph_id}/view", "cg_view", None),
    ("Uploaded inputs", "DELETE", "/api/v1/mesh/uploads/graphs/{graph_id}", None, "DELETE /api/v1/mesh/uploads/graphs/<graph id>"),
    ("Uploaded inputs", "DELETE", "/api/v1/mesh/uploads/{doc_id}", None, "DELETE /api/v1/mesh/uploads/<document id>"),
    ("Uploaded inputs", "DELETE", "/api/v1/context-graphs/{graph_id}", None, "DELETE /api/v1/context-graphs/<graph id>"),
    ("Upload input", "POST", "/api/v1/mesh/uploads/suggest", "suggest", None),
    ("Upload input", "GET", "/api/v1/mesh/uploads/items/{node_id}", "items", None),
    ("Upload input", "POST", "/api/v1/mesh/uploads", None,
     "POST /api/v1/mesh/uploads (a form)\nfile=@02_cable_joint_moisture_review.txt, node_id=raychem, datapoint=O-02, graph_id=g-d03155d7, synthetic=true"),
    ("Ingest data", "GET", "/api/v1/context-graphs/sample", "cg_sample", None),
    ("Ingest data", "POST", "/api/v1/context-graphs", "cg_check", None),
    ("Ingest data", "GET", "/api/v1/context-graphs/{graph_id}", "cg_get", None),
    (QUERY_TAB, "POST", "/api/v1/context-graphs/{graph_id}/query", "q_overview", None),
]
SERVICE = ". An application's service token sees only the graphs shared with the group"
EXTRA_WHO = {("GET", "/api/v1/context-graphs"): SERVICE, ("POST", "/api/v1/context-graphs/{graph_id}/query"): SERVICE}
EXTRA_DOES = {("GET", "/api/v1/mesh/graph/search"): " The one search box of Uploaded inputs calls it after a short pause, and shows an uploaded input it finds under its graph, once."}
EXTRA_BACK = {("GET", "/api/v1/mesh/uploads"): " Each upload says synthetic: true when it was sent as invented data, and false when it is real."}
RENAMED = [("See the tab Context graph queries.", f"See the tab {QUERY_TAB}.")]
TAB_WORK = [
    ("Uploaded inputs", "Sees the uploaded and the ingested graphs, searches them and the mesh graph in one box, opens a graph, an input or a topic, downloads a graph, and a mesh admin drops a graph or removes an input."),
    ("Upload input", "A mesh admin chooses a file, checks the fields read from it, picks the company's catalogue item and adds the file to a graph."),
    ("Ingest data", "Downloads the sample, writes or pastes the JSON of a graph, checks it, ingests it and gets the graph id."),
    (QUERY_TAB, "An application or a script asks an ingested graph by its id, with one of seven query bodies."),
]
TRY = [
    ("Sign in", ["signin"]),
    ("Uploaded inputs", ["uploads", "cg_list", "search", "entity", "upload_graph", "render", "cg_view"]),
    ("Upload input", ["suggest", "items"]),
    ("Ingest data", ["cg_sample", "cg_check", "cg_refused", "cg_get"]),
    (QUERY_TAB, ["q_overview", "q_nodes", "q_node", "q_edges", "q_path", "q_similar", "q_question", "q_missing", "q_scope"]),
]
WHY = {**v1page.WHY,
       "uploads": "Every uploaded document the person may see, and the context graphs they form. Each upload says whether it was sent as invented data.",
       "search": "The graph part of the one search on Uploaded inputs, for the word teardown: the 33 kV teardown document by its name and a concept by another name.",
       "entity": "One topic, Lot acceptance, with its links by type.",
       "upload_graph": "The uploaded graph 33 kV cable joint failures: its document, the entities around it and the links among them.",
       "suggest": "Read a file and propose the title, tags, kind and graph. Here the moisture review fits the graph 33 kV cable joint failures. Nothing is kept. Run the curl command in the folder that holds the file.",
       "items": "The catalogue items of Raychem RPG, each with its sharing rule. The upload's datapoint is one of these codes."}
AUTH = {"person": "Bearer token of the presenter (a mesh admin of Zensar)", "person (KEC)": "Bearer token of a KEC demo user", "none": "None"}
ERRORS = [
    ("200", "The call worked. A check with check=true answers 200 and keeps nothing."),
    ("201", "The call made something new: an uploaded document or an ingested graph."),
    ("401", "The token is missing, invalid or expired. Sign in again."),
    ("403", "The token is fine, but the route needs a role the person does not have, for example an upload by someone who is not a mesh admin."),
    ("404", "The id is not there, or it is not shown to the caller. The two read the same, so a hidden graph is never revealed. A node name that is not in the graph gives 404 with the closest names."),
    ("409", "A name fits several nodes of a graph. The answer lists the candidates, so the caller can send the id of one."),
    ("413", "The JSON sent to ingest or query is larger than 8,000,000 bytes."),
    ("422", "A field needs a change. The answer says which field and what is wrong, and nothing is kept."),
]


def rows() -> list[dict]:
    """One row per API, with the wording of the route rows and the changes of the evening of 2026-11-11."""
    v1 = {(r[1], r[2]): r for r in v1sheet.R}
    out = []
    for n, (tab, method, path, ref, example) in enumerate(APIS, 1):
        _, _, _, who, does, send, back, changes, _ = v1[(method, path)]
        who, does, back = who + EXTRA_WHO.get((method, path), ""), does + EXTRA_DOES.get((method, path), ""), back + EXTRA_BACK.get((method, path), "")
        for old, new in RENAMED:
            does, send = does.replace(old, new), send.replace(old, new)
        out.append({"n": n, "tab": tab, "method": method, "path": path, "who": who, "does": does, "send": send, "back": back,
                    "changes": changes, "ref": ref, "example": example})
    return out


def request_line(c: dict) -> str:
    return f"{c['method']} {c['path']}" + ("?" + urlencode(c["params"]) if c.get("params") else "")


def answer_text(value, limit: int = 1600) -> str:
    text = json.dumps(v1sheet.short(value), indent=1, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "\n... (shortened, the full answer is in source/graph_recorded.json)"


def try_data() -> list[dict]:
    out = []
    for group, ids in TRY:
        for cid in ids:
            c = CALLS[cid]
            out.append({"id": cid, "group": group, "title": c["title"], "why": WHY[cid], "line": request_line(c), "auth": AUTH[c["token"]],
                        "body": c.get("body"), "curl": v1page.curl(c), "status": c["status"], "answer": v1page.trim(c["response"])})
    return out


def block(value) -> str:
    return f"<pre>{e(json.dumps(value, indent=1, ensure_ascii=False))}</pre>"


def page(table: list[dict]) -> str:
    counts: dict[str, int] = {}
    for r in table:
        counts[r["tab"]] = counts.get(r["tab"], 0) + 1
    sent = sum(1 for r in table if r["ref"])
    trydata = json.dumps(try_data(), ensure_ascii=False).replace("</", "<\\/")
    api_rows = "\n".join(
        f"<tr><td>{r['n']}</td><td>{e(r['tab'])}</td><td><code>{r['method']} {e(r['path'])}</code></td><td>{e(r['who'])}</td><td>{e(r['does'])}</td>"
        f"<td>{e(r['send'])}</td><td>{e(r['back'])}</td><td>{e(r['changes'])}</td>"
        f"<td>{'Sent, ' + str(CALLS[r['ref']]['status']) + ', see Try the API' if r['ref'] else 'Not sent, it changes data: <code>' + e(r['example'].splitlines()[0]) + '</code>'}</td></tr>"
        for r in table)
    tab_rows = "\n".join(
        f"<tr><td>{e(tab)}</td><td>{e(work)}</td><td>{'<br>'.join('<code>' + r['method'] + ' ' + e(r['path']) + '</code>' for r in table if r['tab'] == tab)}</td></tr>"
        for tab, work in TAB_WORK)
    kinds = "\n".join(f"<tr><td>{e(want)}</td><td><code>{e(body)}</code></td><td>{e(back)}</td><td>{e(rules)}</td></tr>" for want, kind, body, back, rules, ref in v1sheet.QUERIES)
    cards = "\n".join(
        f"<details class='card'><summary><b>{e(want)}</b>: <code>{kind}</code>, the answer recorded on {SENT_ON}</summary>"
        f"<p class='note'>Request</p>{block(CALLS[ref]['body'])}<p class='note'>Answer, {CALLS[ref]['status']}</p>{block(v1page.trim(CALLS[ref]['response']))}</details>"
        for want, kind, body, back, rules, ref in v1sheet.QUERIES)
    fields = "\n".join(f"<tr><td><code>{e(f)}</code></td><td>{e(where)}</td><td>{e(need)}</td><td>{e(means)}</td><td>{e(missing)}</td><td><code>{e(ex)}</code></td></tr>"
                       for f, where, need, means, missing, ex in v1sheet.FIELDS)
    errors = "\n".join(f"<tr><td><b>{code}</b></td><td>{e(text)}</td></tr>" for code, text in ERRORS)
    signin = CALLS["signin"]
    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Context Graph API</title>
<meta name="description" content="The APIs behind the three tabs of the RPG NeuralMesh Context graph page and the query of a graph by its id, with the request and answer of each.">
<style>{v1page.CSS}</style></head><body><main>
<h1>RPG NeuralMesh Context Graph API</h1>
<p class="sub">The APIs behind the three tabs of the Context graph page (Uploaded inputs, Upload input and Ingest data) and the query of a graph by its id. Each comes with what to send and what comes back. The examples were sent on {SENT_ON} to the running development API, on invented data.</p>
<div class="tabs" role="tablist">
<button class="tab" role="tab" data-tab="access" aria-selected="true">How to access</button>
<button class="tab" role="tab" data-tab="apis" aria-selected="false">Graph APIs</button>
<button class="tab" role="tab" data-tab="query" aria-selected="false">{QUERY_TAB}</button>
<button class="tab" role="tab" data-tab="ingest" aria-selected="false">Ingest JSON fields</button>
<button class="tab" role="tab" data-tab="try" aria-selected="false">Try the API</button>
</div>

<section class="panel on" id="access">
<h2>How to call the context graph APIs</h2>
<div class="hl"><h3>In short</h3><ul>
<li>{len(table)} APIs: {', '.join(f'{t} {n}' for t, n in counts.items())}. Graph APIs lists what to send and what comes back for each.</li>
<li>Every call goes to the NeuralMesh API, <code>{BASE}</code> on the development stack, with the token in the header <code>Authorization: Bearer</code>. Only the sign-in needs no token.</li>
<li>A person signs in with email and password and gets a token valid for 12 hours. An application uses its service token, which sees only the graphs shared with the group and cannot ingest.</li>
<li>An uploaded graph is made from files on Upload input, and its id starts with <code>g-</code>. An ingested graph is written as JSON on Ingest data, and its id starts with <code>cg-</code>. The seven queries by graph id ask an ingested graph.</li>
<li>{sent} of the {len(table)} APIs were sent for the examples. The other {len(table) - sent} change data, an upload and three drops, so they show their request only.</li>
</ul></div>
<h3>Sign in</h3>
<p>The answer holds <code>access_token</code>. Write it into TOKEN, and every curl command on this page sends it.</p>
<pre>{e(v1page.curl(signin))}</pre>
<h3>The tabs of the page and their APIs</h3>
<table class="routes"><thead><tr><th>Page tab</th><th>What a person does there</th><th>APIs</th></tr></thead><tbody>{tab_rows}</tbody></table>
<h3>When something is wrong</h3>
<table><thead><tr><th>HTTP code</th><th>Meaning</th></tr></thead><tbody>{errors}</tbody></table>
</section>

<section class="panel" id="apis">
<h2>Graph APIs</h2>
<table class="routes"><thead><tr><th>No.</th><th>Page tab</th><th>Method and path</th><th>Who can call it</th><th>What it does</th><th>What to send</th><th>What comes back</th><th>Changes data</th><th>Example</th></tr></thead><tbody>
{api_rows}
</tbody></table>
</section>

<section class="panel" id="query">
<h2>{QUERY_TAB}</h2>
<p>Every query is <code>POST /api/v1/context-graphs/{{graph_id}}/query</code> with one of the seven bodies below. The answer starts with <code>graph</code> and <code>kind</code>. The examples ask the ingested graph <code>cg-1cc11e1e</code>, invented data. A node is named by its id, its name or another name, in any case.</p>
<table class="routes"><thead><tr><th>What is asked</th><th>Body</th><th>What comes back</th><th>Rules</th></tr></thead><tbody>{kinds}</tbody></table>
{cards}
</section>

<section class="panel" id="ingest">
<h2>Ingest JSON fields</h2>
<p>The JSON sent to <code>POST /api/v1/context-graphs</code>. Add <code>?check=true</code> to the address to check it and keep nothing. When a needed field is missing or wrong, the answer is 422 with each place to fix, and nothing is kept.</p>
<table><thead><tr><th>Field</th><th>Where</th><th>Needed</th><th>What it means</th><th>When it is missing</th><th>Example</th></tr></thead><tbody>{fields}</tbody></table>
</section>

<section class="panel" id="try">
<h2>Try the API: real requests and answers</h2>
<p>Each entry is a call sent on {SENT_ON}, with its curl command and the answer the running API gave. Set TOKEN with the sign-in, and KEC_TOKEN with the sign-in of a KEC user.</p>
<div class="try"><div class="calls" id="calls" aria-label="Calls"></div><div class="show" id="show" aria-live="polite"></div></div>
</section>
</main>
<script type="application/json" id="trydata">{trydata}</script>
<script>{v1page.JS}</script>
</body></html>
"""


def workbook(table: list[dict]) -> Workbook:
    wb = Workbook()
    ws = wb.active
    ws.title = "Read me"
    v1sheet.title(ws, "RPG NeuralMesh Context Graph API", f"The APIs behind the three tabs of the Context graph page and the query of a graph by its id. Examples sent on {SENT_ON}, on invented data.")
    sent = sum(1 for r in table if r["ref"])
    lines = [
        ("What is in it", f"{len(table)} APIs on the sheet Graph APIs, the seven query bodies on {QUERY_TAB}, the fields of the JSON to ingest on Ingest JSON fields, and the HTTP codes on Errors."),
        ("Where to call", f"The NeuralMesh API, {BASE} on the development stack. Every call sends the token in the header Authorization: Bearer, except the sign-in."),
        ("The token", "POST /api/v1/auth/signin with email and password gives access_token, valid for 12 hours. An application uses its service token, which sees only the graphs shared with the group and cannot ingest."),
        ("Two kinds of graph", "An uploaded graph is made from files on Upload input, and its id starts with g-. An ingested graph is written as JSON on Ingest data, and its id starts with cg-. The seven queries by graph id ask an ingested graph."),
        ("The examples", f"{sent} of the {len(table)} APIs were sent to the running development API. The other {len(table) - sent} change data, an upload and three drops, so they show their request only. Long answers are shortened, and the full answers are in source/graph_recorded.json."),
    ] + [(f"Tab {tab}", work) for tab, work in TAB_WORK]
    for i, (k, v) in enumerate(lines, 4):
        ws.cell(row=i, column=1, value=k).font = Font(name=v1sheet.FONT, bold=True, size=10)
        cell = ws.cell(row=i, column=2, value=v)
        cell.font = Font(name=v1sheet.FONT, size=10)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[i].height = 30
    ws.column_dimensions["A"].width, ws.column_dimensions["B"].width = 22, 120

    ws = wb.create_sheet("Graph APIs")
    v1sheet.title(ws, "Graph APIs", f"One row per API, in the order of the page tabs. The example answers were sent on {SENT_ON}, unless the last column says why not.")
    data = []
    for r in table:
        if r["ref"]:
            c = CALLS[r["ref"]]
            example, answer, checked = v1sheet.request_text(c), answer_text(c["response"]), f"Sent: {c['status']}"
        else:
            example, answer, checked = r["example"] + "\n(an example, not sent)", "Not sent. The answer holds what the column What comes back says.", "Not sent, because it changes data"
        data.append([r["n"], r["tab"], r["method"], r["path"], r["who"], r["does"], r["send"], r["back"], r["changes"], example, answer, checked])
    v1sheet.write_table(ws, 3, ["No.", "Page tab", "Method", "Path", "Who can call it", "What it does", "What to send", "What comes back", "Changes data",
                                "Example request", "Example answer (shortened)", f"Checked on {SENT_ON}"],
                        data, [5, 16, 8, 34, 24, 48, 40, 40, 11, 46, 60, 16], mono={10, 11}, group_col=2)

    ws = wb.create_sheet(QUERY_TAB)
    v1sheet.title(ws, QUERY_TAB, "Every query is POST /api/v1/context-graphs/{graph_id}/query with one key in the body. The examples ask the ingested graph cg-1cc11e1e, invented data.")
    data = [[n, want, kind, body, back, rules, answer_text(CALLS[ref]["response"]), f"Sent: {CALLS[ref]['status']}"]
            for n, (want, kind, body, back, rules, ref) in enumerate(v1sheet.QUERIES, 1)]
    v1sheet.write_table(ws, 3, ["No.", "What you want to know", "Query kind", "Body to send", "What comes back", "Rules", "Example answer (shortened)", f"Checked on {SENT_ON}"],
                        data, [5, 26, 11, 40, 44, 52, 70, 14], mono={4, 7})

    ws = wb.create_sheet("Ingest JSON fields")
    v1sheet.title(ws, "Ingest JSON fields", "The JSON sent to POST /api/v1/context-graphs. Add ?check=true to check it and keep nothing. When a needed field is missing or wrong, the answer is 422 with each place to fix, and nothing is kept.")
    v1sheet.write_table(ws, 3, ["Field", "Where", "Needed", "What it means", "When it is missing", "Example"],
                        [list(f) for f in v1sheet.FIELDS], [22, 16, 14, 60, 48, 42], mono={6})

    ws = wb.create_sheet("Errors")
    v1sheet.title(ws, "Errors", "The HTTP codes of the context graph APIs.")
    v1sheet.write_table(ws, 3, ["HTTP code", "Meaning"], [list(x) for x in ERRORS], [12, 110])
    return wb


if __name__ == "__main__":
    table = rows()
    OUT_HTML.write_text(page(table), encoding="utf-8")
    print(f"wrote {OUT_HTML} ({OUT_HTML.stat().st_size:,} bytes)")
    workbook(table).save(OUT_XLSX)
    print(f"wrote {OUT_XLSX}")
