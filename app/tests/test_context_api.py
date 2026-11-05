"""Context API for SkillForge (/api/v1/context): the six tools, the talent import and the service identity."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.auth import issue_poc_token
from api.main import app
from api.routers import context as context_router
from api.routers import mesh as mesh_router
from knowledge.validator import validate_packs
from services import context_api
from tests.mesh_harness import build_mesh

APP = Path(__file__).resolve().parents[1]
TALENT = APP / "neuralmesh_kb_pack" / "talent_import"
USER = {"user_id": "sf-1042", "company": "harrisons", "roles": ["group_user"]}


@pytest.fixture
def client(monkeypatch, tmp_path):
    orchestrator, transport, mesh = build_mesh()
    rt = SimpleNamespace(mesh=mesh, store=mesh.store, orchestrator=orchestrator, export_status={}, group_packs=[])
    monkeypatch.setattr(context_router, "runtime", lambda: rt)
    monkeypatch.setattr(mesh_router, "runtime", lambda: rt)
    monkeypatch.setattr(context_api, "TALENT_IMPORT", tmp_path / "talent_import")
    mesh_router._graph.cache_clear()
    token = issue_poc_token({"sub": "svc:skillforge", "company": "group", "roles": ["context_client", "talent_exporter"]})
    yield TestClient(app), {"Authorization": f"Bearer {token}"}, transport, rt
    mesh_router._graph.cache_clear()


def test_context_routes_need_the_service_identity(client):
    http, _, _, _ = client
    person = issue_poc_token({"sub": "u", "company": "ceat", "roles": ["group_user"]})
    assert http.post("/api/v1/context/find_mentors", json={"skill": "skill:engineering"}).status_code in (401, 403)
    response = http.post("/api/v1/context/find_mentors", json={"skill": "skill:engineering"},
                         headers={"Authorization": f"Bearer {person}"})
    assert response.status_code == 403


def test_role_context_lists_required_skills_as_skillforge_holds_them(client):
    http, headers, _, _ = client
    body = http.post("/api/v1/context/role_context", json={"role_id": "ceat:role/quality-engineer"}, headers=headers).json()
    levels = {s["skill"]: s["level"] for s in body["required_skills"]}
    assert levels == {"skill:engineering": "A", "skill:manufacturing": "M", "skill:r-and-d-npd": "M",
                      "skill:quality-management": "M"}
    qm = next(s for s in body["required_skills"] if s["skill"] == "skill:quality-management")
    assert {c["id"] for c in qm["concepts"]} >= {"concept:incoming-quality-control", "concept:supplier-feedback-loop"}
    assert http.post("/api/v1/context/role_context", json={"title": "Quality Engineer", "company": "ceat"},
                     headers=headers).json()["role"] == "ceat:role/quality-engineer"


def test_learning_sources_respect_purpose_level_and_supersedes(client):
    http, headers, transport, _ = client
    body = http.post("/api/v1/context/learning_sources",
                     json={"user": USER, "skill": "quality management", "target_level": "M"}, headers=headers).json()
    docs = [s["evidence_id"] for s in body["sources"]]
    assert set(docs) == {"ceat:E-03-01", "ceat:E-03-04"}
    assert all(s["delivery"] == "by_reference" and s["text"] and s["schema_version"] == "1.0" for s in body["sources"])
    assert any(d["reason"] == "explains the skill up to level L only" for d in body["dropped"])
    summarize = [c for c in transport.calls if c[1] == "summarize"]
    assert summarize and all(c[2]["purpose"] == "learning" for c in summarize)

    manufacturing = http.post("/api/v1/context/learning_sources",
                              json={"user": USER, "skill": "skill:manufacturing", "target_level": "L"}, headers=headers).json()
    assert "ceat:E-03-06" not in [s["evidence_id"] for s in manufacturing["sources"]]


def test_find_mentors_returns_consented_experts_without_names(client):
    http, headers, _, _ = client
    body = http.post("/api/v1/context/find_mentors", json={"skill": "skill:quality-management"}, headers=headers).json()
    ids = {m["evidence_id"] for m in body["mentors"]}
    assert "ceat:expert/CE-1" in ids and "harrisons:expert/HE-4" not in ids
    assert "Rohan" not in json.dumps(body)


def test_skill_context_fetches_text_with_the_end_users_identity(client):
    http, headers, transport, _ = client
    body = http.post("/api/v1/context/skill_context",
                     json={"user": USER, "skill": "skill:quality-management", "level": "M", "purpose": "learning"},
                     headers=headers).json()
    assert body["label"] == "Quality Management" and "QA" in body["aliases"]
    assert any(e.get("text") for e in body["evidence"])
    assert {r["role"] for r in body["roles_requiring"]} == {"ceat:role/quality-engineer"}


def test_ask_returns_records_and_strips_contact_details(client):
    http, headers, _, _ = client
    body = http.post("/api/v1/context/ask", headers=headers, json={
        "user": USER, "purpose": "problem_solving",
        "question": "What learnings from CEAT could reduce latex spoilage at Harrisons? I am at me@rpg.example"}).json()
    assert body["schema_version"] == "1.0" and body["contact_details_removed"] == 1
    assert "rpg.example" not in body["question"]
    assert body["evidence"] and all(r["schema_version"] == "1.0" for r in body["evidence"])
    assert body["answer_status"] == "evidence_only"


def test_vocabulary_export_is_a_valid_group_pack_with_aliases(client):
    http, headers, _, _ = client
    pack = http.get("/api/v1/context/vocabulary_export", headers=headers).json()
    pack.pop("embedding_model")
    assert validate_packs([("export", pack)]).errors == []
    qm = next(e for e in pack["entities"] if e["id"] == "skill:quality-management")
    assert "quality assurance" in qm["aliases"]


def test_talent_import_accepts_skillforge_export_and_refuses_bad_packs(client):
    http, headers, _, rt = client
    skills = json.loads((TALENT / "group.skills.pack.json").read_text())
    talent = json.loads((TALENT / "ceat.talent.pack.json").read_text())
    skills["entities"][0]["aliases"] = ["manufacturing operations", "production"]
    talent["entities"].append({"id": "ceat:role/plant-supervisor", "type": "Role", "label": "Plant Supervisor",
                               "aliases": ["shift supervisor"], "subsidiary": "ceat", "domain": "talent"})
    talent["relationships"].append({"id": "rel:ceat.talent/plant-1", "type": "REQUIRES_SKILL",
                                    "from": "ceat:role/plant-supervisor", "to": "skill:manufacturing",
                                    "properties": {"level": "M", "importance": "required"}, "status": "approved",
                                    "provenance": {"method": "imported", "by_role": "SkillForge", "created_at": "2026-11-05"}})
    ok = http.post("/api/v1/context/talent-packs", json={"packs": [skills, talent]}, headers=headers)
    assert ok.status_code == 200, ok.text
    assert ok.json()["roles"] == 4 and ok.json()["requirements"] == 11
    assert rt.mesh.resolve("what does a production lead need")["concepts"].get("skill:manufacturing") == "production"
    role = http.post("/api/v1/context/role_context", json={"role_id": "ceat:role/plant-supervisor"}, headers=headers).json()
    assert role["required_skills"][0]["skill"] == "skill:manufacturing"

    unknown = copy.deepcopy(talent)
    unknown["relationships"][-1]["to"] = "skill:welding"
    bad = http.post("/api/v1/context/talent-packs", json={"packs": [unknown]}, headers=headers)
    assert bad.status_code == 422 and "skill:welding" in bad.text
    people = copy.deepcopy(talent)
    people["experts"] = [{"id": "ceat:expert/X", "role": "x", "skills": [{"skill": "skill:hr"}], "evidence": [], "consent": True}]
    assert http.post("/api/v1/context/talent-packs", json={"packs": [people]}, headers=headers).status_code == 422


def test_mcp_gateway_offers_the_six_context_tools():
    import asyncio as _asyncio

    from mcp_gateway.server import create_gateway

    tools = _asyncio.run(create_gateway(port=18100).list_tools())
    assert {t.name for t in tools} == {"role_context", "skill_context", "ask", "learning_sources", "find_mentors",
                                       "vocabulary_export"}


def test_group_packs_never_replace_the_company_entries_of_the_node_exports():
    from services.mesh_graph import load_group_pack_files
    from services.mesh_runtime import GROUP_FOLDERS

    _, _, mesh = build_mesh()
    load_group_pack_files(mesh, GROUP_FOLDERS)  # the order of a refresh: node exports first, then the group packs
    mesh.rebuild()
    for node in ("ceat", "kec", "zensar", "harrisons"):
        data = mesh.graph.nodes[f"org:{node}"]
        assert node in data["aliases"] and data.get("level") and data.get("owner") == "Mesh team"
    assert mesh.resolve("How does Harrisons handle latex spoilage?")["named_subsidiaries"] == ["harrisons"]
    assert mesh.resolve("What did KEC learn about tower foundations?")["named_subsidiaries"] == ["kec"]


def test_a_role_has_one_company_link_that_is_retired_when_the_talent_pack_drops_it(client):
    http, headers, _, rt = client
    skills = json.loads((TALENT / "group.skills.pack.json").read_text())
    talent = json.loads((TALENT / "ceat.talent.pack.json").read_text())
    talent["entities"].append({"id": "ceat:role/plant-supervisor", "type": "Role", "label": "Plant Supervisor",
                               "subsidiary": "ceat", "domain": "talent"})
    assert http.post("/api/v1/context/talent-packs", json={"packs": [skills, talent]}, headers=headers).status_code == 200

    def links(role):
        return [d for _, _, d in rt.mesh.graph.out_edges(role, data=True) if d["type"] == "ROLE_AT"]

    assert [d["status"] for d in links("ceat:role/plant-supervisor")] == ["approved"]
    assert [d["status"] for d in links("ceat:role/quality-engineer")] == ["approved"]
    talent["entities"] = [e for e in talent["entities"] if e["id"] != "ceat:role/plant-supervisor"]
    assert http.post("/api/v1/context/talent-packs", json={"packs": [talent]}, headers=headers).status_code == 200
    assert [d["status"] for d in links("ceat:role/plant-supervisor")] == ["retired"]
    assert [d["status"] for d in links("ceat:role/quality-engineer")] == ["approved"]


def test_every_record_the_context_api_returns_follows_the_contract(client):
    from contracts.evidence import EvidenceRecord, RelationshipRef

    http, headers, _, _ = client
    record_fields, link_fields = set(EvidenceRecord.model_fields), set(RelationshipRef.model_fields)

    def check(records):
        for r in records:
            assert set(r) <= record_fields, set(r) - record_fields
            EvidenceRecord.model_validate(r)

    learning = http.post("/api/v1/context/learning_sources",
                         json={"user": USER, "skill": "quality management", "target_level": "M"}, headers=headers).json()
    check(learning["sources"])
    mentors = http.post("/api/v1/context/find_mentors", json={"skill": "skill:quality-management"}, headers=headers).json()
    check(mentors["mentors"])
    assert all(m["expert"]["name_available_after_intro_approval"] for m in mentors["mentors"])
    skill = http.post("/api/v1/context/skill_context", headers=headers,
                      json={"user": USER, "skill": "skill:quality-management", "level": "M", "purpose": "learning"}).json()
    check(skill["evidence"] + skill["consented_experts"])
    import yaml

    golden = yaml.safe_load((APP / "neuralmesh_kb_pack" / "kb" / "golden.yaml").read_text())["scenarios"][0]
    ask = http.post("/api/v1/context/ask", headers=headers, json={
        "user": {**USER, "company": "ceat"}, "purpose": "problem_solving", "question": golden["question"]}).json()
    assert ask["schema_version"] == "1.0"
    check(ask["evidence"] + ask["also_found"] + ask["withheld"])
    assert ask["withheld"] and ask["relationships"]
    for link in ask["relationships"]:
        assert set(link) <= link_fields, set(link) - link_fields
        RelationshipRef.model_validate(link)
