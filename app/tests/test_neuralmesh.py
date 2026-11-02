import asyncio

import pytest
from pydantic import ValidationError

from api.schemas.mesh import MeshQueryRequest
from api.auth import API_AUDIENCE, POC_ISSUER, issue_poc_token
from jose import jwt
from services.neuralmesh import MeshOrchestrator, PocNodeTokenProvider, build_mesh_graph
from shared.config import Settings, get_settings


class FakeTokenProvider:
    def __init__(self):
        self.nodes = []

    async def token_for_node(self, user_assertion, node_id):
        self.nodes.append((user_assertion, node_id))
        return f"node-token-{node_id}"


class FakeTransport:
    def __init__(self, fail_nodes=()):
        self.calls = []
        self.fail_nodes = set(fail_nodes)

    async def search(self, url, token, *, query, purpose, mode, as_of):
        self.calls.append((url, token, query, purpose, mode, as_of))
        node_id = token.removeprefix("node-token-")
        if node_id in self.fail_nodes:
            raise ConnectionError("test-only node outage")
        if node_id == "kec":
            return {
                "status": "BLOCKED_BY_POLICY",
                "results": [],
                "withheld": [{"datapoint_id": "C-01", "rule_id": "R-NL-04"}],
            }
        return {
            "status": "ok",
            "results": [{"datapoint_id": "E-03", "citation": "CEAT · E-03", "text": "approved summary"}],
            "withheld": [],
        }


def test_langgraph_fans_out_only_to_selected_independent_nodes():
    token_provider = FakeTokenProvider()
    transport = FakeTransport()
    graph = build_mesh_graph(
        MeshOrchestrator(
            {"ceat": "http://ceat/mcp", "kec": "http://kec/mcp", "zensar": "http://zensar/mcp", "harrisons": "http://harrisons/mcp"},
            token_provider,
            transport,
        )
    )

    result = asyncio.run(
        graph.ainvoke(
            {
                "question": "How can storage practices help?",
                "nodes": ["ceat", "kec"],
                "purpose": "problem_solving",
                "mode": "SUM",
                "as_of": "2026-10-30",
                "user_assertion": "incoming-user-token",
            }
        )
    )

    assert {node_id for _, node_id in token_provider.nodes} == {"ceat", "kec"}
    assert {call[0] for call in transport.calls} == {"http://ceat/mcp", "http://kec/mcp"}
    assert all(call[1].startswith("node-token-") for call in transport.calls)
    assert result["status"] == "ok"
    assert result["sources"][0]["citation"] == "CEAT · E-03"
    assert result["withheld"][0]["rule_id"] == "R-NL-04"
    assert result["user_assertion"] == ""


def test_langgraph_returns_partial_status_when_a_node_is_unavailable():
    token_provider = FakeTokenProvider()
    transport = FakeTransport(fail_nodes={"harrisons"})
    graph = build_mesh_graph(
        MeshOrchestrator(
            {"harrisons": "http://harrisons/mcp"},
            token_provider,
            transport,
        )
    )

    result = asyncio.run(
        graph.ainvoke(
            {
                "question": "What are spoilage drivers?",
                "nodes": ["harrisons"],
                "purpose": "problem_solving",
                "user_assertion": "incoming-user-token",
            }
        )
    )

    assert result["status"] == "partial"
    assert result["node_results"][0]["status"] == "NODE_UNAVAILABLE"
    assert result["sources"] == []


def test_mesh_request_rejects_empty_or_duplicate_node_selection():
    with pytest.raises(ValidationError):
        MeshQueryRequest(question="Find a solution", nodes=[], purpose="problem_solving")
    with pytest.raises(ValidationError, match="duplicates"):
        MeshQueryRequest(question="Find a solution", nodes=["ceat", "ceat"], purpose="problem_solving")


def test_poc_orchestrator_mints_node_audience_token_from_user_session():
    settings = Settings(
        app_secret_key=get_settings().app_secret_key,
        neuralmesh_ceat_url="http://127.0.0.1:8101/mcp",
    )
    provider = PocNodeTokenProvider(settings)
    user_token = issue_poc_token(
        {"sub": "user-123", "company": "ceat", "roles": ["group_user"]},
        audience=API_AUDIENCE,
    )

    node_token = asyncio.run(provider.token_for_node(user_token, "ceat"))
    claims = jwt.decode(
        node_token,
        settings.app_secret_key,
        algorithms=["HS256"],
        issuer=POC_ISSUER,
        audience="http://127.0.0.1:8101",
    )

    assert claims["sub"] == "user-123"
    assert claims["company"] == "ceat"
    assert claims["roles"] == ["group_user"]
    assert claims["scope"] == "neuralmesh.query"