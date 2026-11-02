from fastapi.testclient import TestClient

from api.auth import API_AUDIENCE, issue_poc_token
from api.main import app
from api.routers import mesh


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
    assert [node["node_id"] for node in response.json()["nodes"]] == ["ceat", "kec", "zensar", "harrisons"]
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


def test_admin_endpoint_reports_registry_and_groq_configuration(monkeypatch):
    monkeypatch.setattr(mesh, "_orchestrator", lambda: ScreenOrchestratorStub())
    monkeypatch.setattr(mesh.get_settings(), "neuralmesh_groq_api_key", "test-key")
    client, headers = _client()

    response = client.get("/api/v1/mesh/admin", headers=headers)

    assert response.status_code == 200
    assert len(response.json()["registry"]) == 4
    assert response.json()["groq_configured"] is True
    assert response.json()["orchestrator_stage"] == "parallel_mcp_evidence_fanout"


def test_screen_routes_require_authentication():
    client = TestClient(app)

    response = client.get("/api/v1/mesh/nodes")

    assert response.status_code == 401