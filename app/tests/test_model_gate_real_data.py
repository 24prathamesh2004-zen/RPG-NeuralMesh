"""The model policy and real data: a cloud model never reads an uploaded file that was not sent as invented, in Ask, at
upload and when a file is read before it is saved. A model of the group gateway, named at deployment, may read it."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from api.main import app
from contracts.evidence import EvidenceRecord
from services import uploads
from services.context import policy as model_policy
from tests.mesh_harness import FakeBackend
from tests.test_graph_extract import _concepts
from tests.test_uploads import ADMIN, _upload, mesh  # noqa: F401 - mesh is the fixture

APP = Path(__file__).resolve().parents[1]


def _use(monkeypatch, name):
    monkeypatch.setenv("NEURALMESH_MODEL_POLICY", str(APP / "config" / name))
    model_policy._load.cache_clear()


def test_one_real_upload_in_the_evidence_keeps_a_cloud_model_away_from_the_question(mesh, monkeypatch):
    _use(monkeypatch, "model_policy.json")
    assert model_policy.choice_for("answer").tier == "cloud"
    client = TestClient(app)
    a, b = _concepts(mesh)
    real = _upload(client, f"A real note of the plant on {a} and {b}, kept for the storage team only.", graph_name="Gate check real", datapoint="E-02").json()["document"]["id"]
    made_up = _upload(client, f"An invented note on {a} and {b}, written to test the model policy and nothing else.", title="Invented note", graph_name="Gate check invented",
                      datapoint="E-02", synthetic="true").json()["document"]["id"]
    assert uploads.is_real(real) and not uploads.is_real(made_up) and not uploads.is_real("ceat:E-02-01") and not uploads.is_real(None)
    orchestrator = mesh.orchestrator
    monkeypatch.setattr(orchestrator, "backend", FakeBackend(), raising=False)
    sample = EvidenceRecord(evidence_id="e1", kind="summary", node="ceat", document="ceat:E-02-01", sensitivity="Internal", text="sample")
    for records, decision in (([sample], "made"), ([sample, EvidenceRecord(evidence_id="e2", kind="summary", node="ceat", document=made_up, sensitivity="Internal", text="x")], "made"),
                              ([sample, EvidenceRecord(evidence_id="e3", kind="summary", node="ceat", document=real, sensitivity="Internal", text="x")], "blocked_by_policy")):
        calls: list[dict] = []
        orchestrator._caller({"trace_id": "t"}, calls, records)("answer", "system", "user")
        assert calls[-1]["decision"] == decision, (decision, calls[-1])
    # at upload and before a save: a file counts as real unless it was sent as invented
    kind_calls = [uploads._kind_caller(mesh, "Internal"), uploads._kind_caller(mesh, "Internal", True)]
    assert kind_calls[0]("kind", "s", "u") is None and kind_calls[1]("kind", "s", "u") is not None
    model_policy._load.cache_clear()


def test_the_gateway_policy_takes_its_model_from_the_environment_and_may_read_real_data(monkeypatch):
    _use(monkeypatch, "model_policy.group-gateway.json")
    monkeypatch.setenv("NEURALMESH_GATEWAY_BASE_URL", "http://10.0.0.5:8080/v1")
    monkeypatch.setenv("NEURALMESH_GATEWAY_MODEL", "inside-model-1")
    steps = json.loads((APP / "config" / "model_policy.json").read_text())["steps"]
    for step in steps:
        choice = model_policy.choice_for(step)
        assert (choice.tier, choice.model, choice.base_url, choice.api_key_env) == ("gateway", "inside-model-1", "http://10.0.0.5:8080/v1", "NEURALMESH_GATEWAY_API_KEY")
        assert model_policy.allowed(choice, "production", {"Restricted"}, all_synthetic=False) == (True, "allowed")
    assert model_policy.check_startup("production") == []
    monkeypatch.delenv("NEURALMESH_GATEWAY_MODEL")
    assert model_policy.choice_for("extract").model == "gpt-4.1-mini"  # the id of the file when the environment names none
    model_policy._load.cache_clear()


def test_a_cloud_model_reads_real_data_only_with_the_development_switch_and_never_outside_development(monkeypatch):
    _use(monkeypatch, "model_policy.json")
    cloud = model_policy.choice_for("extract")
    assert model_policy.allowed(cloud, "development", {"Restricted"}, all_synthetic=False)[0] is False
    _use(monkeypatch, "model_policy.dev-llm.json")
    cloud = model_policy.choice_for("extract")
    assert cloud.tier == "cloud" and model_policy.allowed(cloud, "development", {"Restricted"}, all_synthetic=False) == (True, "allowed")
    assert model_policy.allowed(cloud, "development", {"Restricted"}, all_synthetic=True) == (True, "allowed")
    for env in ("production", "staging"):
        assert model_policy.allowed(cloud, env, {"Internal"}, all_synthetic=False) == (False, "cloud tier is allowed in development only")
    model_policy._load.cache_clear()
