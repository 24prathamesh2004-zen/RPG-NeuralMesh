"""The context contract over REST (/api/v1/context/<tool>): every tool answered in the one envelope and answer shape,
the import tool, the service identity, and the records of every answer following the evidence record contract."""
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
from services import context_api, context_import
from tests.mesh_harness import build_mesh
from shared.registry import node_ids

APP = Path(__file__).resolve().parents[1]
TALENT = Path(__file__).resolve().parent / "fixtures" / "talent_import"  # the pinned sample packs, not the last import
PERSON = {"subsidiary": "harrisons", "roles": ["user"], "user_ref": "skillforge:1042"}
SERVICE = {"subsidiary": "group", "roles": ["service"]}


def envelope(tool: str, inp: dict | None = None, purpose: str = "learning", caller: dict | None = None, version: str = "1.0") -> dict:
    return {"schema_version": version, "tool": tool, "purpose": purpose, "caller": caller or PERSON, "input": inp or {}}


async def _load_kept(rt, companies, group_changed, folder):
    """The test mesh has no node processes: load the kept packs straight into the graph, as a node refresh would."""
    for path in sorted(folder.glob("*.pack.json")):
        pack = json.loads(path.read_text())
        pid = pack["pack"]["pack_id"]
        rt.mesh.load_group_pack(pack, source=f"pack:{pid}" if pid.startswith("group.") else f"talent:{pid}")
    rt.mesh.rebuild()
    return {c: "loaded 0 entities, 0 relationships" for c in companies}  # what the real refresh answers for a node that responded


@pytest.fixture
def client(monkeypatch, tmp_path):
    orchestrator, transport, mesh = build_mesh()
    rt = SimpleNamespace(mesh=mesh, store=mesh.store, orchestrator=orchestrator, export_status={}, group_packs=[])
    monkeypatch.setattr(context_router, "runtime", lambda: rt)
    monkeypatch.setattr(mesh_router, "runtime", lambda: rt)
    monkeypatch.setattr(context_api, "TALENT_IMPORT", tmp_path / "talent_import")
    monkeypatch.setattr(context_import, "apply_changes", _load_kept)
    mesh_router._graph.cache_clear()
    token = issue_poc_token({"sub": "svc:skillforge", "company": "group", "roles": ["context_client", "talent_exporter"]})
    headers = {"Authorization": f"Bearer {token}"}
    http = TestClient(app)

    def call(tool: str, inp: dict | None = None, **kw) -> dict:
        response = http.post(f"/api/v1/context/{tool}", json=envelope(tool, inp, **kw), headers=headers)
        assert response.status_code == 200, response.text
        return response.json()

    yield SimpleNamespace(http=http, headers=headers, transport=transport, rt=rt, call=call)
    mesh_router._graph.cache_clear()


def test_context_routes_need_a_registered_service_identity(client):
    body = envelope("find_mentors", {"skill": "skill:engineering"})
    assert client.http.post("/api/v1/context/find_mentors", json=body).status_code in (401, 403)
    person = issue_poc_token({"sub": "u", "company": "ceat", "roles": ["group_user"]})
    assert client.http.post("/api/v1/context/find_mentors", json=body, headers={"Authorization": f"Bearer {person}"}).status_code == 403
    stranger = issue_poc_token({"sub": "svc:unknown", "company": "group", "roles": ["context_client"]})
    refused = client.http.post("/api/v1/context/find_mentors", json=body, headers={"Authorization": f"Bearer {stranger}"})
    assert refused.status_code == 403 and refused.json()["code"] == "not_allowed"
    assert refused.headers["content-type"].startswith("application/problem+json")


def test_role_context_lists_required_skills_as_skillforge_holds_them(client):
    body = client.call("role_context", {"role": "ceat:role/quality-engineer"})
    from contracts.context import CONTRACT_VERSION
    assert body["status"] == "ok" and body["schema_version"] == CONTRACT_VERSION and body["records"] == []
    levels = {s["skill"]: s["level"] for s in body["data"]["required_skills"]}
    assert levels == {"skill:engineering": "A", "skill:manufacturing": "M", "skill:r-and-d-npd": "M", "skill:quality-management": "M"}
    qm = next(s for s in body["data"]["required_skills"] if s["skill"] == "skill:quality-management")
    assert {c["id"] for c in qm["concepts"]} >= {"concept:incoming-quality-control", "concept:supplier-feedback-loop"}
    assert all(set(r) >= {"id", "label", "subsidiary"} for r in body["data"]["similar_roles"])
    assert client.call("role_context", {"title": "Quality Engineer", "company": "ceat"})["data"]["role"] == "ceat:role/quality-engineer"


def test_similar_roles_share_two_skills_that_are_half_of_the_smaller_role(client):
    similar = {r["id"]: r["shared_skill_share"] for r in client.call("role_context", {"role": "ceat:role/process-engineer"})["data"]["similar_roles"]}
    assert similar == {"ceat:role/quality-engineer": 0.67, "ceat:role/sales-executive": 0.67}
    # Sales Executive shares one skill with Quality Engineer (Manufacturing): one shared skill is not enough
    quality = client.call("role_context", {"role": "ceat:role/quality-engineer"})["data"]["similar_roles"]
    assert [r["id"] for r in quality] == ["ceat:role/process-engineer"]


def test_skills_a_person_joined_with_an_approved_same_as_count_as_one_skill(client):
    g = client.rt.mesh.graph
    # Quality Management and HR joined: Quality Engineer then shares Manufacturing and HR with Sales Executive
    g.add_edge("skill:quality-management", "skill:hr", key="rel:test/same", type="SAME_AS", status="approved", properties={})
    quality = {r["id"] for r in client.call("role_context", {"role": "ceat:role/quality-engineer"})["data"]["similar_roles"]}
    assert quality == {"ceat:role/process-engineer", "ceat:role/sales-executive"}
    g.remove_edge("skill:quality-management", "skill:hr", key="rel:test/same")
    g.add_edge("skill:quality-management", "skill:hr", key="rel:test/same", type="SAME_AS", status="proposed", properties={})
    quality = {r["id"] for r in client.call("role_context", {"role": "ceat:role/quality-engineer"})["data"]["similar_roles"]}
    assert quality == {"ceat:role/process-engineer"}  # a proposed link is not a join


def test_an_import_waits_while_another_process_holds_the_folder_lock(client):
    import fcntl
    import os
    import threading
    import time

    skills, talent = _skillforge_packs()
    folder = context_api.TALENT_IMPORT
    folder.mkdir(parents=True, exist_ok=True)
    fd = os.open(folder / context_import.LOCK_FILE, os.O_RDWR | os.O_CREAT)
    fcntl.flock(fd, fcntl.LOCK_EX)  # a second open file holds the lock, as another API process would
    done: dict = {}
    worker = threading.Thread(target=lambda: done.setdefault("body", client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)))
    worker.start()
    try:
        time.sleep(0.6)
        assert worker.is_alive() and not (folder / "import_log.json").exists()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)
    worker.join(30)
    assert not worker.is_alive() and done["body"]["status"] == "ok"
    assert set(json.loads((folder / "import_log.json").read_text())) == {"group.skills", "ceat.talent"}


def test_a_retired_skill_is_not_required_and_makes_no_role_similar(client):
    client.rt.mesh.graph.nodes["skill:engineering"]["retired"] = True
    body = client.call("role_context", {"role": "ceat:role/process-engineer"})["data"]
    assert "skill:engineering" not in {s["skill"] for s in body["required_skills"]}
    # Process Engineer keeps HR and Manufacturing, both required by Sales Executive. Quality Engineer shares one of them.
    assert {r["id"]: r["shared_skill_share"] for r in body["similar_roles"]} == {"ceat:role/sales-executive": 1.0}


def test_a_call_whose_packs_are_all_refused_takes_no_lock_and_writes_no_file(client):
    folder = context_api.TALENT_IMPORT
    assert not folder.exists()
    _, talent = _skillforge_packs()
    ventures = copy.deepcopy(talent)
    ventures["pack"].update({"pack_id": "ventures.talent", "subsidiary": "ventures"})
    stranger = copy.deepcopy(talent)
    stranger["pack"]["pack_id"] = "someone.else"
    body = client.call("import", {"packs": [ventures, stranger]}, purpose="career_mobility", caller=SERVICE)
    assert body["status"] == "refused"
    assert [r["code"] for r in body["data"]["packs"]] == ["company_not_connected", "pack_refused"]
    assert not folder.exists()


def test_a_cancelled_wait_for_the_folder_lock_leaves_no_lock_behind(tmp_path):
    import asyncio
    import fcntl
    import os

    folder = tmp_path / "talent_import"
    folder.mkdir()
    holder = os.open(folder / context_import.LOCK_FILE, os.O_RDWR | os.O_CREAT)
    fcntl.flock(holder, fcntl.LOCK_EX)

    async def scenario():
        async def wait_for_lock():
            async with context_import._folder_lock(folder):
                await asyncio.sleep(0)

        waiter = asyncio.create_task(wait_for_lock())
        await asyncio.sleep(0.2)
        waiter.cancel()
        with pytest.raises(asyncio.CancelledError):
            await waiter
        fcntl.flock(holder, fcntl.LOCK_UN)
        os.close(holder)

        # the cancelled wait gets the lock late, and closing its file then releases it
        async def take():
            async with context_import._folder_lock(folder):
                return True
        return await asyncio.wait_for(take(), timeout=5)

    assert asyncio.run(scenario())


def test_learning_sources_respect_purpose_level_and_supersedes(client):
    body = client.call("learning_sources", {"skill": "quality management", "level": "M"})
    assert {r["evidence_id"] for r in body["records"]} == {"ceat:E-03-01", "ceat:E-03-04"}
    assert all(r["delivery"] == "by_reference" and r["text"] for r in body["records"])
    assert any(d["reason"] == "explains the skill up to level L only" for d in body["data"]["dropped"])
    summarize = [c for c in client.transport.calls if c[1] == "summarize"]
    assert summarize and all(c[2]["purpose"] == "learning" for c in summarize)
    manufacturing = client.call("learning_sources", {"skill": "skill:manufacturing", "level": "L"})
    assert "ceat:E-03-06" not in [r["evidence_id"] for r in manufacturing["records"]]


def test_find_mentors_returns_consented_experts_without_names(client):
    body = client.call("find_mentors", {"skill": "skill:quality-management"})
    ids = {r["evidence_id"] for r in body["records"]}
    assert "ceat:expert/CE-1" in ids and "harrisons:expert/HE-4" not in ids
    assert all(r["kind"] == "expert" for r in body["records"]) and "Rohan" not in json.dumps(body)


def test_skill_context_fetches_text_with_the_end_users_identity(client):
    body = client.call("skill_context", {"skill": "skill:quality-management", "level": "M"})
    assert body["data"]["label"] == "Quality Management" and "QA" in body["data"]["aliases"]
    assert any(r.get("text") for r in body["records"])
    assert {r["role"] for r in body["data"]["roles_requiring"]} == {"ceat:role/quality-engineer"}


def test_ask_returns_records_and_strips_contact_details(client):
    body = client.call("ask", {"question": "What learnings from CEAT could reduce latex spoilage at Harrisons? I am at me@rpg.example"},
                       purpose="problem_solving")
    assert body["data"]["contact_details_removed"] == 1 and "rpg.example" not in json.dumps(body)
    assert body["records"] and all(r["schema_version"] == "1.0" for r in body["records"])
    assert body["data"]["answer_status"] == "evidence_only" and body["answer"] is None
    assert all(isinstance(c, str) for c in body["also_found"])


def test_ask_asks_only_the_companies_the_caller_names(client):
    body = client.call("ask", {"question": "How is quality managed for incoming material?", "nodes": ["ceat"]}, purpose="problem_solving")
    assert body["data"]["routing"].get("subsidiaries") == ["ceat"]
    wrong = client.call("ask", {"question": "How is quality managed?", "nodes": ["acme"]}, purpose="problem_solving")
    assert wrong["status"] == "refused" and wrong["problem"]["code"] == "invalid_input"
    assert "ceat" in wrong["problem"]["fields"][0]["allowed"]


def test_vocabulary_export_is_a_valid_group_pack_with_aliases(client):
    body = client.call("vocabulary_export", purpose="career_mobility", caller=SERVICE)
    pack = dict(body["data"])
    pack.pop("embedding_model")
    assert validate_packs([("export", pack)]).errors == []
    qm = next(e for e in pack["entities"] if e["id"] == "skill:quality-management")
    assert "quality assurance" in qm["aliases"]


def _skillforge_packs():
    skills = json.loads((TALENT / "group.skills.pack.json").read_text())
    skills["pack"]["pack_id"] = "group.skillforge-skills"  # SkillForge's own name, kept as group.skills by the registry
    talent = json.loads((TALENT / "ceat.talent.pack.json").read_text())
    return skills, talent


def test_import_keeps_packs_under_the_registry_name_and_says_what_was_refused(client):
    skills, talent = _skillforge_packs()
    skills["entities"][0]["aliases"] = ["manufacturing operations", "production"]
    talent["entities"].append({"id": "ceat:role/plant-supervisor", "type": "Role", "label": "Plant Supervisor",
                               "aliases": ["shift supervisor"], "subsidiary": "ceat", "domain": "talent"})
    talent["relationships"].append({"id": "rel:ceat.talent/plant-1", "type": "REQUIRES_SKILL", "from": "ceat:role/plant-supervisor",
                                    "to": "skill:manufacturing", "properties": {"level": "M", "importance": "required"},
                                    "status": "approved", "provenance": {"method": "imported", "by_role": "SkillForge", "created_at": "2026-11-05"}})
    ventures = copy.deepcopy(talent)
    ventures["pack"].update({"pack_id": "ventures.talent", "subsidiary": "ventures"})
    body = client.call("import", {"packs": [skills, talent, ventures]}, purpose="career_mobility", caller=SERVICE)
    results = {r["pack_id"]: r for r in body["data"]["packs"]}
    assert results["group.skillforge-skills"]["result"] == "loaded" and results["group.skillforge-skills"]["kept_as"] == "group.skills"
    assert results["ceat.talent"]["result"] == "loaded" and results["ceat.talent"]["roles"] == 4 and results["ceat.talent"]["requirements"] == 11
    assert results["ventures.talent"]["result"] == "refused" and results["ventures.talent"]["code"] == "company_not_connected"
    assert body["status"] == "partial" and body["problem"]["code"] == "pack_refused"
    kept = json.loads((context_api.TALENT_IMPORT / "group.skills.pack.json").read_text())
    assert kept["pack"]["pack_id"] == "group.skills"
    assert client.rt.mesh.resolve("what does a production lead need")["concepts"].get("skill:manufacturing") == "production"
    role = client.call("role_context", {"role": "ceat:role/plant-supervisor"})
    assert role["data"]["required_skills"][0]["skill"] == "skill:manufacturing"

    again = client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)
    assert {r["result"] for r in again["data"]["packs"]} == {"unchanged"} and again["status"] == "ok"

    unknown = copy.deepcopy(talent)
    unknown["relationships"][-1]["to"] = "skill:welding"
    bad = client.call("import", {"packs": [unknown]}, purpose="career_mobility", caller=SERVICE)
    assert bad["status"] == "refused" and "skill:welding" in bad["data"]["packs"][0]["reason"]
    people = copy.deepcopy(talent)
    people["experts"] = [{"id": "ceat:expert/X", "role": "x", "skills": [{"skill": "skill:hr"}], "evidence": [], "consent": True}]
    assert client.call("import", {"packs": [people]}, purpose="career_mobility", caller=SERVICE)["data"]["packs"][0]["code"] == "pack_refused"
    other = copy.deepcopy(talent)
    other["pack"]["pack_id"] = "ceat.engineering"
    assert client.call("import", {"packs": [other]}, purpose="career_mobility", caller=SERVICE)["data"]["packs"][0]["code"] == "pack_refused"


def test_a_role_has_one_company_link_that_is_retired_when_the_talent_pack_drops_it(client):
    skills, talent = _skillforge_packs()
    talent["entities"].append({"id": "ceat:role/plant-supervisor", "type": "Role", "label": "Plant Supervisor",
                               "subsidiary": "ceat", "domain": "talent"})
    assert client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)["status"] == "ok"

    def links(role):
        return [d for _, _, d in client.rt.mesh.graph.out_edges(role, data=True) if d["type"] == "ROLE_AT"]

    assert [d["status"] for d in links("ceat:role/plant-supervisor")] == ["approved"]
    talent["entities"] = [e for e in talent["entities"] if e["id"] != "ceat:role/plant-supervisor"]
    assert client.call("import", {"packs": [talent]}, purpose="career_mobility", caller=SERVICE)["status"] == "ok"
    assert [d["status"] for d in links("ceat:role/plant-supervisor")] == ["retired"]
    assert [d["status"] for d in links("ceat:role/quality-engineer")] == ["approved"]


def test_group_packs_never_replace_the_company_entries_of_the_node_exports():
    from services.mesh_graph import load_group_pack_files
    from services.mesh_runtime import GROUP_FOLDERS

    _, _, mesh = build_mesh()
    load_group_pack_files(mesh, GROUP_FOLDERS)  # the order of a refresh: node exports first, then the group packs
    mesh.rebuild()
    for node in node_ids():
        data = mesh.graph.nodes[f"org:{node}"]
        assert node in data["aliases"] and data.get("level") and data.get("owner") == "Mesh team"
    assert mesh.resolve("How does Harrisons handle latex spoilage?")["named_subsidiaries"] == ["harrisons"]
    assert mesh.resolve("What did KEC learn about tower foundations?")["named_subsidiaries"] == ["kec"]


def test_every_record_the_context_api_returns_follows_the_contract(client):
    from contracts.evidence import EvidenceRecord, RelationshipRef
    import yaml

    record_fields, link_fields = set(EvidenceRecord.model_fields), set(RelationshipRef.model_fields)

    def check(records):
        for r in records:
            assert set(r) <= record_fields, set(r) - record_fields
            EvidenceRecord.model_validate(r)

    check(client.call("learning_sources", {"skill": "quality management", "level": "M"})["records"])
    mentors = client.call("find_mentors", {"skill": "skill:quality-management"})
    check(mentors["records"])
    assert all(m["expert"]["name_available_after_intro_approval"] for m in mentors["records"])
    skill = client.call("skill_context", {"skill": "skill:quality-management", "level": "M"})
    check(skill["records"] + skill["data"]["consented_experts"])
    golden = yaml.safe_load((APP / "neuralmesh_kb_pack" / "kb" / "golden.yaml").read_text())["scenarios"][0]
    ask = client.call("ask", {"question": golden["question"]}, purpose="problem_solving", caller={**PERSON, "subsidiary": "ceat"})
    check(ask["records"] + ask["data"]["also_found_records"] + ask["data"]["withheld"])
    assert ask["data"]["withheld"] and ask["data"]["relationships"]
    for link in ask["data"]["relationships"]:
        assert set(link) <= link_fields, set(link) - link_fields
        RelationshipRef.model_validate(link)


def _talent_with(extra_datapoint=None, approvals=None, foreign_role=False, relationship_type=None):
    _, talent = _skillforge_packs()
    talent = copy.deepcopy(talent)
    if extra_datapoint:
        talent.setdefault("datapoints", []).append(extra_datapoint)
    if approvals:
        talent["relationships"][0]["approvals"] = approvals
    if foreign_role:
        talent["entities"].append({"id": "kec:role/site-engineer", "type": "Role", "label": "Site Engineer", "subsidiary": "kec"})
    if relationship_type:
        talent["relationships"][0]["type"] = relationship_type
    return talent


@pytest.mark.parametrize("kwargs, words", [
    ({"extra_datapoint": {"id": "ceat:T-99", "catalogue_id": "E-01", "title": "x", "sensitivity": "Internal", "ceiling": "SUM",
                          "owner_role": "x", "purposes_allowed": ["learning"]}}, "datapoint ceat:T-99"),
    ({"extra_datapoint": {"id": "ceat:T-01", "catalogue_id": "T-01", "title": "x", "sensitivity": "Internal", "ceiling": "SUM",
                          "owner_role": "x", "purposes_allowed": ["learning", "bid_support"]}}, "opens purposes"),
    ({"approvals": [{"subsidiary": "ceat", "role": "x"}, {"subsidiary": "kec", "role": "y"}]}, "carries approvals"),
    ({"foreign_role": True}, "not in the namespace ceat"),
    ({"relationship_type": "SIMILAR_TO"}, "of type SIMILAR_TO"),
])
def test_a_pack_that_holds_more_than_its_rule_allows_is_refused_and_changes_nothing(client, kwargs, words):
    before = sorted(p.name for p in context_api.TALENT_IMPORT.glob("*.json")) if context_api.TALENT_IMPORT.is_dir() else []
    body = client.call("import", {"packs": [_talent_with(**kwargs)]}, purpose="career_mobility", caller=SERVICE)
    result = body["data"]["packs"][0]
    assert body["status"] == "refused" and result["result"] == "refused" and words in result["reason"], result
    after = sorted(p.name for p in context_api.TALENT_IMPORT.glob("*.json")) if context_api.TALENT_IMPORT.is_dir() else []
    assert after == before


def test_a_pack_whose_node_did_not_answer_is_kept_and_loads_on_the_next_send(client, monkeypatch):
    skills, talent = _skillforge_packs()
    answers = iter([{"ceat": "unavailable: ConnectError"}, {"ceat": "loaded 40 entities, 30 relationships"}])

    async def node_down_once(rt, companies, group_changed, folder):
        await _load_kept(rt, companies, group_changed, folder)
        return next(answers)
    monkeypatch.setattr(context_import, "apply_changes", node_down_once)
    first = client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)
    results = {r["pack_id"]: r for r in first["data"]["packs"]}
    assert results["group.skillforge-skills"]["result"] == "loaded"
    assert results["ceat.talent"]["result"] == "refused" and results["ceat.talent"]["code"] == "node_unavailable"
    assert (context_api.TALENT_IMPORT / "ceat.talent.pack.json").is_file()
    assert "ceat.talent" not in json.loads((context_api.TALENT_IMPORT / "import_log.json").read_text())
    second = client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)
    assert {r["pack_id"]: r["result"] for r in second["data"]["packs"]} == {"group.skillforge-skills": "unchanged", "ceat.talent": "loaded"}


def test_a_failed_import_puts_back_the_kept_packs_and_the_node_packs(client, monkeypatch):
    from services import context_import as ci

    skills, talent = _skillforge_packs()
    assert client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)["status"] == "ok"
    kept_before = (context_api.TALENT_IMPORT / "ceat.talent.pack.json").read_bytes()
    node_pack = ci._node_pack("ceat")
    node_before = node_pack.read_bytes()
    changed = copy.deepcopy(talent)
    changed["entities"][0]["label"] += " changed"

    async def breaks(rt, companies, group_changed, folder):
        node_pack.write_text("{ half written")
        raise RuntimeError("the pack build failed")

    async def no_refresh():
        return {}
    client.rt.refresh_from_nodes = no_refresh
    monkeypatch.setattr(ci, "apply_changes", breaks)
    body = client.call("import", {"packs": [changed]}, purpose="career_mobility", caller=SERVICE)
    reason = body["data"]["packs"][0]["reason"]
    assert body["status"] == "refused" and "nothing was changed" in reason and "Send it again later" in reason
    assert (context_api.TALENT_IMPORT / "ceat.talent.pack.json").read_bytes() == kept_before
    assert node_pack.read_bytes() == node_before

    # A check that fails at the rebuild names its reason: sending the same pack again would never help.
    from knowledge.validator import PackCheckFailed

    async def fails_a_check(rt, companies, group_changed, folder):
        raise PackCheckFailed("Pack validation failed: ERROR   references: skill:x is referenced 1 time(s) in ceat.talent but defined in none of the loaded packs")
    monkeypatch.setattr(ci, "apply_changes", fails_a_check)
    reason = client.call("import", {"packs": [changed]}, purpose="career_mobility", caller=SERVICE)["data"]["packs"][0]["reason"]
    assert reason.startswith("references: skill:x is referenced") and "Send it again" not in reason and "Nothing was changed." in reason

    # Any other ValueError (a file that does not parse) is not a check of the packs: the next send tries again
    async def breaks_on_a_file(rt, companies, group_changed, folder):
        raise json.JSONDecodeError("Expecting value", "", 0)
    monkeypatch.setattr(ci, "apply_changes", breaks_on_a_file)
    reason = client.call("import", {"packs": [changed]}, purpose="career_mobility", caller=SERVICE)["data"]["packs"][0]["reason"]
    assert "Send it again later" in reason


def _presenter() -> dict:
    token = issue_poc_token({"sub": "presenter@neuralmesh.local", "company": "group", "roles": ["group_user", "mesh_admin"]})
    return {"Authorization": f"Bearer {token}"}


def _joined_skills_pack(replaces: bool):
    """SkillForge's skill list after Group HR joined Professional Workplace Skills (a Raychem name that two Raychem
    documents explain) into another entry: the old entry is gone and its name is an alias of the kept one."""
    skills, _ = _skillforge_packs()
    old = next(e for e in skills["entities"] if e["id"] == "skill:professional-workplace-skills")
    skills["entities"].remove(old)
    kept = {"id": "skill:professional-workplace", "type": "Skill", "label": "Professional Workplace",
            "aliases": [old["label"]], "domain": "talent"}
    if replaces:
        kept["replaces"] = [old["id"]]
    skills["entities"].append(kept)
    return skills


def test_a_join_loads_when_the_kept_skill_lists_the_id_it_replaces(client):
    skills = _joined_skills_pack(replaces=True)
    body = client.call("import", {"packs": [skills]}, purpose="career_mobility", caller=SERVICE)
    assert body["status"] == "ok", body
    assert body["data"]["packs"][0]["result"] == "loaded"
    g = client.rt.mesh.graph
    assert "skill:professional-workplace-skills" not in g and g.graph["replaced_by"] == {"skill:professional-workplace-skills": "skill:professional-workplace"}
    assert "Professional Workplace Skills" in g.nodes["skill:professional-workplace"]["aliases"]
    # every link to the old id now reaches the kept skill, and a lookup by the old id finds the kept skill
    assert not [e for e in g.edges(keys=True) if "skill:professional-workplace-skills" in e[:2]]
    found = client.call("find_mentors", {"skill": "skill:professional-workplace-skills"})
    assert found["status"] in ("ok", "no_evidence") and found["data"]["skill"] == "skill:professional-workplace"


def test_a_group_pack_that_drops_a_referenced_skill_is_refused_with_the_reason_and_the_rest_loads(client):
    first, talent = _skillforge_packs()
    assert client.call("import", {"packs": [first, talent]}, purpose="career_mobility", caller=SERVICE)["status"] == "ok"
    kept_before = (context_api.TALENT_IMPORT / "group.skills.pack.json").read_bytes()
    skills = _joined_skills_pack(replaces=False)
    talent["entities"][0]["label"] += " renamed"
    body = client.call("import", {"packs": [skills, talent]}, purpose="career_mobility", caller=SERVICE)
    results = {r["pack_id"]: r for r in body["data"]["packs"]}
    assert body["status"] == "partial"
    refused = results["group.skillforge-skills"]
    assert refused["result"] == "refused" and refused["code"] == "pack_refused"
    assert refused["reason"].startswith("skill:professional-workplace-skills is used in raychem.lessons and raychem.operations, but no pack defines it.")
    assert "replaces" in refused["reason"] and "Send it again" not in refused["reason"]
    assert results["ceat.talent"]["result"] == "loaded"  # checked again without the refused pack, and it passes
    assert (context_api.TALENT_IMPORT / "group.skills.pack.json").read_bytes() == kept_before
    # the Applications page shows the latest send with the refusal
    page = client.http.get("/api/v1/mesh/applications", headers=_presenter())
    card = next(a for a in page.json()["applications"] if a["id"] == "skillforge")
    assert (card["imports"]["last_send"]["loaded"], card["imports"]["last_send"]["refused"]) == (1, 1)
    assert [r["pack_id"] for r in card["imports"]["refused"]] == ["group.skillforge-skills"]
    assert "packs_received" not in card["facts"]
    # A call with a pack id the registry does not allow (a test of the refusal) leaves the record of the real packs
    client.call("import", {"packs": [{"pack": {"pack_id": "live-check.not-a-pack"}}]}, purpose="career_mobility", caller=SERVICE)
    again = next(a for a in client.http.get("/api/v1/mesh/applications", headers=_presenter()).json()["applications"] if a["id"] == "skillforge")
    assert again["imports"] == card["imports"]
    # The refused pack sent again and loaded: no refusal is left
    fixed = _joined_skills_pack(replaces=True)
    assert client.call("import", {"packs": [fixed]}, purpose="career_mobility", caller=SERVICE)["status"] == "ok"
    after = next(a for a in client.http.get("/api/v1/mesh/applications", headers=_presenter()).json()["applications"] if a["id"] == "skillforge")
    assert after["imports"]["refused"] == [] and after["imports"]["last_send"]["loaded"] == 1


def test_two_imports_at_the_same_time_run_one_after_the_other(client):
    import asyncio

    from services.context_catalogue import CallContext, ImportIn, h_import
    from services.applications import applications

    skills, talent = _skillforge_packs()
    other = copy.deepcopy(talent)
    other["entities"][0]["label"] += " second"
    ctx = CallContext(rt=client.rt, app=applications()["skillforge"], purpose="career_mobility", user=None, trace_id="t")

    async def both():
        return await asyncio.gather(h_import(ctx, ImportIn(packs=[skills, talent])), h_import(ctx, ImportIn(packs=[other])))
    first, second = asyncio.run(both())
    assert first.status == "ok" and second.status == "ok"
    log = json.loads((context_api.TALENT_IMPORT / "import_log.json").read_text())
    assert set(log) == {"group.skills", "ceat.talent"}
    kept = json.loads((context_api.TALENT_IMPORT / "ceat.talent.pack.json").read_text())
    assert kept["entities"][0]["label"].endswith(" second")
