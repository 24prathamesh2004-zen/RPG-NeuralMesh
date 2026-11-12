"""Send the context graph calls of the v2 API page to the running API and keep each request and answer in
graph_recorded.json. Only calls that keep nothing: reads, a check with check=true, a refused JSON and the queries of
one ingested graph. The password and the tokens are never kept: the sign-in answer's token is replaced with <token>.
Run from RPG-NeuralMesh/app:  ../.venv/bin/python "../Docs - rpg neuralmesh/02_API_Reference/source/record_graph_calls.py"
"""
import json, re
from pathlib import Path
import httpx

HERE = Path(__file__).resolve().parent
BASE = "http://127.0.0.1:8000"
SAMPLE_FILE = HERE.parents[1] / "01_Inputs_for_Testing" / "Upload_Input_Samples" / "auto_fill_samples" / "02_cable_joint_moisture_review.txt"
PW = re.search(r"MeshPilot[^`\"' ]*", Path("scripts/seed_demo_accounts.py").read_text()).group(0)
c = httpx.Client(base_url=BASE, timeout=120)


def signin(email):
    r = c.post("/api/v1/auth/signin", json={"email": email, "password": PW})
    r.raise_for_status()
    return r.json()["access_token"], r


P, signin_resp = signin("presenter@neuralmesh.local")
K, _ = signin("kec.expert@neuralmesh.local")
calls = []


def call(cid, title, method, path, token=None, body=None, params=None, files=None, form=None, shown_body=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    if files:
        r = c.request(method, path, headers=h, params=params, files=files, data=form)
    else:
        r = c.request(method, path, headers=h, json=body, params=params)
    try:
        resp = r.json()
    except ValueError:
        resp = r.text
    calls.append({"id": cid, "title": title, "method": method, "path": path, "params": params,
                  "body": shown_body if shown_body is not None else body, "multipart": bool(files), "status": r.status_code,
                  "token": {P: "person", K: "person (KEC)"}.get(token, "none"), "response": resp})
    print(f"{r.status_code} {method} {path} {params or ''}")
    return resp


sr = signin_resp.json()
sr["access_token"] = "<token>"
calls.append({"id": "signin", "title": "Sign in and get a token", "method": "POST", "path": "/api/v1/auth/signin", "params": None,
              "body": {"email": "presenter@neuralmesh.local", "password": "<password>"}, "multipart": False, "status": 200, "token": "none", "response": sr})
ups = call("uploads", "Uploaded inputs and their context graphs", "GET", "/api/v1/mesh/uploads", P)
kv = next(g["id"] for g in ups["graphs"] if g["name"] == "33 kV cable joint failures")
call("cg_list", "Ingested graphs the person may see", "GET", "/api/v1/context-graphs", P)
call("search", "The one search: the graph part", "GET", "/api/v1/mesh/graph/search", P, params={"q": "teardown"})
call("entity", "One topic with its links", "GET", "/api/v1/mesh/graph/entity/concept:lot-acceptance", P)
call("upload_graph", "One uploaded context graph", "GET", f"/api/v1/mesh/uploads/graphs/{kv}", P)
call("render", "That graph in the standard JSON structure", "POST", "/api/v1/mesh/uploads/json-templates/render", P, {"graph_id": kv})
G = "cg-1cc11e1e"
call("cg_view", "An ingested graph's nodes and edges", "GET", f"/api/v1/context-graphs/{G}/view", P)
call("suggest", "Read a file and propose the fields", "POST", "/api/v1/mesh/uploads/suggest", P,
     files={"file": (SAMPLE_FILE.name, SAMPLE_FILE.read_bytes(), "text/plain")}, form={"node_id": "raychem"},
     shown_body={"file": SAMPLE_FILE.name, "node_id": "raychem"})
call("items", "Catalogue items of a company", "GET", "/api/v1/mesh/uploads/items/raychem", P)
sample = call("cg_sample", "The sample JSON", "GET", "/api/v1/context-graphs/sample", P)
call("cg_check", "Check a JSON and keep nothing", "POST", "/api/v1/context-graphs", P, sample, params={"check": "true"})
broken = json.loads(json.dumps(sample))
broken.pop("company")
broken["edges"][0]["target"] = "nowhere"
call("cg_refused", "A JSON with mistakes is refused", "POST", "/api/v1/context-graphs", P, broken)
call("cg_get", "One ingested graph as JSON", "GET", f"/api/v1/context-graphs/{G}", P)
q = f"/api/v1/context-graphs/{G}/query"
call("q_overview", "What the graph holds", "POST", q, P, {"overview": True})
call("q_nodes", "Find nodes by type, name or property", "POST", q, P, {"nodes": {"type": "Supplier"}})
call("q_node", "One node and its neighbours", "POST", q, P, {"node": "Mixer 1", "hops": 1})
call("q_edges", "Relationships by type, source or target", "POST", q, P, {"edges": {"type": "SUPPLIES", "target": "Rotor seal RS-200"}})
call("q_path", "How two nodes are connected", "POST", q, P, {"path": {"from": "Supplier X", "to": "Plant A"}})
call("q_similar", "Nodes similar to one", "POST", q, P, {"similar": {"node": "Supplier X", "top": 5}})
call("q_question", "A question in plain words", "POST", q, P, {"question": "Which suppliers supply the rotor seal?"})
call("q_missing", "A name that is not in the graph", "POST", q, P, {"node": "Rotor sael RS-200"})
call("q_scope", "Another company asks a company-only graph", "POST", q, K, {"overview": True})
(HERE / "graph_recorded.json").write_text(json.dumps(calls, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
print(len(calls), "calls kept")
