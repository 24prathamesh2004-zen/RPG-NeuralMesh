"""The published context contract (plan 2.7 and 2.8): the bundle and its lock, the refusals that say what is needed,
suggestions that never name a document, the registry rules, the MCP gateway on the same dispatcher, and the two steps
that carry an import to the nodes (the talent pack rebuild and the node's reload of changed pack files)."""
from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator

from api.auth import issue_poc_token
from api.main import app
from api.routers import context as context_router
from api.routers import mesh as mesh_router
from services import applications, context_api, mesh_query
from services.context_catalogue import CATALOGUE, bundle
from tests.mesh_harness import build_mesh
from shared.registry import node_ids

APP = Path(__file__).resolve().parents[1]
SCHEMAS = APP / "contracts" / "schemas"
PERSON = {"subsidiary": "ceat", "roles": ["user"], "user_ref": "skillforge:7"}
SERVICE = {"subsidiary": "group", "roles": ["service"]}


@pytest.fixture
def mesh(monkeypatch, tmp_path):
    orchestrator, transport, mesh = build_mesh()
    rt = SimpleNamespace(mesh=mesh, store=mesh.store, orchestrator=orchestrator, export_status={}, group_packs=[])
    monkeypatch.setattr(context_router, "runtime", lambda: rt)
    monkeypatch.setattr(mesh_router, "runtime", lambda: rt)
    monkeypatch.setattr(context_api, "TALENT_IMPORT", tmp_path / "talent_import")
    token = issue_poc_token({"sub": "svc:skillforge", "company": "group", "roles": ["context_client", "talent_exporter"]})
    http = TestClient(app)
    headers = {"Authorization": f"Bearer {token}"}

    def post(tool, body):
        return http.post(f"/api/v1/context/{tool}", json=body, headers=headers)

    def call(tool, inp=None, purpose="learning", caller=None, version="1.0"):
        return post(tool, {"schema_version": version, "tool": tool, "purpose": purpose, "caller": caller or PERSON, "input": inp or {}})

    return SimpleNamespace(rt=rt, http=http, headers=headers, post=post, call=call)


# ── the bundle ──────────────────────────────────────────────────────────────
def test_the_published_bundle_equals_the_code_and_the_lock_moves_only_with_the_version():
    current = bundle()
    on_disk = json.loads((SCHEMAS / "context_contract.json").read_text())
    lock = json.loads((SCHEMAS / "context_contract.lock.json").read_text())
    if current["sha256"] != lock["sha256"] and current["version"] == lock["version"]:
        pytest.fail("The contract changed but its version did not. Raise the version in contracts/context.py, then run "
                    "python -m scripts.write_context_contract")
    assert on_disk == current, "Run python -m scripts.write_context_contract to publish the changed contract"
    assert lock == {"version": current["version"], "sha256": current["sha256"]}


def test_every_registered_tool_is_in_the_catalogue_with_an_input_and_a_data_schema():
    for app_ in applications.applications().values():
        assert set(app_.tools) <= set(CATALOGUE), app_.id
        assert set(app_.purposes) and set(app_.companies)
    for name, described in bundle()["tools"].items():
        assert described["input"]["type"] == "object" and described["data"]["type"] == "object", name


def test_the_route_serves_the_bundle_with_its_hash(mesh):
    served = mesh.http.get("/api/v1/context/contract", headers=mesh.headers).json()
    from contracts.context import CONTRACT_VERSION
    assert served["sha256"] == bundle()["sha256"] and served["version"] == CONTRACT_VERSION


# ── identity and envelope faults: HTTP errors with a problem body ─────────────
@pytest.mark.parametrize("body, status, code", [
    (["not", "an", "object"], 400, "not_an_envelope"),
    ({"tool": "entity"}, 400, "not_an_envelope"),
    ({"schema_version": "2.0", "tool": "entity", "purpose": "learning", "caller": PERSON, "input": {}}, 400, "unsupported_version"),
    ({"schema_version": "1.0", "tool": "related", "purpose": "learning", "caller": PERSON, "input": {}}, 400, "tool_mismatch"),
])
def test_an_unreadable_envelope_is_an_http_error_that_names_the_fault(mesh, body, status, code):
    response = mesh.post("entity", body)
    assert response.status_code == status and response.json()["code"] == code
    assert response.json()["type"] == f"urn:rpg-neuralmesh:problem:{code}" and response.json()["status"] == status


def test_identity_faults_answer_with_a_problem_body(mesh):
    missing = mesh.http.post("/api/v1/context/entity", json={})
    assert missing.status_code == 401 and missing.json()["code"] == "unauthenticated"
    assert missing.headers["content-type"].startswith("application/problem+json")
    expired = issue_poc_token({"sub": "svc:skillforge", "company": "group", "roles": ["context_client"]}, hours=-1)
    assert mesh.http.post("/api/v1/context/entity", json={}, headers={"Authorization": f"Bearer {expired}"}).json()["code"] == "unauthenticated"
    person = issue_poc_token({"sub": "u", "company": "ceat", "roles": ["group_user"]})
    denied = mesh.http.post("/api/v1/context/entity", json={}, headers={"Authorization": f"Bearer {person}"})
    assert denied.status_code == 403 and denied.json()["code"] == "not_allowed"


def test_a_body_over_the_limit_is_refused_before_it_is_read_whole(mesh):
    from api.routers.context import BODY_BYTES
    big = b'{"x": "' + b"a" * (BODY_BYTES + 10) + b'"}'
    response = mesh.http.post("/api/v1/context/entity", content=big, headers={**mesh.headers, "content-type": "application/json"})
    assert response.status_code == 400 and response.json()["code"] == "not_an_envelope"


def test_an_internal_error_of_a_tool_is_a_503_that_shows_nothing_internal(mesh, monkeypatch):
    from services import context_catalogue

    def broken(*args, **kwargs):
        raise ValueError("secret internal path /var/data/x.json is corrupt")
    monkeypatch.setattr(context_catalogue.context_tools, "entity", broken)
    response = mesh.call("entity", {"id": "skill:hr"})
    assert response.status_code == 503 and response.json()["code"] == "service_unavailable"
    assert "secret" not in response.text


def test_the_contract_script_refuses_a_change_without_a_new_version():
    from scripts.write_context_contract import guard

    current = bundle()
    assert guard(current, {"version": current["version"], "sha256": current["sha256"]}) is None
    assert "Raise CONTRACT_VERSION" in guard(current, {"version": current["version"], "sha256": "0" * 64})
    assert guard(current, {"version": "1.0", "sha256": "0" * 64}) is None  # a new version may change the content


def test_an_application_reads_only_its_own_kinds_and_documents_its_purpose_allows(mesh):
    snap = issue_poc_token({"sub": "svc:snapscore", "company": "group", "roles": ["context_client"]})
    headers = {"Authorization": f"Bearer {snap}"}

    def as_snapscore(tool, inp, purpose="inspection"):
        return mesh.http.post(f"/api/v1/context/{tool}", headers=headers, json={
            "schema_version": "1.1", "tool": tool, "purpose": purpose, "caller": PERSON, "input": inp}).json()

    role = as_snapscore("entity", {"id": "ceat:role/quality-engineer"})
    assert role["status"] == "refused" and role["problem"]["code"] == "not_found"
    assert all(mesh.rt.mesh.graph.nodes[s["id"]]["type"] not in ("Role", "Skill") for s in role["problem"]["suggestions"])
    g = mesh.rt.mesh.graph
    hidden = next(n for n, d in g.nodes(data=True) if d.get("type") == "Document" and not d.get("retired")
                  and "inspection" not in (g.nodes.get(d.get("datapoint"), {}).get("purposes_allowed") or []))
    assert as_snapscore("entity", {"id": hidden})["problem"]["code"] == "not_found"
    shown = mesh.call("entity", {"id": hidden}, purpose="problem_solving").json()
    allows = "problem_solving" in (g.nodes.get(g.nodes[hidden].get("datapoint"), {}).get("purposes_allowed") or [])
    assert (shown["status"] == "ok") == allows
    org = as_snapscore("related", {"id": "org:ceat"})
    listed = [x["id"] for items in org["data"]["related"].values() for x in items]
    assert listed and not any(g.nodes[x]["type"] in ("Role", "Skill") for x in listed)


def test_a_never_leave_document_is_read_only_by_a_person_of_its_company(mesh):
    secret = {"id": "ceat:E-01-01"}  # Compound formulation record A, in CEAT's never-leave datapoint
    own = mesh.call("entity", secret, purpose="problem_solving", caller={**PERSON, "subsidiary": "ceat"}).json()
    assert own["status"] == "ok" and own["data"]["id"] == "ceat:E-01-01"
    for caller in ({**PERSON, "subsidiary": "kec"}, SERVICE):
        other = mesh.call("entity", secret, purpose="problem_solving", caller=caller).json()
        assert other["status"] == "refused" and other["problem"]["code"] == "not_found"
    related = mesh.call("related", {"id": "ceat:E-01"}, purpose="problem_solving", caller={**PERSON, "subsidiary": "kec"}).json()
    assert related["status"] == "refused"


def test_the_registry_decides_tools_purposes_and_companies(mesh):
    unknown = mesh.call("teleport")
    assert unknown.status_code == 404 and "role_context" in unknown.json()["allowed"]["tools"]
    not_listed = mesh.call("live", {"id": "ceat:asset/x"}, purpose="learning")
    assert not_listed.status_code == 403 and "live" not in not_listed.json()["allowed"]["tools"]
    purpose = mesh.call("entity", {"id": "skill:hr"}, purpose="inspection")
    assert purpose.status_code == 403 and purpose.json()["allowed"]["purposes"] == ["learning", "career_mobility", "problem_solving"]
    company = mesh.call("entity", {"id": "skill:hr"}, caller={**PERSON, "subsidiary": "acme"})
    assert company.status_code == 403 and "zensar" in company.json()["allowed"]["companies"]


def test_mesh_admin_is_never_granted_through_a_request():
    skillforge = applications.applications()["skillforge"]
    assert skillforge.mesh_roles(["mesh_admin"]) == ("group_user",)
    assert skillforge.mesh_roles(["admin", "lead", "nobody"]) == ("group_user",)


# ── value faults: an answer with a status and what is needed ──────────────────
def test_a_wrong_input_field_names_the_field_and_the_allowed_values(mesh):
    body = mesh.call("learning_sources", {"skill": "skill:hr", "level": "X"}).json()
    assert body["status"] == "refused" and body["problem"]["code"] == "invalid_input"
    level = next(f for f in body["problem"]["fields"] if f["field"] == "input.level")
    assert level["allowed"] == ["L", "M", "A"]
    extra = mesh.call("entity", {"id": "skill:hr", "colour": "red"}).json()
    assert extra["problem"]["fields"][0]["field"] == "input.colour"
    purpose = mesh.call("learning_sources", {"skill": "skill:hr", "level": "M"}, purpose="career_mobility").json()
    assert purpose["problem"]["fields"][0] == {"field": "purpose", "problem": "not served by this tool", "allowed": ["learning"]}
    service_only = mesh.call("vocabulary_export", purpose="career_mobility").json()
    assert service_only["problem"]["fields"][0]["allowed"] == ["group"]
    person_only = mesh.call("skill_context", {"skill": "skill:hr"}, caller=SERVICE).json()
    assert person_only["problem"]["fields"][0]["field"] == "caller.subsidiary"


def test_an_unknown_role_answers_with_the_closest_roles_and_never_a_document(mesh):
    typo = mesh.call("role_context", {"role": "ceat:role/quality-enginer"}).json()
    assert typo["status"] == "refused" and typo["problem"]["code"] == "not_found"
    assert typo["problem"]["suggestions"][0]["id"] == "ceat:role/quality-engineer" and typo["problem"]["loaded"] is True
    other = mesh.call("role_context", {"role": "zensar:role/data-engineer"}).json()
    assert other["problem"]["loaded"] is False and "no role of zensar" in other["problem"]["detail"]
    for s in typo["problem"]["suggestions"] + other["problem"]["suggestions"]:
        node = mesh.rt.mesh.graph.nodes[s["id"]]
        assert node["type"] == "Role" and s["score"] >= 0.5
    anything = mesh.call("entity", {"id": "ceat:E-03-0"}).json()
    assert all(mesh.rt.mesh.graph.nodes[s["id"]]["type"] not in ("Document", "Datapoint", "Expert") for s in anything["problem"]["suggestions"])


def test_a_person_of_a_company_without_a_node_is_told_so(mesh):
    ventures = {**PERSON, "subsidiary": "ventures"}
    body = mesh.call("ask", {"question": "How is cable jointing checked?"}, purpose="problem_solving", caller=ventures).json()
    assert body["status"] == "refused" and body["problem"]["code"] == "company_not_connected"
    assert {c["id"] for c in body["problem"]["choices"]} == set(node_ids())
    assert mesh.call("role_context", {"role": "ceat:role/quality-engineer"}, caller=ventures).json()["status"] == "ok"


def test_a_question_that_matches_no_company_asks_for_a_choice(mesh, monkeypatch):
    async def no_route(graph, **kwargs):
        return {"status": "needs_node_choice", "question": kwargs["question"], "answer": None, "answer_status": "evidence_only",
                "evidence": [], "also_found": [], "withheld": [], "routing": {}, "node_results": []}
    monkeypatch.setattr(mesh_query, "run_query", no_route)
    body = mesh.call("ask", {"question": "What should I do next?"}, purpose="problem_solving").json()
    assert body["status"] == "needs_input" and body["problem"]["code"] == "needs_choice"
    assert {c["id"] for c in body["problem"]["choices"]} == set(node_ids())


def test_every_answer_validates_against_the_published_schemas(mesh):
    published = bundle()
    answer_schema = Draft202012Validator(published["answer"])
    calls = [("role_context", {"role": "ceat:role/quality-engineer"}, "learning", PERSON),
             ("skill_context", {"skill": "skill:quality-management"}, "learning", PERSON),
             ("learning_sources", {"skill": "skill:quality-management", "level": "M"}, "learning", PERSON),
             ("find_mentors", {"skill": "skill:quality-management"}, "learning", PERSON),
             ("vocabulary_export", {}, "career_mobility", SERVICE),
             ("entity", {"id": "skill:hr"}, "learning", PERSON),
             ("related", {"id": "ceat:role/quality-engineer", "depth": 2}, "learning", PERSON),
             ("similar", {"id": "skill:hr"}, "learning", PERSON),
             ("ask", {"question": "How does CEAT check incoming material quality?"}, "problem_solving", PERSON),
             ("role_context", {"role": "nobody:role/none"}, "learning", PERSON)]
    for tool, inp, purpose, caller in calls:
        body = mesh.call(tool, inp, purpose=purpose, caller=caller).json()
        errors = [e.message for e in answer_schema.iter_errors(body)]
        assert not errors, (tool, errors[:3])
        if body["status"] in ("ok", "partial", "no_evidence", "blocked"):
            data_errors = [e.message for e in Draft202012Validator(published["tools"][tool]["data"]).iter_errors(body["data"])]
            assert not data_errors, (tool, data_errors[:3])


# ── the MCP gateway answers through the same dispatcher ─────────────────────
def test_the_gateway_lists_the_catalogue_and_gives_the_same_answers(mesh, monkeypatch):
    from mcp_gateway import server as gateway

    monkeypatch.setattr(gateway, "runtime", lambda: mesh.rt)
    monkeypatch.setattr(gateway, "_claims", lambda: {"sub": "svc:skillforge", "roles": ["context_client"]})
    server = gateway.create_gateway(port=18100)
    tools = {t.name: t for t in asyncio.run(server.list_tools())}
    assert set(tools) == set(CATALOGUE) - {"import"}
    assert set(tools["role_context"].inputSchema["properties"]) == {"purpose", "caller", "input", "schema_version"}

    def run(name, args):
        return asyncio.run(server.call_tool(name, args))

    rest = mesh.call("role_context", {"role": "ceat:role/quality-engineer"}).json()
    content = run("role_context", {"purpose": "learning", "caller": PERSON, "input": {"role": "ceat:role/quality-engineer"}})
    structured = content[1] if isinstance(content, tuple) else json.loads(content[0].text)
    assert structured["data"] == rest["data"] and structured["status"] == "ok"
    refused = run("role_context", {"purpose": "learning", "caller": PERSON, "input": {"role": "ceat:role/quality-enginer"}})
    refused = refused[1] if isinstance(refused, tuple) else json.loads(refused[0].text)
    assert refused["status"] == "refused" and refused["problem"]["suggestions"]
    denied = run("role_context", {"purpose": "inspection", "caller": PERSON, "input": {"role": "ceat:role/quality-engineer"}})
    assert denied.isError and json.loads(denied.content[0].text)["code"] == "not_allowed"


def test_the_gateway_checks_arguments_by_the_contract_and_lists_the_contract_schema(mesh, monkeypatch):
    """The MCP library does not check the arguments: a wrong field is the contract's refusal, a broken envelope the
    contract's Problem as JSON with no prefix, and the tool list still shows the contract's input schema."""
    from mcp_gateway import server as gateway

    real_claims = gateway._claims
    monkeypatch.setattr(gateway, "runtime", lambda: mesh.rt)
    monkeypatch.setattr(gateway, "_claims", lambda: {"sub": "svc:skillforge", "roles": ["context_client"]})
    server = gateway.create_gateway(port=18101)
    tool = next(t for t in asyncio.run(server.list_tools()) if t.name == "learning_sources")
    assert tool.inputSchema["required"] == ["purpose", "caller", "input"]
    assert tool.inputSchema["properties"]["input"] == {"$ref": "#/$defs/LearningIn"}

    def run(args):
        return asyncio.run(server.call_tool("learning_sources", args))

    wrong = run({"purpose": "learning", "caller": PERSON, "input": {"skill": "skill:hr", "level": "X"}})
    body = wrong[1] if isinstance(wrong, tuple) else json.loads(wrong[0].text)
    assert body["status"] == "refused" and body["problem"]["code"] == "invalid_input"
    assert next(f for f in body["problem"]["fields"] if f["field"] == "input.level")["allowed"] == ["L", "M", "A"]
    for args, code in (({"purpose": "learning", "input": {"skill": "skill:hr"}}, "not_an_envelope"),
                       ({"purpose": "learning", "caller": "ceat", "input": {"skill": "skill:hr"}}, "not_an_envelope"),
                       ({"purpose": "learning", "caller": PERSON, "input": {"skill": "skill:hr"}, "schema_version": "2.0"}, "unsupported_version")):
        fault = run(args)
        assert fault.isError, args
        assert json.loads(fault.content[0].text)["code"] == code  # the text is the Problem and nothing else
    # a call without a service identity: the gateway's own claims check
    monkeypatch.setattr(gateway, "_claims", real_claims)
    monkeypatch.setattr(gateway, "get_access_token", lambda: None)
    denied = run({"purpose": "learning", "caller": PERSON, "input": {"skill": "skill:hr"}})
    assert denied.isError and json.loads(denied.content[0].text)["code"] == "not_allowed"


# ── the two steps that carry an import to the nodes ─────────────────────────
def test_the_talent_pack_rebuild_writes_only_the_talent_packs_of_the_named_nodes(tmp_path, monkeypatch):
    from knowledge import packgen

    import os

    kb_pack = tmp_path / "kb_pack"
    sources = {"kb": APP / "neuralmesh_kb_pack" / "kb", "group": APP / "neuralmesh_kb_pack" / "group",
               "data_pack": Path(os.environ["NEURALMESH_DATA_PACK"]), "talent_import": Path(os.environ["NEURALMESH_TALENT_IMPORT"])}
    for part, source in sources.items():
        shutil.copytree(source, kb_pack / part, ignore=shutil.ignore_patterns("build", "chroma"))
    monkeypatch.setattr(packgen, "KB", kb_pack / "kb")
    monkeypatch.setattr(packgen, "DATA", kb_pack / "data_pack")
    monkeypatch.setattr(packgen, "GROUP", kb_pack / "group")
    talent = json.loads((kb_pack / "talent_import" / "ceat.talent.pack.json").read_text())
    talent["pack"].update({"pack_id": "zensar.talent", "subsidiary": "zensar", "title": "Zensar roles"})
    talent["datapoints"] = [{**d, "id": "zensar:T-01"} for d in talent.get("datapoints", [])]
    talent["documents"] = [{**d, "id": d["id"].replace("ceat:", "zensar:"), "datapoint": "zensar:T-01"} for d in talent.get("documents", [])]
    talent["entities"] = [{**e, "id": e["id"].replace("ceat:", "zensar:"), "subsidiary": "zensar"} for e in talent["entities"]]
    talent["relationships"] = [{**r, "id": r["id"].replace("ceat.", "zensar."), "from": r["from"].replace("ceat:", "zensar:")}
                               for r in talent["relationships"]]
    (kb_pack / "talent_import" / "zensar.talent.pack.json").write_text(json.dumps(talent))
    before = {p: p.read_bytes() for p in (kb_pack / "data_pack").glob("*/packs/*/pack.json")}
    real_before = (Path(os.environ["NEURALMESH_DATA_PACK"]) / "zensar" / "packs" / "talent" / "pack.json").read_bytes()

    assert packgen.rebuild_talent_packs(["zensar"], kb_pack / "talent_import") == ["zensar.talent"]
    changed = [p for p in before if p.read_bytes() != before[p]]
    assert [str(p.relative_to(kb_pack / "data_pack")) for p in changed] == ["zensar/packs/talent/pack.json"]
    rebuilt = json.loads(changed[0].read_text())
    assert {e["id"] for e in rebuilt["entities"] if e["type"] == "Role"} == {e["id"] for e in talent["entities"]}
    assert (Path(os.environ["NEURALMESH_DATA_PACK"]) / "zensar" / "packs" / "talent" / "pack.json").read_bytes() == real_before


def test_a_node_reads_its_pack_files_again_when_they_change(tmp_path):
    from mcp_nodes.access_store import AccessStore
    from mcp_nodes.server import LiveNode, load_node_config

    import os

    root = tmp_path / "data_pack"
    shutil.copytree(Path(os.environ["NEURALMESH_DATA_PACK"]) / "kec", root / "kec", ignore=shutil.ignore_patterns("build", "chroma"))
    config = load_node_config("kec", root)
    live = LiveNode(config, AccessStore(tmp_path / "g.db", tmp_path / "a.jsonl", config), reload=True, data_root=root)
    pack_path = root / "kec" / "packs" / "talent" / "pack.json"
    pack = json.loads(pack_path.read_text())
    before = len([e for p in live.config.knowledge.packs for e in p.get("entities", [])])
    pack.setdefault("entities", []).append({"id": "kec:role/site-engineer", "type": "Role", "label": "Site Engineer", "subsidiary": "kec"})
    pack_path.write_text(json.dumps(pack))
    after = len([e for p in live.config.knowledge.packs for e in p.get("entities", [])])
    assert after == before + 1
    pack_path.write_text("{ not json")
    assert len([e for p in live.config.knowledge.packs for e in p.get("entities", [])]) == after  # a broken file keeps the packs of before


def test_asking_a_group_company_without_a_node_says_which_company_is_not_connected(mesh):
    body = mesh.call("ask", {"question": "How are cable joints tested?", "nodes": ["ventures"]}, purpose="problem_solving").json()
    assert body["status"] == "refused" and body["problem"]["code"] == "company_not_connected"
    assert body["problem"]["fields"][0]["field"] == "input.nodes" and "ventures" in body["problem"]["fields"][0]["problem"]
    caller = mesh.call("ask", {"question": "How are cable joints tested?"}, purpose="problem_solving",
                       caller={**PERSON, "subsidiary": "ventures"}).json()
    assert caller["problem"]["fields"][0]["field"] == "caller.subsidiary"
