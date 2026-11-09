"""Knowledge mesh v2: registry, packs, hybrid search, evidence records, graph routing, context layer, model policy."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
import yaml

from api.auth import issue_poc_token
from contracts.evidence import EvidenceRecord
from knowledge import embedder
from knowledge.validator import validate_packs
from mcp_nodes.auth import CallerContext
from mcp_nodes.server import NODE_IDS, export_graph_node, load_node_config, search_node
from services.context import policy as model_policy
from services.context.builder import build
from services.context.cache import ANSWER_CACHE, RERANK_CACHE
from services.context.check import run_checks
from services.neuralmesh import build_mesh_graph
from shared.registry import node_ids
from tests.mesh_harness import FakeBackend, build_mesh

APP = Path(__file__).resolve().parents[1]
GOLDEN = yaml.safe_load((APP / "neuralmesh_kb_pack" / "kb" / "golden.yaml").read_text())["scenarios"]
CANARIES = [c for n in NODE_IDS for c in yaml.safe_load((APP / "neuralmesh_kb_pack" / "kb" / f"{n}.yaml").read_text())["canaries"]]
needs_model = pytest.mark.skipif(not embedder.available(), reason="embedding model not installed")


def user_token(company: str = "ceat", roles=("group_user",)) -> str:
    return issue_poc_token({"sub": "user-1", "company": company, "roles": list(roles)})


@pytest.fixture
def local_policy(tmp_path, monkeypatch):
    """A policy whose steps use a model inside the group network, so a stand-in model may answer any bundle."""
    data = json.loads((APP / "config" / "model_policy.json").read_text())
    for step in data["steps"].values():
        step["model"] = "local-ollama"
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("NEURALMESH_MODEL_POLICY", str(path))
    model_policy._load.cache_clear()
    ANSWER_CACHE.clear()
    RERANK_CACHE.clear()
    yield
    model_policy._load.cache_clear()
    ANSWER_CACHE.clear()
    RERANK_CACHE.clear()


def run(orchestrator, question, nodes=None, purpose="problem_solving", company="ceat", roles=("group_user",)):
    graph = build_mesh_graph(orchestrator)
    return asyncio.run(graph.ainvoke({
        "question": question, "nodes": nodes, "purpose": purpose, "user_assertion": user_token(company, roles),
        "company": company, "roles": list(roles), "trace_id": "test",
    }))


# ── phase 0: registry ───────────────────────────────────────────────────────
def test_registry_is_the_single_node_list():
    assert node_ids() == ("ceat", "kec", "zensar", "harrisons", "raychem", "rpgls", "asvata")
    assert NODE_IDS == node_ids()


def test_query_schema_accepts_no_node_choice_and_rejects_unknown_nodes():
    from pydantic import ValidationError

    from api.schemas.mesh import MeshQueryRequest

    assert MeshQueryRequest(question="Which delays repeat?", purpose="problem_solving").nodes is None
    with pytest.raises(ValidationError):
        MeshQueryRequest(question="Which delays repeat?", nodes=["ventures"], purpose="problem_solving")


# ── phase 1: packs, hybrid search, evidence records ─────────────────────────
def test_built_packs_validate_together_with_the_group_packs():
    packs = [(p.name, json.loads(p.read_text())) for p in (APP / "neuralmesh_kb_pack" / "data_pack").glob("*/packs/*/pack.json")]
    packs += [(p.name, json.loads(p.read_text())) for p in (APP / "neuralmesh_kb_pack" / "group").glob("*.pack.json")]
    packs += [(p.name, json.loads(p.read_text())) for p in (APP / "neuralmesh_kb_pack" / "talent_import").glob("group.*.pack.json")]
    report = validate_packs(packs, strict=True)
    assert report.errors == []
    subsidiary = [p for p in packs if p[1]["pack"]["scope"] == "subsidiary"]
    assert len(subsidiary) == 35 and {p[1]["pack"]["subsidiary"] for p in subsidiary} == set(node_ids())


@needs_model
def test_no_canary_in_any_vector_store():
    from knowledge.vector_index import VectorIndex

    builds = list((APP / "neuralmesh_kb_pack" / "data_pack").glob("*/packs/*/build"))
    packs = list((APP / "neuralmesh_kb_pack" / "data_pack").glob("*/packs/*/pack.json"))
    assert len(builds) == len(packs) and all(VectorIndex(b).exists() for b in builds)
    for build in builds:
        text = VectorIndex(build).all_text()
        assert not [c for c in CANARIES if c in text], build


def test_every_search_item_is_a_valid_evidence_record():
    caller = CallerContext("u", "ceat", frozenset({"group_user"}), "problem_solving")
    response = search_node(load_node_config("ceat"), caller, "natural rubber storage lot acceptance compound formulation",
                           "problem_solving")
    items = response["results"] + response["withheld"]
    assert items
    for item in items:
        record = EvidenceRecord.model_validate({k: v for k, v in item.items() if k in EvidenceRecord.model_fields})
        assert record.schema_version == "1.0" and record.node == "ceat"
    assert all(i["kind"] == "metadata" and "text" not in i for i in response["withheld"])
    stale = [i for i in response["results"] if i["document"] == "ceat:E-03-06"]
    assert all(i["superseded_by"] == "ceat:E-03-02" for i in stale)


@needs_model
def test_vector_search_adds_a_document_the_keywords_miss():
    from mcp_nodes import knowledge_view

    caller = CallerContext("u", "harrisons", frozenset({"group_user"}), "problem_solving")
    config = load_node_config("harrisons")
    question = "milk from the trees thickening early during the rainy months"
    keyword_only = set(knowledge_view._fts_keys(config.index_path, question))
    by_meaning = {key for key, _ in knowledge_view._vector_keys(config.knowledge, question, None)}
    assert by_meaning - keyword_only, "the vector list should add a document the keyword list does not hold"
    assert any(key.startswith("harrisons:O-05") for key in by_meaning)
    response = search_node(config, caller, question, "problem_solving")
    assert response["search"]["vector_hits"] > 0
    assert any(i["datapoint_id"] in ("O-05", "F-01") for i in response["results"])


def test_purpose_is_decided_per_datapoint():
    config = load_node_config("ceat")
    learner = CallerContext("u", "harrisons", frozenset({"group_user"}), "learning")
    response = search_node(config, learner, "material handling failure RCA lot acceptance", "learning")
    assert any(i["datapoint_id"] == "E-03" for i in response["results"])
    assert all(i["datapoint_id"] != "E-02" for i in response["results"])
    assert any(i["datapoint_id"] == "E-02" and i["rule_id"] == "R-PURPOSE-01" for i in response["withheld"])


def test_export_graph_is_metadata_only_and_for_the_mesh_service_only():
    config = load_node_config("ceat")
    user = CallerContext("u", "ceat", frozenset({"group_user"}), "problem_solving")
    assert export_graph_node(config, user)["decision"] == "BLOCKED_BY_POLICY"
    export = export_graph_node(config, CallerContext("svc", "group", frozenset({"mesh_service"}), "problem_solving"))
    text = json.dumps(export)
    assert export["decision"] == "ALLOWED"
    assert '"summary"' not in text and "body" not in text and "private" not in text
    assert not [c for c in CANARIES if c in text]
    assert "CE-5" not in text  # opted-out expert
    assert "Rohan" not in text  # names stay at the node


# ── phase 2: graph, routing, links ──────────────────────────────────────────
def test_graph_load_is_idempotent_and_routes_all_golden_scenarios():
    _, transport, mesh = build_mesh()
    before = mesh.store.counts()
    service = CallerContext("svc", "group", frozenset({"mesh_service"}), "problem_solving")
    mesh.load_node_export(export_graph_node(transport.configs["ceat"], service))
    assert mesh.store.counts() == before
    for scenario in GOLDEN:
        question = scenario["question"] if scenario["id"] != "S7" else GOLDEN[1]["question"]
        resolved = mesh.resolve(question)
        route = mesh.route(set(resolved["concepts"]), set(resolved["named_subsidiaries"]))
        expected = set(scenario["nodes"]) if scenario["id"] != "S4" else set()
        if scenario["id"] == "S4":
            assert route["experts"] and not any(e.endswith(("CE-5", "KE-5", "ZE-4", "HE-4")) for e in route["experts"])
        else:
            assert expected <= route["subsidiaries"], scenario["id"]


def test_cross_subsidiary_link_counts_only_after_both_owners_approve():
    _, _, mesh = build_mesh()
    link = next(l for l in mesh.links() if l["status"] == "proposed")
    a, b = link["sides"]
    mesh.store.review_link(link["id"], a, "Owner", "approve", "tester")
    mesh.rebuild()
    assert next(l for l in mesh.links() if l["id"] == link["id"])["status"] == "proposed"
    mesh.store.review_link(link["id"], b, "Owner", "approve", "tester")
    mesh.rebuild()
    assert next(l for l in mesh.links() if l["id"] == link["id"])["status"] == "approved"


def test_blocked_caller_sees_no_relationship_into_the_blocking_node():
    _, _, mesh = build_mesh()
    links = mesh.expand({"ceat:E-03-01", "ceat:E-03-05", "kec:E-05-01"}, {"harrisons"})
    assert any(l["type"] == "ADDRESSES_GAP" for l in links["hidden"])
    assert all("harrisons" not in l["source"] + l["target"] for l in links["used"])


# ── phase 3: the full flow and the context layer ────────────────────────────
def test_flagship_question_routes_without_a_node_choice_and_shows_links(local_policy):
    orchestrator, transport, _ = build_mesh(backend=FakeBackend())
    result = run(orchestrator, GOLDEN[0]["question"])
    assert result["routing"]["method"] == "graph"
    assert {"ceat", "harrisons"} <= set(result["routing"]["subsidiaries"])
    assert any(w["datapoint_id"] == "E-01" for w in result["withheld"])
    assert any(l["type"] == "ADDRESSES_GAP" for l in result["relationships"]["used"])
    assert result["answer"]["status"] == "answered"
    assert "CANARY" not in json.dumps(result)


def test_blocked_scenarios_stay_blocked():
    orchestrator, _, _ = build_mesh()
    s5 = run(orchestrator, GOLDEN[4]["question"])
    assert any(w["datapoint_id"] == "E-01" and w["rule_id"] == "R-NL-01" for w in s5["withheld"])
    assert not any(r.get("datapoint") == "ceat:E-01" for r in s5.get("records", []))
    s6 = run(orchestrator, GOLDEN[5]["question"])
    assert not any(r.get("datapoint") == "ceat:F-06" for r in s6.get("records", []))


def test_stopped_node_gives_a_partial_answer():
    orchestrator, _, _ = build_mesh(down={"kec"})
    result = run(orchestrator, GOLDEN[1]["question"])
    assert result["status"] == "partial"
    assert {n["node_id"]: n["status"] for n in result["node_results"]}["kec"] == "NODE_UNAVAILABLE"
    assert any(r["node"] == "zensar" for r in result["records"])


def test_planted_instruction_never_reaches_the_prompt(local_policy):
    backend = FakeBackend()
    orchestrator, _, _ = build_mesh(backend=backend)
    run(orchestrator, GOLDEN[7]["question"])
    prompts = [user for step, user in backend.calls if step == "answer"]
    assert prompts and all("IGNORE PREVIOUS INSTRUCTIONS" not in p for p in prompts)


def test_uncited_or_invented_citation_fails_the_check(local_policy):
    backend = FakeBackend(reply="Spoilage falls when lots are trended. Also see [ceat:X-99-99].")
    orchestrator, _, _ = build_mesh(backend=backend)
    result = run(orchestrator, GOLDEN[0]["question"])
    assert result["answer"]["status"] == "check_failed"
    assert result["answer"]["text"] is None
    assert {f["rule"] for f in result["answer"]["checks"]} == {1}
    # one second try that names the broken rules, then a reason in words, never a count of checks
    answers = [user for step, user in backend.calls if step == "answer"]
    assert len(answers) == 2 and "Your first answer broke these rules" in answers[1] and "ceat:X-99-99" in answers[1]
    reason = result["answer"]["reason"]
    assert reason.startswith("The written answer is not shown, because a sentence cited no record and it cited a record")
    assert "check(s)" not in reason


class _FixesOnTheSecondTry(FakeBackend):
    def complete(self, choice, system, user):
        if choice.step == "answer" and not any(step == "answer" for step, _ in self.calls):
            self.calls.append((choice.step, user))
            return "Spoilage falls when lots are trended.", 100, 20
        return super().complete(choice, system, user)


def test_a_second_try_with_the_rule_named_gives_a_checked_answer(local_policy):
    backend = _FixesOnTheSecondTry()
    orchestrator, _, _ = build_mesh(backend=backend)
    result = run(orchestrator, GOLDEN[0]["question"])
    assert result["answer"]["status"] == "answered" and result["answer"]["checks"] == []
    assert [step for step, _ in backend.calls].count("answer") == 2


class _ClassifiesNothing(FakeBackend):
    def complete(self, choice, system, user):
        if choice.step == "classify":
            self.calls.append((choice.step, user))
            return '{"nodes": [], "reason": "no profile fits"}', 50, 5
        return super().complete(choice, system, user)


def test_a_question_no_company_matches_goes_to_the_askers_own_company(local_policy):
    orchestrator, _, _ = build_mesh(backend=_ClassifiesNothing())
    own = run(orchestrator, "What do we do when a reading is outside its limit?", company="rpgls")
    assert own["routing"]["method"] == "own" and own["routing"]["subsidiaries"] == ["rpgls"]
    group = run(orchestrator, "What do we do when a reading is outside its limit?", company="group", roles=("group_user", "mesh_admin"))
    assert group["routing"]["method"] == "none" and group["status"] == "needs_node_choice"


def test_with_companies_chosen_a_link_to_another_company_is_hidden():
    _, _, mesh = build_mesh()
    docs = {"ceat:E-03-01", "ceat:E-03-05"}
    assert any("harrisons" in l["source"] + l["target"] for l in mesh.expand(docs)["used"])
    chosen = mesh.expand(docs, only={"ceat", "kec"})
    assert all("harrisons" not in l["source"] + l["target"] for l in chosen["used"])
    assert any("harrisons" in l["source"] + l["target"] for l in chosen["hidden"])


def test_identical_queries_make_one_answer_call(local_policy):
    backend = FakeBackend()
    orchestrator, _, _ = build_mesh(backend=backend)
    run(orchestrator, GOLDEN[2]["question"])
    second = run(orchestrator, GOLDEN[2]["question"])
    assert [step for step, _ in backend.calls] == ["rerank", "answer"]
    assert second["answer"]["cached"] is True and second["scope"]["rerank"] == "cached"


def test_confidential_bundle_never_reaches_a_cloud_model(tmp_path, monkeypatch):
    """The development switch for synthetic Confidential records is off here, as it is outside development."""
    data = json.loads((APP / "config" / "model_policy.json").read_text())
    data["development_cloud_for_synthetic_confidential"] = False
    path = tmp_path / "policy.json"
    path.write_text(json.dumps(data))
    monkeypatch.setenv("NEURALMESH_MODEL_POLICY", str(path))
    model_policy._load.cache_clear()
    backend = FakeBackend()
    orchestrator, _, _ = build_mesh(backend=backend)
    result = run(orchestrator, GOLDEN[0]["question"])
    assert backend.calls == []
    assert result["answer"]["status"] == "evidence_only"
    assert any(c["decision"] == "blocked_by_policy" for c in result["model_calls"])
    model_policy._load.cache_clear()


def test_strict_mode_refuses_a_cloud_model_outside_development():
    model_policy._load.cache_clear()
    with pytest.raises(model_policy.PolicyViolation):
        model_policy.check_startup("staging")
    assert model_policy.check_startup("development") == []


def test_contact_details_are_removed_from_the_question():
    orchestrator, _, _ = build_mesh()
    result = run(orchestrator, "Which delays repeat across projects? Mail me at a.b@example.com or +91 98765 43210")
    assert "example.com" not in result["question"] and "98765" not in result["question"]
    assert result["resolved"]["contact_details_removed"] == 2


def test_context_builder_keeps_the_budget_and_counts_what_it_leaves_out():
    records = [EvidenceRecord(evidence_id=f"ceat:E-03-{i:02d}", kind="summary", node="ceat", document=f"ceat:E-03-{i:02d}",
                              title="t", version="2026-03", citation="CEAT", text="A sentence about storage. " * 60, rank=i)
               for i in range(1, 30)]
    built = build("q", "problem_solving", "ceat", "graph", [], records, [], budget=8_000)
    assert built.chars <= 8_000 + 400
    assert built.omitted > 0 and "omitted for size" in built.prompt


def test_check_rules_on_conflict_and_contact_details():
    failures = run_checks("CEAT integrates early [ceat:L-01-01]. Call 98765 43210 [ceat:L-01-01].",
                          {"ceat:L-01-01", "zensar:C-05-01"}, set(), [], [("ceat:L-01-01", "zensar:C-05-01")], [], [])
    assert {f["rule"] for f in failures} == {4, 6}


def test_checks_accept_the_marker_sentence_and_the_withheld_template():
    from services.context.check import run_checks, sentences
    withheld = [EvidenceRecord(evidence_id="ceat:E-01-01", kind="metadata", node="ceat", datapoint="ceat:E-01",
                               title="Compound formulations and material specs", reason="formulation data never leaves CEAT",
                               rule_id="R-NL-01", decision="BLOCKED_BY_POLICY")]
    answer = ("[NOT IN EVIDENCE] The tread compound formulation. "
              "Withheld: Compound formulations and material specs, reason: formulation data never leaves CEAT [ceat:E-01-01]. "
              "Lots are trended per supplier at receipt [ceat:E-03-01].")
    assert len(sentences(answer)) == 3
    assert run_checks(answer, {"ceat:E-03-01", "ceat:E-01-01"}, set(), withheld, [], [], []) == []
    bad = "Withheld: Compound formulations and material specs, which use 40 percent natural rubber [ceat:E-01-01]."
    assert [f["rule"] for f in run_checks(bad, {"ceat:E-01-01"}, set(), withheld, [], [], [])] == [3]


def test_prompts_are_versioned_files_and_every_step_is_timed(local_policy):
    from services.context import prompts

    assert prompts.versions() == {"answer": "mesh_answer_v4", "rerank": "mesh_rerank_v1", "classify": "mesh_classify_v1"}
    assert all(prompts.load(step).text for step in prompts.versions())
    orchestrator, _, _ = build_mesh(backend=FakeBackend())
    result = run(orchestrator, GOLDEN[0]["question"])
    assert [s["step"] for s in result["steps"]] == ["resolve", "route", "fan_out", "scope", "expand", "build_answer", "assemble"]
    assert all(isinstance(s["ms"], int) for s in result["steps"])
    assert all(c.get("prompt_version") for c in result["model_calls"])


# ── findings of the end-to-end verification run ─────────────────────────────
def test_withheld_metadata_items_carry_the_decision_about_their_content():
    caller = CallerContext("u", "ceat", frozenset({"group_user"}), "problem_solving")
    response = search_node(load_node_config("ceat"), caller, "compound formulation", "problem_solving")
    item = next(i for i in response["withheld"] if i["datapoint_id"] == "E-01")
    assert item["decision"] == "BLOCKED_BY_POLICY" and item["rule_id"] == "R-NL-01" and "text" not in item


def test_stopword_only_query_is_an_empty_query():
    caller = CallerContext("u", "harrisons", frozenset({"group_user"}), "problem_solving")
    assert search_node(load_node_config("harrisons"), caller, "the and of", "problem_solving")["status"] == "empty_query"


def test_summarize_citation_uses_the_bare_document_id(tmp_path):
    from mcp_nodes.access_store import AccessStore
    from mcp_nodes.server import summarize_node

    config = load_node_config("ceat")
    store = AccessStore(tmp_path / "grants.db", tmp_path / "audit.jsonl", config)
    caller = CallerContext("u", "ceat", frozenset({"group_user"}), "problem_solving")
    assert summarize_node(config, caller, "E-03-05", "problem_solving", store)["citation"] == "CEAT · E-03 · E-03-05"


def test_check_rejects_invented_content_about_a_withheld_item():
    withheld = [EvidenceRecord(evidence_id="ceat:C-03-01", kind="metadata", node="ceat", datapoint="ceat:C-03",
                               title="Channel pricing sheet (restricted)", reason="Datapoint is metadata-only", rule_id="R-NL-03")]
    fine = run_checks("Withheld: Channel pricing sheet (restricted) (Datapoint is metadata-only) [ceat:C-03-01].",
                      {"ceat:C-03-01"}, set(), withheld, [], [], [])
    bad = run_checks("The withheld record says secret pricing table rows [ceat:C-03-01].", {"ceat:C-03-01"}, set(), withheld, [], [], [])
    assert fine == [] and {f["rule"] for f in bad} == {3}


def test_check_rejects_more_than_ten_sentences():
    answer = " ".join(f"Sentence number {i} says something [ceat:E-03-01]." for i in range(12))
    assert {f["rule"] for f in run_checks(answer, {"ceat:E-03-01"}, set(), [], [], [], [])} == {7}


def test_rerank_that_rejects_everything_keeps_the_top_three(local_policy):
    import re as _re

    class RejectAll(FakeBackend):
        def complete(self, choice, system, user):
            if choice.step == "rerank":
                ids = _re.findall(r"Document: (\S+)", user)
                return json.dumps([{"document": i, "relevant": False, "reason": "t"} for i in ids]), 100, 5
            return super().complete(choice, system, user)

    orchestrator, _, _ = build_mesh(backend=RejectAll())
    result = run(orchestrator, GOLDEN[2]["question"])
    assert result["scope"]["rerank"].endswith("_all_rejected_kept_top3")
    kept = {r["document"] for r in result["records"]} - {l["source"] for l in result["relationships"]["used"]} - {l["target"] for l in result["relationships"]["used"]}
    assert 1 <= len(kept) <= 3 and result["scope"]["also_found"]
    assert result["answer"]["status"] == "answered"


def test_injection_text_is_removed_from_the_records_users_receive():
    from services.context.records import strip_injection

    orchestrator, _, _ = build_mesh()
    result = run(orchestrator, GOLDEN[7]["question"])
    page = next(r for r in result["records"] if r["document"] == "zensar:C-05-99")
    assert "IGNORE PREVIOUS INSTRUCTIONS" not in page["text"] and "[instruction-like text removed]" in page["text"]
    once = strip_injection(EvidenceRecord.model_validate(page))
    assert once.text.count("[instruction-like text removed]") == 1


@needs_model
def test_vector_index_build_is_deterministic(tmp_path):
    from knowledge.vector_index import ChunkRow, VectorIndex

    rows = [ChunkRow(f"ceat:E-03-0{i}", "E-03", "SUM", "Confidential", "2026-03", 0, text, "t")
            for i, text in enumerate(["Lots are trended per supplier.", "Rubber is stored off the floor.", "Each lot has a time to use."], start=1)]
    a, b = VectorIndex(tmp_path / "a"), VectorIndex(tmp_path / "b")
    a.build(rows), b.build(rows)
    assert a.all_text() == b.all_text()
    query = embedder.embed(["how long may a lot wait before mixing"])[0]
    assert a.search(query) == b.search(query)



@needs_model
def test_vector_store_rebuild_embeds_only_changed_chunks_and_deletes_removed_ones(tmp_path, monkeypatch):
    from knowledge import vector_index
    from knowledge.vector_index import ChunkRow, VectorIndex

    def row(i, text):
        return ChunkRow(f"ceat:E-03-0{i}", "E-03", "SUM", "Confidential", "2026-03", 0, text, "t")

    embedded: list[str] = []
    real = embedder.embed
    monkeypatch.setattr(vector_index.embedder, "embed", lambda texts: embedded.extend(texts) or real(texts))
    store = VectorIndex(tmp_path)
    assert store.build([row(1, "Lots are trended per supplier."), row(2, "Rubber is stored off the floor.")]) == 2
    embedded.clear()
    assert store.build([row(1, "Lots are trended per supplier."), row(3, "Each lot has a time to use.")]) == 2
    assert embedded == ["t. Each lot has a time to use."]
    assert "stored off the floor" not in store.all_text()
    keys = [k for k, _ in store.search(real(["time to use of a lot"])[0])]
    assert keys[0] == "ceat:E-03-03" and "ceat:E-03-02" not in keys

def test_validator_refuses_a_document_id_defined_twice():
    pack = json.loads((APP / "neuralmesh_kb_pack" / "data_pack" / "ceat" / "packs" / "engineering" / "pack.json").read_text())
    other = json.loads(json.dumps(pack))
    other["pack"]["pack_id"], other["pack"]["domain"] = "ceat.lessons", "lessons"
    report = validate_packs([("a", pack), ("b", other)])
    assert any("already defined" in e for e in report.errors)


def test_bundle_key_changes_when_a_document_version_changes():
    from services.context.cache import bundle_key

    def key(version):
        rec = EvidenceRecord(evidence_id="ceat:E-03-05", kind="summary", node="ceat", version=version, mode="SUM", text="t")
        return bundle_key("q", "problem_solving", "ceat", ["group_user"], None, [rec], [], "m", "p1")

    assert key("2026-03") != key("2026-04")


def test_expired_token_is_refused(client):
    token = issue_poc_token({"sub": "u", "company": "ceat", "roles": ["group_user"]}, hours=-1)
    assert client.get("/api/v1/mesh/nodes", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_an_abbreviation_never_ends_a_sentence_of_the_answer():
    from services.context.check import sentences

    assert sentences("Teams use tools, e.g. Spark, in production [a#1]. Lots are trended [b#2].") == [
        "Teams use tools, e.g. Spark, in production [a#1].", "Lots are trended [b#2]."]
    assert sentences("Lots are kept [c#1]. [NOT IN EVIDENCE] Line No. 3 rules. Losses are 1.1% [h#1].") == [
        "Lots are kept [c#1].", "[NOT IN EVIDENCE] Line No. 3 rules.", "Losses are 1.1% [h#1]."]



def test_an_answer_with_every_match_withheld_for_the_purpose_says_to_try_another_purpose(local_policy):
    orchestrator, _, _ = build_mesh(backend=FakeBackend())
    out = run(orchestrator, "Who can teach professional workplace skills?", purpose="career_mobility")
    assert out["records"] == [] and any(w["rule_id"] == "R-PURPOSE-01" for w in out["withheld_records"])
    assert out["answer"]["reason"] == ("The documents that match are not shared for the purpose career mobility. "
                                       "If the question has another purpose, ask it again with that purpose.")


def test_the_capabilities_of_a_node_list_a_never_leave_datapoint_only_to_its_company_and_mesh_admins():
    from mcp_nodes.auth import CallerContext
    from mcp_nodes.server_config import capabilities_payload, load_node_config, node_profile

    config = load_node_config("ceat")
    hidden = {k for k, v in config.datapoints.items() if v.get("never_leave")}
    assert hidden
    listed = lambda company, roles: {d["datapoint_id"] for d in capabilities_payload(  # noqa: E731
        config, CallerContext(f"{company}-user", company, frozenset(roles), "problem_solving"))["datapoints"]}
    assert not listed("kec", {"group_user"}) & hidden
    assert hidden <= listed("ceat", {"group_user"}) and hidden <= listed("zensar", {"group_user", "mesh_admin"})
    profile = node_profile(config)
    assert not any(config.datapoints[d]["title"] in profile for d in hidden)
