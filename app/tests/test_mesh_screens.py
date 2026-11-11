from fastapi.testclient import TestClient

from api.auth import API_AUDIENCE, issue_poc_token
from api.main import app
from api.routers import mesh
from shared.registry import node as registered_node, node_ids


class ScreenOrchestratorStub:
    async def call_node_tool(self, token, node_id, tool, arguments):
        if tool == "health":
            return {"node_id": node_id, "status": "healthy"}
        if tool == "describe_capabilities":
            return {
                "schema_version": "1.0.0",
                "datapoints": [{"datapoint_id": "E-03", "title": "Materials learnings", "exposure_ceiling": "SUM"}],
            }
        if tool == "find_experts":
            return {"experts": [{"expert_id": f"{node_id}-expert", "company": node_id, "role": "Quality lead", "skills": [arguments["query"]], "evidence": ["E-03"], "match_score": 1}]}
        raise AssertionError(f"Unexpected tool: {tool}")


def _client():
    token = issue_poc_token({"sub": "demo-user", "email": "presenter@neuralmesh.local", "company": "zensar", "roles": ["group_user"]})
    return TestClient(app), {"Authorization": f"Bearer {token}"}


def test_nodes_endpoint_uses_each_mcp_registry(monkeypatch):
    monkeypatch.setattr(mesh, "_orchestrator", lambda: ScreenOrchestratorStub())
    client, headers = _client()

    response = client.get("/api/v1/mesh/nodes", headers=headers)

    assert response.status_code == 200
    assert [node["node_id"] for node in response.json()["nodes"]] == list(node_ids())
    assert [node["tone"] for node in response.json()["nodes"]] == [registered_node(n).tone for n in node_ids()]
    assert all(node["status"] == "healthy" and node["datapoint_count"] == 1 for node in response.json()["nodes"])


def test_expert_search_fans_out_and_identifies_origin_node(monkeypatch):
    monkeypatch.setattr(mesh, "_orchestrator", lambda: ScreenOrchestratorStub())
    client, headers = _client()

    response = client.post(
        "/api/v1/mesh/experts/search",
        headers=headers,
        json={"query": "latex handling", "purpose": "problem_solving", "nodes": ["ceat", "harrisons"]},
    )

    assert response.status_code == 200
    experts = response.json()["experts"]
    assert {expert["node_id"] for expert in experts} == {"ceat", "harrisons"}
    assert {node["node_id"] for node in response.json()["nodes"]} == {"ceat", "harrisons"}


def test_expert_search_lists_evidence_by_title_and_leaves_out_a_never_leave_document_of_another_company(monkeypatch):
    from types import SimpleNamespace

    class Stub(ScreenOrchestratorStub):
        async def call_node_tool(self, token, node_id, tool, arguments):
            assert arguments.get("concepts") == ["concept:x"]  # the question's concepts reach the node
            return {"experts": [{"expert_id": "CE-9", "company": "CEAT", "role": "Lead", "skills": [], "match_score": 3,
                                 "evidence": ["ceat:E-01-01", "ceat:E-03-01"]}]}

    graph = SimpleNamespace(resolve=lambda q: {"concepts": {"concept:x": "x"}},
                            shown_to=lambda doc, company, roles: doc != "ceat:E-01-01",
                            label=lambda doc: {"ceat:E-03-01": "Lot acceptance and trending"}.get(doc, doc))
    monkeypatch.setattr(mesh, "_orchestrator", lambda: Stub())
    monkeypatch.setattr(mesh, "runtime", lambda: SimpleNamespace(mesh=graph))
    client, headers = _client()
    body = client.post("/api/v1/mesh/experts/search", headers=headers,
                       json={"query": "lot trending", "purpose": "problem_solving", "nodes": ["ceat"]}).json()
    expert = body["experts"][0]
    assert expert["evidence"] == ["ceat:E-03-01"] and expert["evidence_titles"] == ["Lot acceptance and trending"]
    # the list of each node carries the same filtered experts: the never-leave id is nowhere in the answer
    assert body["nodes"][0]["experts"][0]["evidence"] == ["ceat:E-03-01"]
    assert "ceat:E-01-01" not in str(body)


def test_admin_endpoint_reports_registry_and_the_model_policy(monkeypatch):
    monkeypatch.setattr(mesh, "_orchestrator", lambda: ScreenOrchestratorStub())
    client, headers = _client()

    response = client.get("/api/v1/mesh/admin", headers=headers)

    assert response.status_code == 200
    assert len(response.json()["registry"]) == len(node_ids())
    policy = response.json()["model_policy"]
    assert policy["steps"]["answer"]["model"] and isinstance(policy["answer_model_ready"], bool)
    assert "groq_configured" not in response.json()
    assert response.json()["orchestrator_stage"] == "resolve_route_fanout_scope_expand_build_answer_check"


def test_screen_routes_require_authentication():
    client = TestClient(app)

    response = client.get("/api/v1/mesh/nodes")

    assert response.status_code == 401

def test_domains_endpoint_lists_every_domain_with_its_types_and_counts(monkeypatch):
    """The Domains page read this endpoint. On 2026-11-09 a refactor left `ontology` imported in the wrong function, and
    the endpoint answered 500 until 2026-11-10. No test had called it."""
    monkeypatch.setattr(mesh, "_orchestrator", lambda: ScreenOrchestratorStub())
    mesh._DOMAINS_CACHE.clear()
    client, headers = _client()

    response = client.get("/api/v1/mesh/domains", headers=headers)

    assert response.status_code == 200, response.text[:200]
    body = response.json()
    names = [d["domain"] for d in body["domains"]]
    assert names == ["core", "inspection"]  # the two layers of the graph rules, not the pack domains of the nodes
    core = body["domains"][0]
    assert {"type", "count", "description"} <= set(core["node_types"][0])
    assert core["entities"] == sum(n["count"] for n in core["node_types"]) > 0
    assert core["links"] == sum(sum(e["counts"].values()) for e in core["edge_types"]) > 0
    assert "sources" in body and "revision" in body and "checks" in body
