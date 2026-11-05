import asyncio
import json
import time
from datetime import date

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jose import jwt
from mcp.server.auth.provider import AccessToken
from mcp.server.auth.settings import AuthSettings
from starlette.testclient import TestClient

import pytest

from mcp_nodes.auth import CallerContext, JwtTokenVerifier, caller_context_from_token
from mcp_nodes.access_store import AccessStore, verify_audit
from mcp_nodes.policy import evaluate_access
from mcp_nodes.server import (
    NODE_IDS,
    capabilities_payload,
    create_server,
    health_payload,
    load_node_config,
    find_experts_node,
    request_access_node,
    search_node,
    summarize_node,
    request_intro_node,
)


class RejectingTokenVerifier:
    async def verify_token(self, token):
        return None


def make_test_server(config, access_store):
    return create_server(
        config,
        access_store=access_store,
        token_verifier=RejectingTokenVerifier(),
        auth_settings=AuthSettings(
            issuer_url="https://issuer.example.test",
            resource_server_url=f"http://127.0.0.1:{config.port}",
            validate_token_resource=False,
            required_scopes=["neuralmesh.query"],
        ),
    )


@pytest.fixture
def signed_token():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("ascii")
    claims = {
        "iss": "https://issuer.example.test",
        "aud": "http://127.0.0.1:8101",
        "sub": "user-123",
        "company": "CEAT",
        "roles": ["group_user"],
        "scope": "neuralmesh.query",
        "exp": int(time.time()) + 120,
    }
    token = jwt.encode(claims, private_key, algorithm="RS256")
    return token, claims, private_key, public_key


@pytest.mark.parametrize("node_id", NODE_IDS)
def test_each_subsidiary_has_a_distinct_node_config(node_id):
    config = load_node_config(node_id)

    assert config.node_id == node_id
    assert config.port == {"ceat": 8101, "kec": 8102, "zensar": 8103, "harrisons": 8104}[node_id]
    assert config.datapoints


@pytest.mark.parametrize("node_id", NODE_IDS)
def test_each_node_registers_the_common_mcp_tools(node_id, tmp_path):
    config = load_node_config(node_id)
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    server = make_test_server(config, store)

    tools = asyncio.run(server.list_tools())

    assert {tool.name for tool in tools} == {
        "health", "describe_capabilities", "search", "summarize", "find_experts", "request_access", "export_graph"
    }


def test_health_and_capabilities_are_scoped_to_the_configured_node():
    config = load_node_config("harrisons")
    caller = CallerContext("user-123", "Harrisons", frozenset({"group_user"}), "problem_solving")

    assert health_payload(config)["node_id"] == "harrisons"
    assert health_payload(config)["status"] == "healthy"
    response = capabilities_payload(config, caller)
    assert response["decision"] == "ALLOWED"
    f01 = next(item for item in response["datapoints"] if item["datapoint_id"] == "F-01")
    assert f01["exposure_ceiling"] == "SUM"
    assert f01["title"] == "Estate SOPs (collection, preservation, transport)"


def test_unknown_node_id_is_rejected():
    with pytest.raises(ValueError, match="Unknown subsidiary node"):
        load_node_config("../../secrets")


def test_mcp_http_endpoint_requires_bearer_authentication(tmp_path):
    config = load_node_config("ceat")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    client = TestClient(make_test_server(config, store).streamable_http_app())

    response = client.post("/mcp", json={})

    assert response.status_code == 401


def test_jwt_verifier_accepts_valid_rs256_claims(signed_token):
    token, _, _, public_key = signed_token
    verifier = JwtTokenVerifier(public_key, "https://issuer.example.test", "http://127.0.0.1:8101")

    access_token = asyncio.run(verifier.verify_token(token))

    assert access_token is not None
    assert access_token.subject == "user-123"
    assert access_token.claims["company"] == "CEAT"
    assert access_token.scopes == ["neuralmesh.query"]


def test_jwt_verifier_rejects_wrong_audience_and_expired_tokens(signed_token):
    token, claims, private_key, public_key = signed_token
    verifier = JwtTokenVerifier(public_key, "https://issuer.example.test", "http://127.0.0.1:8101")
    wrong_audience = jwt.encode({**claims, "aud": "http://127.0.0.1:8102"}, private_key, algorithm="RS256")
    expired = jwt.encode({**claims, "exp": int(time.time()) - 1}, private_key, algorithm="RS256")

    assert asyncio.run(verifier.verify_token(wrong_audience)) is None
    assert asyncio.run(verifier.verify_token(expired)) is None
    assert asyncio.run(verifier.verify_token(token + "invalid")) is None


def test_caller_context_comes_from_verified_claims():
    token = AccessToken(
        token="opaque",
        client_id="client-1",
        scopes=["neuralmesh.query"],
        subject="user-123",
        claims={"company": "CEAT", "roles": ["group_user"]},
    )

    caller = caller_context_from_token(token, "problem_solving")

    assert caller == CallerContext("user-123", "CEAT", frozenset({"group_user"}), "problem_solving")


def test_policy_blocks_disallowed_role_and_purpose():
    config = load_node_config("ceat")
    wrong_role = CallerContext("user-1", "CEAT", frozenset({"guest"}), "problem_solving")
    wrong_purpose = CallerContext("user-1", "CEAT", frozenset({"group_user"}), "marketing")

    assert evaluate_access(config, wrong_role, "E-03", "SUM").rule_id == "R-ROLE-01"
    assert evaluate_access(config, wrong_purpose, "E-03", "SUM").rule_id == "R-PURPOSE-01"


def test_policy_enforces_never_leave_and_exposure_ceiling():
    config = load_node_config("ceat")
    caller = CallerContext("user-1", "CEAT", frozenset({"group_user"}), "problem_solving")

    blocked_formula = evaluate_access(config, caller, "E-01", "RAG")
    blocked_upgrade = evaluate_access(config, caller, "E-03", "RAG")
    allowed_summary = evaluate_access(config, caller, "E-03", "SUM")

    assert (blocked_formula.code, blocked_formula.rule_id) == ("BLOCKED_BY_POLICY", "R-NL-01")
    assert (blocked_upgrade.code, blocked_upgrade.rule_id) == ("BLOCKED_BY_POLICY", "R-EXPOSURE-01")
    assert allowed_summary.code == "ALLOWED_SUMMARY_ONLY"


def test_policy_requires_bounded_approval_for_declared_upgrade():
    config = load_node_config("ceat")
    caller = CallerContext("user-1", "CEAT", frozenset({"group_user"}), "problem_solving")

    pending = evaluate_access(config, caller, "E-02", "RAG")
    approved = evaluate_access(config, caller, "E-02", "RAG", grant_mode="RAG")
    never_leave = evaluate_access(config, caller, "E-01", "RAG", grant_mode="RAG")

    assert pending.code == "NEEDS_APPROVAL"
    assert approved.code == "ALLOWED"
    assert never_leave.code == "BLOCKED_BY_POLICY"


def test_policy_blocks_upsi_during_configured_blackout():
    config = load_node_config("ceat")
    caller = CallerContext("user-1", "CEAT", frozenset({"group_user"}), "problem_solving")

    decision = evaluate_access(config, caller, "F-06", "SUM", as_of=date(2026, 10, 30))

    assert (decision.code, decision.rule_id) == ("BLOCKED_BY_POLICY", "UPSI")


def test_capability_listing_returns_no_datapoints_to_unauthorized_role():
    config = load_node_config("ceat")
    caller = CallerContext("user-1", "CEAT", frozenset({"guest"}), "problem_solving")

    response = capabilities_payload(config, caller)

    assert response["decision"] == "BLOCKED_BY_POLICY"
    assert response["rule_id"] == "R-ROLE-01"
    assert response["datapoints"] == []


def test_search_returns_cited_summary_and_withholds_formula_metadata():
    config = load_node_config("ceat")
    caller = CallerContext("user-1", "CEAT", frozenset({"group_user"}), "problem_solving")

    response = search_node(
        config,
        caller,
        "natural rubber storage handling contamination lot acceptance",
        "problem_solving",
    )

    assert response["status"] == "ok"
    assert any(item["datapoint_id"] == "E-03" and item["citation"] for item in response["results"])
    assert all("text" in item for item in response["results"])
    assert "CANARY-CEAT-FORMULA-7731" not in repr(response)

    formula = search_node(config, caller, "compound formulation", "problem_solving")
    assert any(item["datapoint_id"] == "E-01" and item["mode"] == "MD" for item in formula["withheld"])


def test_search_withholds_blackout_and_approval_gated_metadata():
    caller = CallerContext("user-1", "Group", frozenset({"group_user"}), "problem_solving")
    ceat = load_node_config("ceat")
    kec = load_node_config("kec")

    finance = search_node(
        ceat,
        caller,
        "pre-results capex benchmarks",
        "problem_solving",
        as_of=date(2026, 10, 30),
    )
    annex = search_node(kec, caller, "claims labour annex", "problem_solving")

    assert any(item["datapoint_id"] == "F-06" and item["rule_id"] == "UPSI" for item in finance["withheld"])
    assert any(item["datapoint_id"] == "L-02a" and item["decision"] == "NEEDS_APPROVAL" for item in annex["withheld"])
    assert "CANARY-KEC-CLAIMS-4410" not in repr(annex)


def test_search_flags_injection_and_handles_fts_operators_safely():
    config = load_node_config("zensar")
    caller = CallerContext("user-1", "Zensar", frozenset({"group_user"}), "problem_solving")

    injected = search_node(config, caller, 'onboarding tips " OR * :', "problem_solving")
    empty = search_node(config, caller, '" * :', "problem_solving")

    assert any(item["doc_id"].endswith("C-05-99#0") and item["suspicious"] for item in injected["results"])
    assert empty["status"] == "empty_query"


def test_search_caps_result_count():
    config = load_node_config("harrisons")
    caller = CallerContext("user-1", "Harrisons", frozenset({"group_user"}), "problem_solving")

    response = search_node(config, caller, "latex " * 10000, "problem_solving")

    assert len(response["results"]) <= 30


def test_search_returns_no_metadata_when_caller_is_not_authorized():
    config = load_node_config("ceat")
    caller = CallerContext("user-1", "CEAT", frozenset({"guest"}), "problem_solving")

    response = search_node(config, caller, "compound formulation", "problem_solving")

    assert response["status"] == "BLOCKED_BY_POLICY"
    assert response["rule_id"] == "R-ROLE-01"
    assert response["results"] == []
    assert response["withheld"] == []


def test_request_access_is_persisted_and_never_leave_cannot_be_requested(tmp_path):
    config = load_node_config("kec")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")

    request = request_access_node(
        config,
        store,
        caller,
        "L-02a",
        "RAG",
        "problem_solving",
        "Review claims and labour details for integration planning.",
    )
    denied = request_access_node(
        config,
        store,
        caller,
        "C-01",
        "RAG",
        "problem_solving",
        "Need the bid pricing for cross-business planning.",
    )

    assert request["status"] == "pending"
    assert request["approver"] == "PMO head"
    assert denied["decision"] == "BLOCKED_BY_POLICY"
    assert [row["request_id"] for row in store.pending()] == [request["request_id"]]
    assert store.audit_path.exists()
    assert "Review claims and labour" not in store.audit_path.read_text(encoding="utf-8")


def test_approval_is_bound_to_caller_purpose_and_releases_gated_body(tmp_path):
    config = load_node_config("kec")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")
    request = store.request_access(
        caller,
        "L-02a",
        "RAG",
        "problem_solving",
        "Review claims and labour details for integration planning.",
    )
    reviewed = store.review(request["request_id"], "PMO head", "approve", hours=12)
    store.append_event(reviewed["audit_event"])

    assert store.active_grant(caller, "L-02a", "RAG", "problem_solving") is not None
    assert store.active_grant(CallerContext("user-2", "GroupCo", caller.roles, caller.purpose), "L-02a", "RAG", caller.purpose) is None
    assert store.active_grant(CallerContext("user-1", "OtherCo", caller.roles, caller.purpose), "L-02a", "RAG", caller.purpose) is None
    assert store.active_grant(CallerContext("user-1", "GroupCo", caller.roles, "compliance"), "L-02a", "RAG", "compliance") is None

    result = search_node(
        config,
        caller,
        "claims labour annex",
        caller.purpose,
        mode="RAG",
        access_store=store,
        trace_id="trace-approval-test",
    )

    gated = next(item for item in result["results"] if item["datapoint_id"] == "L-02a")
    audit_text = store.audit_path.read_text(encoding="utf-8")
    assert gated["decision"] == "ALLOWED"
    assert "CANARY-KEC-CLAIMS-4410" in gated["text"]
    assert "CANARY-KEC-CLAIMS-4410" not in audit_text
    assert "claims labour annex" not in audit_text
    assert "Review claims and labour details" not in audit_text
    assert verify_audit(store.audit_path)


def test_only_datapoint_owner_role_can_review_request(tmp_path):
    config = load_node_config("kec")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")
    request = store.request_access(
        caller,
        "L-02a",
        "RAG",
        caller.purpose,
        "Review claims and labour details for integration planning.",
    )

    with pytest.raises(ValueError, match="Only the designated owner role"):
        store.review(request["request_id"], "Group user", "approve")


def test_summarize_returns_only_approved_summaries_and_gated_teasers(tmp_path):
    config = load_node_config("kec")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")

    allowed = summarize_node(config, caller, "L-02-01", caller.purpose, store)
    teaser = summarize_node(config, caller, "L-02a-01", caller.purpose, store)
    blocked = summarize_node(config, caller, "C-01-01", caller.purpose, store)

    assert allowed["decision"] == "ALLOWED_SUMMARY_ONLY"
    assert allowed["citation"].startswith("KEC International")
    assert "text" not in allowed and "body" not in allowed
    assert teaser["decision"] == "NEEDS_APPROVAL"
    assert teaser["summary"] == "Full annex with claim figures and named parties. Owner approval required."
    assert blocked["decision"] == "BLOCKED_BY_POLICY"
    assert blocked["summary"] is None


def test_find_experts_hides_opted_out_people_and_reveals_name_after_intro_approval(tmp_path):
    config = load_node_config("ceat")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")

    before = find_experts_node(config, caller, "natural rubber lot acceptance", caller.purpose, store)
    assert before["experts"]
    assert all("name" not in expert for expert in before["experts"])
    assert all(expert["expert_id"] != "CE-5" for expert in before["experts"])

    request = request_intro_node(
        config,
        store,
        caller,
        "CE-1",
        caller.purpose,
        "Request an introduction to discuss natural rubber quality controls.",
    )
    assert request["status"] == "pending"
    assert request["approver"] == "CHRO"
    approved = store.review(request["request_id"], "CHRO", "approve", hours=12)
    store.append_event(approved["audit_event"])

    after = find_experts_node(config, caller, "natural rubber lot acceptance", caller.purpose, store)
    expert = next(item for item in after["experts"] if item["expert_id"] == "CE-1")
    assert expert["name"] == "Rohan Deshmukh (fictional)"
    other_caller = CallerContext("user-2", caller.company, caller.roles, caller.purpose)
    other_result = find_experts_node(
        config,
        other_caller,
        "natural rubber lot acceptance",
        other_caller.purpose,
        store,
    )
    assert all("name" not in item for item in other_result["experts"])
    assert "Rohan Deshmukh" not in store.audit_path.read_text(encoding="utf-8")


def test_intro_request_for_opted_out_expert_is_blocked(tmp_path):
    config = load_node_config("ceat")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")

    result = request_intro_node(
        config,
        store,
        caller,
        "CE-5",
        caller.purpose,
        "Request an introduction about polymer science and compounds.",
    )

    assert result["status"] == "BLOCKED_BY_POLICY"
    assert store.pending() == []


def test_approved_grant_expiry_and_revocation_are_enforced(tmp_path):
    config = load_node_config("ceat")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")
    request = store.request_access(
        caller,
        "E-02",
        "RAG",
        caller.purpose,
        "Review full material-handling failure records for trend evaluation.",
    )
    approved = store.review(request["request_id"], "Head Quality", "approve", hours=1)

    assert store.active_grant(caller, "E-02", "RAG", caller.purpose) is not None
    with store._connect() as connection:
        connection.execute(
            "UPDATE access_requests SET expires_at='2000-01-01T00:00:00+00:00' WHERE grant_id=?",
            (approved["grant_id"],),
        )
    assert store.active_grant(caller, "E-02", "RAG", caller.purpose) is None

    renewed_request = store.request_access(
        caller,
        "E-02",
        "RAG",
        caller.purpose,
        "Review full material-handling failure records for trend evaluation.",
    )
    renewed = store.review(renewed_request["request_id"], "Head Quality", "approve", hours=1)
    store.revoke(renewed["grant_id"], "Head Quality")
    assert store.active_grant(caller, "E-02", "RAG", caller.purpose) is None


def test_decision_audit_hash_chain_detects_tampering(tmp_path):
    config = load_node_config("ceat")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("user-1", "GroupCo", frozenset({"group_user"}), "problem_solving")
    decision = evaluate_access(config, caller, "E-03", "SUM")
    store.log_decision(
        caller=caller,
        action="search",
        datapoint_id="E-03",
        decision=decision,
        trace_id="trace-audit-test",
    )
    assert verify_audit(store.audit_path)

    entry = json.loads(store.audit_path.read_text(encoding="utf-8"))
    entry["datapoint_id"] = "E-01"
    store.audit_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")
    assert not verify_audit(store.audit_path)