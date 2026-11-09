"""Regression tests for the code review of 2026-11-09."""
from types import SimpleNamespace

import pytest

from services.context import llm, policy


def test_production_refuses_the_development_admin_email(monkeypatch):
    from shared.config import Settings
    with pytest.raises(ValueError, match="neuralmesh_admin_emails"):
        Settings(app_env="production", app_secret_key="x" * 40)
    Settings(app_env="production", app_secret_key="x" * 40, neuralmesh_admin_emails="owner@example.com")


def _backend(stop_reason, text, calls):
    class Messages:
        def create(self, **kw):
            calls.append(kw)
            blocks = [SimpleNamespace(type="text", text=text)] if text else []
            return SimpleNamespace(stop_reason=stop_reason, content=blocks, usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    return llm.AnthropicBackend(client_factory=lambda key: SimpleNamespace(messages=Messages()))


def _choice(cap):
    return policy.ModelChoice("classify", "m", "cloud", "", "", 1000, cap, "anthropic")


def test_a_small_output_cap_leaves_thinking_off_and_an_empty_cut_off_reply_is_an_error(monkeypatch):
    monkeypatch.setattr(llm, "api_key_for", lambda choice: "k")
    calls: list = []
    _backend("end_turn", "{}", calls).complete(_choice(100), "s", "u")
    assert "thinking" not in calls[0]
    _backend("end_turn", "{}", calls).complete(_choice(2000), "s", "u")
    assert calls[1]["thinking"] == {"type": "adaptive"}
    with pytest.raises(RuntimeError, match="output limit"):
        _backend("max_tokens", "", calls).complete(_choice(2000), "s", "u")


def test_vector_stamp_reads_only_the_store_files(tmp_path):
    from knowledge import vector_index
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "big.bin").write_bytes(b"x")
    assert vector_index._newest(tmp_path) == 0.0
    (tmp_path / "chroma.sqlite3").write_bytes(b"x")
    assert vector_index._newest(tmp_path) > 0.0


def _call(roles, company="zensar"):
    from fastapi.testclient import TestClient
    from api.auth import issue_poc_token
    from api.main import app
    token = issue_poc_token({"sub": "u", "email": "u@example.com", "company": company, "roles": roles})
    return TestClient(app).get("/api/v1/mesh/governance/audit/verify", headers={"Authorization": f"Bearer {token}"})


def test_audit_verify_shows_a_person_only_the_ledger_of_their_own_company():
    own = _call(["group_user"])
    assert own.status_code == 200
    assert [n["node_id"] for n in own.json()["nodes"]] == ["zensar"]
    from shared.registry import node_ids
    assert {n["node_id"] for n in _call(["group_user", "mesh_admin"]).json()["nodes"]} == set(node_ids())


def test_a_listed_default_admin_email_is_refused_in_production():
    from shared.config import Settings
    with pytest.raises(ValueError, match="neuralmesh_admin_emails"):
        Settings(app_env="production", app_secret_key="x" * 40, neuralmesh_admin_emails="Presenter@NeuralMesh.local, ops@rpg.example")


def test_a_rebuilt_store_is_seen_by_a_process_that_had_it_open(tmp_path):
    import numpy as np
    from knowledge.vector_index import ChunkRow, VectorIndex
    import knowledge.vector_index as vi
    idx = VectorIndex(tmp_path)
    row = lambda k: ChunkRow(k, "E-01", "SUM", "low", "1", 0, f"text {k}", f"title {k}")
    idx.build([row("n:1")])
    q = np.ones(384, dtype="float32")
    idx.search(q, min_score=-1)  # opens the store
    import shutil, time
    time.sleep(0.01)
    other = VectorIndex(tmp_path)
    other.build([row("n:1"), row("n:2")])  # same process here, but the cached handle must still be dropped when the stamp moves
    keys = {k for k, _ in idx.search(q, min_score=-1)}
    assert "n:2" in keys
