"""Aggregate views: grouped figures of a node's own database as evidence records, computed at request time."""
from __future__ import annotations

import json

from mcp_nodes.auth import CallerContext
from mcp_nodes.server import aggregate_node, load_node_config, search_node
from services.context.builder import build
from contracts.evidence import EvidenceRecord
from tests.mesh_harness import FakeBackend, build_mesh
from tests.test_mesh_v2 import GOLDEN, local_policy, run  # noqa: F401 - fixture

CALLER = CallerContext("user-1", "ceat", frozenset({"group_user"}), "problem_solving")


def test_a_view_is_released_at_group_level_and_only_a_listed_view_is_read():
    config = load_node_config("harrisons")
    record = aggregate_node(config, CALLER, "O-05", "v_spoilage_by_month", "problem_solving")
    assert record["decision"] == "ALLOWED" and record["kind"] == "aggregate" and record["mode"] == "SUM"
    assert record["evidence_id"] == "harrisons:O-05@v_spoilage_by_month"
    EvidenceRecord.model_validate({k: v for k, v in record.items() if k in EvidenceRecord.model_fields})
    lines = record["text"].split("\n")
    assert lines[0].startswith("Computed now from estate_mis.db") and record["rows"] >= len(lines) - 1
    groups = [line for line in lines[1:] if not line.endswith("not shown.")]
    assert groups and all("n_estates" in line and int(line.rsplit("n_estates ", 1)[1]) >= 3 for line in groups)
    # a view over months shows the latest months when it has more groups than one record holds
    months = [line.split(",", 1)[0].split(" ", 1)[1] for line in groups]
    assert len(groups) == 48 and months == sorted(months, reverse=True) and lines[-1].startswith("The latest 48 groups by month are shown")
    assert record["rows"] == 144 and lines[-1].endswith("96 earlier groups not shown.")
    # the table behind the view is not a listed view, so it is never read
    assert aggregate_node(config, CALLER, "O-05", "estate_month", "problem_solving")["decision"] == "NOT_AVAILABLE"
    assert aggregate_node(config, CALLER, "O-05", "estate_month; DROP TABLE x", "problem_solving")["decision"] == "NOT_AVAILABLE"
    # a live datapoint's view leaves as a live figure
    esg = aggregate_node(load_node_config("kec"), CALLER, "F-05", "v_esg_summary", "problem_solving")
    assert esg["decision"] == "ALLOWED" and esg["mode"] == "LIVE" and esg["rows"] == 4


def test_policy_decides_the_view_like_the_datapoint():
    config = load_node_config("ceat")
    blocked = CallerContext("user-2", "kec", frozenset({"group_user"}), "career_mobility")
    record = aggregate_node(config, blocked, "E-02", "v_failure_by_cause", "career_mobility")
    assert record["decision"] == "BLOCKED_BY_POLICY" and record["kind"] == "metadata" and record["text"] is None
    allowed = aggregate_node(config, CALLER, "E-02", "v_failure_by_cause", "problem_solving")
    assert allowed["decision"] == "ALLOWED" and "material-handling" in allowed["text"]


def test_search_results_name_the_views_of_their_datapoint():
    config = load_node_config("harrisons")
    response = search_node(config, CALLER, "latex spoilage trend by month", "problem_solving")
    released = [i for i in response["results"] if i["datapoint_id"] == "O-05"]
    assert released and released[0]["views"] == ["v_spoilage_by_month", "v_spoilage_by_band"]
    assert all("views" not in i for i in response["withheld"])


def test_the_flagship_question_carries_the_spoilage_view_as_evidence_and_it_is_cited(local_policy):
    orchestrator, transport, _ = build_mesh(backend=FakeBackend())
    result = run(orchestrator, GOLDEN[0]["question"])
    aggregates = [r for r in result["records"] if r["kind"] == "aggregate"]
    ids = {r["evidence_id"] for r in aggregates}
    assert "harrisons:O-05@v_spoilage_by_month" in ids
    assert [c for c in transport.calls if c[1] == "aggregate"]
    prompt = next(user for step, user in orchestrator.backend.calls if step == "answer")
    block = prompt.split("## Aggregate facts\n", 1)[1].split("\n## ", 1)[0]
    assert "[harrisons:O-05@v_spoilage_by_month]" in block and "spoil_pct" in block
    assert result["answer"]["status"] == "answered"
    assert "CANARY" not in json.dumps(result)


def test_the_repeat_failures_question_carries_both_views(local_policy):
    orchestrator, _, _ = build_mesh(backend=FakeBackend())
    result = run(orchestrator, GOLDEN[2]["question"])
    ids = {r["evidence_id"] for r in result["records"] if r["kind"] == "aggregate"}
    assert {"ceat:E-02@v_failure_by_cause", "kec:O-06@v_delay_by_category"} <= ids


def test_builder_places_aggregates_in_the_protected_block():
    rec = EvidenceRecord(evidence_id="kec:O-06@v_delay_by_category", kind="aggregate", node="kec", datapoint="kec:O-06",
                         title="Delay notes · delay by category", version="computed", mode="SUM", citation="KEC · O-06",
                         text="category material-supply, n_notes 24, share_pct 26.7")
    built = build("q", "problem_solving", "ceat", "routing", [], [rec], [])
    assert "## Aggregate facts\n[kec:O-06@v_delay_by_category]" in built.prompt and "kec:O-06@v_delay_by_category" in built.included


def test_rerank_output_cap_fits_a_full_verdict_list():
    """The re-rank reply holds one verdict per selected document. A cap under that cuts the JSON, the step reads
    nothing, no verdict is cached and every repeat of the question runs the model again (found on 2026-11-10 with
    a cap of 300 tokens and 12 documents)."""
    import json as _json
    from pathlib import Path as _Path
    from services.context import policy as model_policy
    from services.context.scoping import TOP_DOCUMENTS
    sample = _json.dumps([{"document": f"harrisons:O-05-{n:02d}#2", "relevant": n % 2 == 0,
                           "reason": "the text names the question's topic and the figures the question asks for"}
                          for n in range(TOP_DOCUMENTS)])
    needed = model_policy.estimate_tokens(sample)
    for name in ("model_policy.json", "model_policy.dev-standin.json"):
        cap = _json.loads((_Path(__file__).resolve().parents[1] / "config" / name).read_text())["steps"]["rerank"]["max_output_tokens"]
        assert cap >= needed, f"{name}: re-rank cap {cap} tokens is under the {needed} a full verdict list needs"
