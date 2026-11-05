"""Live wiring check against running services: API on 8000, gateway on 8100, nodes on 8101 to 8104.

    python -m evaluations.live_wiring_check

Calls the real HTTP and MCP endpoints with development tokens and prints one line per check. Writes nothing
except the node and central audit entries that any query writes.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import json
import subprocess
import sys
from pathlib import Path

import httpx
import yaml
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

from api.auth import issue_poc_token

API = "http://127.0.0.1:8000/api/v1"
GATEWAY = "http://127.0.0.1:8100/mcp"
STANDIN_CONTROL = "http://127.0.0.1:11435/control"
APP = Path(__file__).resolve().parents[1]
GOLDEN = yaml.safe_load((Path(__file__).resolve().parents[1] / "neuralmesh_kb_pack" / "kb" / "golden.yaml").read_text())["scenarios"]
CANARY = "CANARY-"
results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}{'  ' + detail if detail else ''}")


def main() -> None:
    user = issue_poc_token({"sub": "live-check", "email": "presenter@neuralmesh.local", "company": "ceat", "roles": ["group_user"]})
    service = issue_poc_token({"sub": "svc:skillforge", "company": "group", "roles": ["context_client", "talent_exporter"],
                               "scope": "neuralmesh.context"})
    h = {"Authorization": f"Bearer {user}"}
    s = {"Authorization": f"Bearer {service}"}
    http = httpx.Client(timeout=60)

    nodes = http.get(f"{API}/mesh/nodes", headers=h).json()["nodes"]
    check("4 nodes healthy with packs and profiles", all(n["status"] == "healthy" and n["packs"] and n["profile"] for n in nodes),
          ", ".join(f"{n['node_id']} {len(n['packs'])} packs" for n in nodes))
    graph = http.get(f"{API}/mesh/graph", headers=h).json()
    check("graph built from node exports", all(v.startswith("loaded") for v in graph["exports"].values()) and graph["counts"].get("Role", 0) >= 3,
          json.dumps(graph["counts"]))

    for scenario in GOLDEN:
        if scenario["id"] == "S7":
            continue
        body = http.post(f"{API}/mesh/query", headers=h, json={"question": scenario["question"], "purpose": "problem_solving"}).json()
        routed = set(body["routing"].get("subsidiaries", []))
        text = json.dumps(body)
        expected = set(scenario["nodes"])
        ok = CANARY not in text and body["status"] in ("ok", "partial")
        if scenario["id"] == "S4":
            ok = ok and bool(routed)
        else:
            ok = ok and expected <= routed
        withheld = {w["datapoint_id"] for w in body["withheld"]}
        extra = ""
        if scenario["id"] == "S5":
            ok = ok and "E-01" in withheld and not any(e.get("datapoint") == "ceat:E-01" for e in body["evidence"])
        if scenario["id"] == "S6":
            ok = ok and not any(e.get("datapoint") == "ceat:F-06" for e in body["evidence"])
        if scenario["id"] == "S10":
            ok = ok and any(w["datapoint_id"] == "E-02" or w.get("decision") == "NEEDS_APPROVAL" for w in body["withheld"]) or \
                any(e.get("datapoint") == "ceat:E-02" and e.get("mode") == "SUM" for e in body["evidence"])
        if scenario["id"] == "S1":
            types = {l["type"] for l in body["relationships"]}
            ok = ok and "ADDRESSES_GAP" in types and "E-01" in withheld
            extra = f" links {sorted(types)}"
        if scenario["id"] == "S2":
            ok = ok and any(l["type"] == "CONFLICTS_WITH" for l in body["relationships"])
        if scenario["id"] == "S8":
            ok = ok and "IGNORE PREVIOUS INSTRUCTIONS" not in (body["answer"] or "")
        check(f"{scenario['id']} {body['routing'].get('method')} -> {sorted(routed)}", ok,
              f"{len(body['evidence'])} records, {len(body['withheld'])} withheld, answer {body['answer_status']}{extra}")

    reworded = http.post(f"{API}/mesh/query", headers=h, json={"question": "latex going bad before it reaches the factory",
                                                                 "purpose": "problem_solving"}).json()
    check("reworded question routed by meaning", "harrisons" in reworded["routing"].get("subsidiaries", []),
          str(reworded["routing"].get("concept_labels")))

    role = http.post(f"{API}/context/role_context", headers=s, json={"role_id": "ceat:role/quality-engineer"}).json()
    check("context role_context", len(role.get("required_skills", [])) == 4, str([x["skill"] for x in role.get("required_skills", [])]))
    learner = {"user_id": "sf-1042", "company": "harrisons", "roles": ["group_user"]}
    sources = http.post(f"{API}/context/learning_sources", headers=s,
                        json={"user": learner, "skill": "quality management", "target_level": "M"}).json()
    check("context learning_sources by reference", sorted(x["evidence_id"] for x in sources["sources"]) == ["ceat:E-03-01", "ceat:E-03-04"]
          and all(x["text"] for x in sources["sources"]), str([x["evidence_id"] for x in sources["sources"]]))
    mentors = http.post(f"{API}/context/find_mentors", headers=s, json={"skill": "skill:quality-management"}).json()
    check("context find_mentors without names", mentors["mentors"] and "fictional" not in json.dumps(mentors),
          str([m["evidence_id"] for m in mentors["mentors"]]))
    ask = http.post(f"{API}/context/ask", headers=s, json={"user": learner, "purpose": "problem_solving",
                                                           "question": "How do CEAT's storage practices help with latex spoilage? reach me at x@y.com"}).json()
    check("context ask strips contact details", ask["contact_details_removed"] == 1 and "y.com" not in json.dumps(ask),
          f"{len(ask['evidence'])} records")
    check("person token refused on context API",
          http.post(f"{API}/context/find_mentors", headers=h, json={"skill": "skill:hr"}).status_code == 403)

    async def gateway() -> None:
        async with streamablehttp_client(GATEWAY, headers={"Authorization": f"Bearer {service}"}) as (reader, writer, _):
            async with ClientSession(reader, writer) as session:
                await session.initialize()
                tools = {t.name for t in (await session.list_tools()).tools}
                result = await session.call_tool("role_context", {"role_id": "ceat:role/quality-engineer"})
                check("MCP gateway lists six tools and answers role_context",
                      len(tools) == 6 and not result.isError and len(result.structuredContent["required_skills"]) == 4, str(sorted(tools)))
    asyncio.run(gateway())

    expired = issue_poc_token({"sub": "x", "company": "ceat", "roles": ["group_user"]}, hours=-1)
    check("expired token refused", http.get(f"{API}/mesh/nodes", headers={"Authorization": f"Bearer {expired}"}).status_code == 401)

    rels = {}
    for company in ("harrisons", "kec"):
        token = issue_poc_token({"sub": f"live-{company}", "company": company, "roles": ["group_user"]})
        body = http.post(f"{API}/mesh/query", headers={"Authorization": f"Bearer {token}"},
                         json={"question": GOLDEN[0]["question"], "purpose": "problem_solving"}).json()
        rels[company] = sorted(link["id"] for link in body["relationships"])
    check("S1 links are the same for a Harrisons and a KEC caller", bool(rels["kec"]) and rels["harrisons"] == rels["kec"], str(rels["kec"]))

    questions = [s["question"] for s in GOLDEN if s["id"] != "S7"] * 3
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        codes = list(pool.map(lambda q: http.post(f"{API}/mesh/query", headers=h, json={"question": q, "purpose": "compliance"},
                                                   timeout=120).status_code, questions[:20]))
    verify = subprocess.run([sys.executable, "-m", "mcp_nodes.approvals", "--node", "ceat", "verify-audit"],
                            capture_output=True, text=True, cwd=APP)
    check("20 parallel queries all answer and the ceat audit chain verifies", all(c == 200 for c in codes) and '"valid": true' in verify.stdout,
          f"status codes {sorted(set(codes))}, verify-audit {verify.stdout.strip()[:30]}")

    standin = http.get(STANDIN_CONTROL)
    if standin.status_code == 200:
        for mode, rule, question in (
            ("leak-withheld", 3, "What is in CEAT's channel pricing sheet and compound formulation records?"),
            ("too-long", 7, "Which project delays and site breakdowns repeat at KEC International?"),
            ("canary", 2, "What storage practices does CEAT use for natural rubber lots in the warehouse?"),
        ):
            http.post(STANDIN_CONTROL, json={"mode": mode})
            body = http.post(f"{API}/mesh/query", headers=h, json={"question": question, "purpose": "bid_support"}, timeout=120).json()
            http.post(STANDIN_CONTROL, json={"mode": "ok"})
            rules = {f["rule"] for f in body["checks"]}
            check(f"check step catches stand-in mode {mode} with rule {rule}", body["answer_status"] == "check_failed" and rule in rules,
                  f"{body['answer_status']} rules {sorted(rules)}")
    else:
        print("SKIP  stand-in control not reachable, the check-step modes were not exercised")

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)} of {len(results)} checks passed")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
