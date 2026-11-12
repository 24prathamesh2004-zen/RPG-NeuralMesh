"""Send the documented read calls to the running API and keep each request and answer. Tokens and the password are
never kept: the sign-in answer's token is replaced with <token>."""
import json, re, sys, httpx
from pathlib import Path
SP = Path(sys.argv[1])
BASE = "http://127.0.0.1:8000"
seed = Path("scripts/seed_demo_accounts.py").read_text()
PW = re.search(r"MeshPilot[^`\"' ]*", seed).group(0)
c = httpx.Client(base_url=BASE, timeout=120)
def signin(email):
    r = c.post("/api/v1/auth/signin", json={"email": email, "password": PW})
    r.raise_for_status()
    return r.json()["access_token"], r
P, signin_resp = signin("presenter@neuralmesh.local")
K, _ = signin("kec.expert@neuralmesh.local")
S = (SP / ".svc_token").read_text().strip()
calls = []
def call(cid, group, title, method, path, token=None, body=None, params=None, shown_body=None):
    h = {"Authorization": f"Bearer {token}"} if token else {}
    r = c.request(method, path, headers=h, json=body, params=params)
    try: resp = r.json()
    except ValueError: resp = r.text
    calls.append({"id": cid, "group": group, "title": title, "method": method, "path": path, "params": params, "body": shown_body if shown_body is not None else body,
                  "status": r.status_code, "token": {P: "person", K: "person (KEC)", S: "service"}.get(token, "none"), "response": resp})
    print(f"{r.status_code} {method} {path} {params or ''}")
    return resp
# people
call("health", "start", "Is the service up", "GET", "/health")
call("companies", "start", "The companies a person can sign up for", "GET", "/api/v1/auth/companies")
sr = signin_resp.json(); sr["access_token"] = "<token>"
calls.append({"id": "signin", "group": "start", "title": "Sign in and get a token", "method": "POST", "path": "/api/v1/auth/signin", "params": None,
              "body": {"email": "presenter@neuralmesh.local", "password": "<password>"}, "status": 200, "token": "none", "response": sr}); print("200 POST signin")
call("me", "start", "Who is signed in", "GET", "/api/v1/auth/me", P)
ask = call("ask", "mesh", "Ask the mesh a question", "POST", "/api/v1/mesh/query", P,
           {"question": "What rubber-compound learnings from CEAT could reduce Harrisons Malayalam's latex spoilage?", "purpose": "problem_solving"})
call("routing", "mesh", "Which companies a question goes to", "GET", "/api/v1/mesh/routing", P, params={"q": "latex spoilage at receipt"})
found = call("search", "mesh", "Search the mesh graph", "GET", "/api/v1/mesh/graph/search", P, params={"q": "latex"})
first = found["results"][0]["id"] if found.get("results") else None
if first: call("entity", "mesh", "One entity with its links", "GET", f"/api/v1/mesh/graph/entity/{first}", P)
call("nodes", "mesh", "The company nodes and their health", "GET", "/api/v1/mesh/nodes", P)
call("experts", "mesh", "Find experts by skill", "POST", "/api/v1/mesh/experts/search", P, {"query": "latex preservation", "purpose": "problem_solving"})
call("graph", "mesh", "The whole mesh graph", "GET", "/api/v1/mesh/graph", P)
call("domains", "mesh", "Knowledge areas and catalogue items", "GET", "/api/v1/mesh/domains", P)
call("applications", "mesh", "Registered applications", "GET", "/api/v1/mesh/applications", P)
call("links", "mesh", "Links between companies", "GET", "/api/v1/mesh/graph/links", P)
call("proposals", "mesh", "Links proposed by applications", "GET", "/api/v1/mesh/proposals", P)
call("governance", "mesh", "Pending requests and the audit", "GET", "/api/v1/mesh/governance", P)
call("verify", "mesh", "Check the audit chains", "GET", "/api/v1/mesh/governance/audit/verify", P)
call("admin", "mesh", "Registry, vocabulary and model", "GET", "/api/v1/mesh/admin", P)
call("dashboard", "mesh", "Dashboard figures", "GET", "/api/v1/mesh/dashboard", P)
call("help", "mesh", "Ask the help chat", "POST", "/api/v1/help/chat", P, {"question": "How do I ingest my own graph as JSON?"})
ups = call("uploads", "uploaded", "Uploaded inputs and their graphs", "GET", "/api/v1/mesh/uploads", P)
kochi = next((g["id"] for g in ups.get("graphs", []) if "Kochi" in g["name"]), ups.get("graphs", [{}])[0].get("id"))
doc = next((u["document"]["id"] for u in ups.get("uploads", []) if u["context_graph"]["id"] == kochi), None)
call("upload_graph", "uploaded", "One uploaded context graph", "GET", f"/api/v1/mesh/uploads/graphs/{kochi}", P)
call("render", "uploaded", "The graph in the standard JSON structure", "POST", "/api/v1/mesh/uploads/json-templates/render", P, {"graph_id": kochi})
call("structure", "uploaded", "The standard JSON structure", "GET", "/api/v1/mesh/uploads/json-templates", P)
if doc: call("doc_graph", "uploaded", "The graph around one uploaded document", "GET", f"/api/v1/mesh/uploads/{doc}/graph", P)
call("items", "uploaded", "Catalogue items of a company", "GET", "/api/v1/mesh/uploads/items/ceat", P)
# ingested context graphs
G = "cg-1cc11e1e"
call("cg_list", "ingested", "The ingested graphs a person may see", "GET", "/api/v1/context-graphs", P)
sample = call("cg_sample", "ingested", "The sample JSON", "GET", "/api/v1/context-graphs/sample", P)
call("cg_check", "ingested", "Check a JSON and keep nothing", "POST", "/api/v1/context-graphs", P, sample, params={"check": "true"})
broken = json.loads(json.dumps(sample)); broken.pop("company"); broken["edges"][0]["target"] = "nowhere"
call("cg_refused", "ingested", "A JSON with mistakes is refused", "POST", "/api/v1/context-graphs", P, broken)
call("cg_get", "ingested", "One graph as JSON", "GET", f"/api/v1/context-graphs/{G}", P)
call("cg_view", "ingested", "Nodes and edges for a drawing", "GET", f"/api/v1/context-graphs/{G}/view", P)
q = f"/api/v1/context-graphs/{G}/query"
call("q_overview", "query", "What the graph holds", "POST", q, P, {"overview": True})
call("q_nodes", "query", "Find nodes by type, name or property", "POST", q, P, {"nodes": {"type": "Supplier"}})
call("q_node", "query", "One node and its neighbours", "POST", q, P, {"node": "Mixer 1", "hops": 1})
call("q_edges", "query", "Relationships by type, source or target", "POST", q, P, {"edges": {"type": "SUPPLIES", "target": "Rotor seal RS-200"}})
call("q_path", "query", "How two nodes are connected", "POST", q, P, {"path": {"from": "Supplier X", "to": "Plant A"}})
call("q_similar", "query", "Nodes similar to one", "POST", q, P, {"similar": {"node": "Supplier X", "top": 5}})
call("q_question", "query", "A question in plain words", "POST", q, P, {"question": "Which suppliers supply the rotor seal?"})
call("q_missing", "query", "A name that is not in the graph", "POST", q, P, {"node": "Rotor sael RS-200"})
call("q_scope", "query", "Another company asks a company-only graph", "POST", q, K, {"overview": True})
# applications: the context contract
con = call("contract", "contract", "The published contract", "GET", "/api/v1/context/contract", S)
env = lambda tool, inp, purpose="learning", person=True: {"schema_version": "1.1", "tool": tool, "purpose": purpose,
      "caller": {"subsidiary": "ceat", "roles": ["user"], **({"user_ref": "sf-user-1042"} if person else {})}, "input": inp}
rc = call("t_role", "contract", "role_context: a role and its skills", "POST", "/api/v1/context/role_context", S, env("role_context", {"title": "Process Engineer", "company": "ceat"}, person=False))
import re as _re
skill = next(iter(_re.findall(r'"(skill:[a-z0-9-]+)"', json.dumps(rc))), "skill:rubber-plantation-management")
call("t_entity", "contract", "entity: one entity", "POST", "/api/v1/context/entity", S, env("entity", {"id": skill}, person=False))
call("t_related", "contract", "related: neighbours by link type", "POST", "/api/v1/context/related", S, env("related", {"id": skill, "depth": 1}, person=False))
role = "ceat:role/process-engineer"
if role: call("t_similar", "contract", "similar: computed similar entities", "POST", "/api/v1/context/similar", S, env("similar", {"id": role, "k": 3}, person=False))
call("t_ask", "contract", "ask: a cited answer for an end user", "POST", "/api/v1/context/ask", S,
     env("ask", {"question": "What does a compounding engineer need to know about natural rubber storage?"}, purpose="problem_solving"))
call("t_refused", "contract", "A refusal that says what is needed", "POST", "/api/v1/context/entity", S, env("entity", {"id": "skill:no-such-skill"}, person=False))
json.dump(calls, open(SP / "recorded.json", "w"), indent=1, ensure_ascii=False)
print(len(calls), "calls kept")

# applications: the other read-only tools (a SkillForge token, and a Snap and Score token for the inspection tools,
# made with python -m scripts.issue_service_token snapscore and kept in .svc_token_snap beside .svc_token)
SNAP = (SP / ".svc_token_snap").read_text().strip() if (SP / ".svc_token_snap").exists() else None
def env2(tool, inp, purpose, company="ceat", person=True):
    return {"schema_version": "1.1", "tool": tool, "purpose": purpose,
            "caller": {"subsidiary": company, "roles": ["user"], **({"user_ref": "app-user-1042"} if person else {})}, "input": inp}
more = [("t2_skill", "skill_context: a skill with its evidence", S, env2("skill_context", {"skill": "skill:engineering", "level": "M"}, "learning")),
        ("t2_learning", "learning_sources: study documents for a skill", S, env2("learning_sources", {"skill": "skill:engineering", "level": "M"}, "learning")),
        ("t2_mentors", "find_mentors: consented experts of a skill", S, env2("find_mentors", {"skill": "skill:engineering"}, "learning")),
        ("t2_vocab", "vocabulary_export: the group vocabulary", S, env2("vocabulary_export", {}, "career_mobility", company="group", person=False))]
if SNAP:
    more += [("t2_profile", "inspection_profile: how an asset is inspected", SNAP, env2("inspection_profile", {"asset": "ceat:asset/finished_tyre"}, "inspection")),
             ("t2_history", "inspection_history: past inspections of an asset", SNAP, env2("inspection_history", {"asset": "ceat:asset/finished_tyre"}, "inspection")),
             ("t2_live", "live: a fact asked of the owning node now", SNAP, env2("live", {"id": "ceat:asset/finished_tyre", "fact": "cover_status"}, "inspection"))]
for cid, title, tok, body in more:
    r = c.post(f"/api/v1/context/{body['tool']}", headers={"Authorization": f"Bearer {tok}"}, json=body)
    calls.append({"id": cid, "group": "contract", "title": title, "method": "POST", "path": f"/api/v1/context/{body['tool']}", "params": None, "body": body,
                  "status": r.status_code, "token": "service" if tok == S else "service (Snap and Score)", "response": r.json()})
    print(r.status_code, body["tool"])
json.dump(calls, open(SP / "recorded.json", "w"), indent=1, ensure_ascii=False)
print(len(calls), "calls kept with the other tools")
