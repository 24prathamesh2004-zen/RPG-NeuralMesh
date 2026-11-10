"""Regression tests for the code reviews of 2026-11-09 and 2026-11-11."""
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


# The code review of 2026-11-11


def test_the_stand_in_model_takes_a_misbehaviour_mode_by_post():
    """The checks switch the stand-in model to a misbehaviour with POST /control. The route had moved to another function."""
    from fastapi.testclient import TestClient

    from evaluations import standin_model_server as standin
    client = TestClient(standin.app)
    before = standin.STATE["mode"]
    try:
        assert client.post("/control", json={"mode": "no-cite"}).json()["mode"] == "no-cite"
        assert client.get("/control").json()["mode"] == "no-cite"
    finally:
        standin.STATE["mode"] = before


def test_a_json_file_nested_too_deeply_is_refused_with_a_reason():
    from services.uploads import UploadRefused, extract_text
    for data in (b"[" * 100_000 + b"]" * 100_000, b"[" * 900 + b'"a value far down in the lists"' + b"]" * 900):
        with pytest.raises(UploadRefused, match="nested too deeply"):
            extract_text("deep.json", data)
    text, fmt = extract_text("flat.json", b'{"plant": "Halol", "note": "Lots are kept off the floor and used first in, first out."}')
    assert fmt == "json" and text.startswith("plant: Halol")


def test_changes_of_the_upload_records_run_one_at_a_time(monkeypatch):
    """Two uploads at the same moment would take the same document id. Each function that writes the upload records
    holds one lock while it runs, so a second thread cannot get it. Nothing is written here: each call stops at its
    first check."""
    import threading

    from services import uploads
    got = []

    def another_thread_tries(result):
        def stub(*_args, **_kwargs):
            def attempt():
                free = uploads._WRITES.acquire(blocking=False)
                got.append(free)
                if free:
                    uploads._WRITES.release()
            thread = threading.Thread(target=attempt)
            thread.start()
            thread.join()
            return result
        return stub

    monkeypatch.setattr(uploads, "node_ids", another_thread_tries([]))
    with pytest.raises(uploads.UploadRefused, match="not a registered company"):
        uploads.add_upload(None, {}, "ceat", "E-03", "note", "", "note.txt", b"")
    monkeypatch.setattr(uploads, "record_of", another_thread_tries(None))
    with pytest.raises(KeyError):
        uploads.remove_upload("ceat", "ceat:E-03-U999", {})
    monkeypatch.setattr(uploads, "_all_records", another_thread_tries([]))
    with pytest.raises(KeyError):
        uploads.drop_graph("g-none", {})
    assert len(got) == 4 and not any(got)


def test_a_value_the_graph_does_not_have_is_not_written_as_the_word_none(monkeypatch, tmp_path):
    from services import json_templates as jt
    out = jt.render({"alone": "{graph.name}", "line": "Graph {graph.name} of {graph.id}"}, {"graph": {"graph.name": None, "graph.id": "g-1"}})
    assert out == {"alone": None, "line": "Graph  of g-1"}
    # a template file of a graph that does not hold a JSON object is passed over, and the graph gives the standard structure
    monkeypatch.setenv("NEURALMESH_TEMPLATE_PER_GRAPH", "1")
    monkeypatch.setenv("NEURALMESH_JSON_TEMPLATES", str(tmp_path))
    jt._graph_file("g-1").write_text("[]", encoding="utf-8")
    assert jt.of_graph("g-1") == (jt.DEFAULT, False)


def test_a_model_reply_whose_concepts_are_not_a_list_of_names_does_not_stop_the_form():
    from services import upload_suggest as us
    cands = [{"id": "concept:a", "label": "A", "found_by": "full name"}]
    graphs = [{"id": "g-1", "name": "One", "concepts": {"concept:a"}, "inputs": ["x"]}]
    ask = lambda reply: us.confirm(lambda *a: reply, "f.md", "T", "text", cands, graphs, ["report"], lambda c: c, reply)  # noqa: E731
    assert ask('{"kind": "report", "concepts": 5, "graph": "new"}') is None  # not a list: the code result stands
    assert ask('{"kind": "report", "concepts": {"concept:a": true}, "graph": "new"}') is None
    mixed = ask('{"kind": "report", "concepts": [{"id": "concept:a"}, ["concept:a"], "concept:a"], "graph": "new"}')
    assert mixed["concepts"] == ["concept:a"]  # an entry that is not a name is passed over
