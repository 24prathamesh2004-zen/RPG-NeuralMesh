"""The generic context tools, the inspection layer of Snap and Score, the live lookup and the similarity layer."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from services import context_tools, similarity
from services.context_api import EndUser
from services.mesh_runtime import load_application_files
from tests.mesh_harness import build_mesh


@pytest.fixture
def rt():
    orchestrator, transport, mesh = build_mesh()
    loaded = load_application_files(mesh)
    mesh.rebuild()
    assert any(s.startswith("app:snapscore (") and "errors" not in s for s in loaded), loaded
    return SimpleNamespace(mesh=mesh, store=mesh.store, orchestrator=orchestrator, transport=transport)


def test_entity_and_related_serve_every_domain(rt):
    role = context_tools.entity(rt, "ceat:role/quality-engineer")
    assert role["type"] == "Role" and role["layer"] == "core" and role["connections"]["REQUIRES_SKILL"] == 4
    rel = context_tools.related(rt, "ceat:role/quality-engineer", group="structure")["related"]
    assert {x["id"] for x in rel["REQUIRES_SKILL"]} >= {"skill:quality-management", "skill:engineering"}
    asset = context_tools.entity(rt, "ceat:asset/finished_tyre")
    assert asset["layer"] == "core" and asset["type"] == "Asset" and asset["connections"]["CHECKED_FOR"] == 5
    two = context_tools.related(rt, "ceat:asset/finished_tyre", edge_types=["CHECKED_FOR", "BELONGS_TO"], depth=2)["related"]
    assert "BELONGS_TO" in two and any(x["via"] for x in two["BELONGS_TO"])


def test_inspection_profile_answers_the_snap_and_score_lookup(rt):
    profile = context_tools.inspection_profile(rt, "harrisons.smoked_sheet")
    assert profile["asset"]["id"] == "harrisons:asset/smoked_sheet" and profile["owner"] == "harrisons"
    assert {c["id"].rsplit("/", 1)[-1] for c in profile["conditions"]} == {"colour_unevenness", "bubbles", "mould", "dirt_foreign"}
    assert profile["grade_scale"]["grades"] == ["Grade 1", "Grade 2", "Grade 3", "Grade 4", "Grade 5"]
    assert [c["id"] for c in profile["expected_cover"]] == ["inspection:cover-type/stock_policy"]
    assert [s["id"] for s in profile["standards"]] == ["harrisons:F-01-05"] and profile["status"] == "proposed"
    with pytest.raises(Exception):
        context_tools.inspection_profile(rt, "nobody.nothing")


def test_live_cover_status_is_looked_up_at_the_node_and_carries_its_time(rt):
    user = EndUser("sf-1", "ceat", ("group_user",))
    out = asyncio.run(context_tools.live(rt, user, "ceat.finished_tyre", "cover_status"))
    assert out["decision"] == "ALLOWED" and out["value"] == "stock_policy active" and out["looked_up_at"] and out["mode"] == "LIVE"
    assert rt.transport.calls[-1][1] == "lookup"
    none = asyncio.run(context_tools.live(rt, user, "ceat.fleet_tyre", "history"))
    assert none["decision"] == "NOT_AVAILABLE" and none["value"] is None
    assert "ceat:asset/finished_tyre" in rt.mesh.graph and "cover_status" not in rt.mesh.graph.nodes["ceat:asset/finished_tyre"]


def test_record_inspection_adds_an_event_and_history_reads_it_back(rt):
    user = EndUser("insp-7", "harrisons", ("group_user",))
    result = context_tools.record_inspection(rt, user, {"inspection_id": "HM-2026-0001", "asset": "harrisons.smoked_sheet", "grade": "Grade 3",
                                                        "conditions": ["mould"], "review_status": "visible_concern_requires_review", "defect_area_pct": 1.2,
                                                        "inspected_at": "2026-11-07T09:00:00+00:00", "image_ref": "local://shots/0001.jpg"})
    assert result["accepted"], result
    hist = context_tools.history(rt, "harrisons.smoked_sheet")
    assert hist["inspections"][0]["grade"] == "Grade 3" and hist["inspections"][0]["conditions"] == ["mould"]
    kinds = {d["type"] for _, _, d in rt.mesh.graph.out_edges(result["inspection"], data=True)}
    assert kinds == {"INSPECTION_OF", "FOUND", "GRADED"}
    assert "image_ref" in rt.mesh.graph.nodes[result["inspection"]] and "local://" in rt.mesh.graph.nodes[result["inspection"]]["image_ref"]


def test_ask_with_an_inspection_context_routes_to_the_governing_standard(rt):
    docs, owners = context_tools.context_documents(rt, {"asset": "harrisons.smoked_sheet", "conditions": ["mould"], "grade": "Grade 3"})
    assert docs == {"harrisons:F-01-05"} and owners == {"harrisons"}


def test_similarity_job_writes_computed_links_with_reasons(rt):
    summary = similarity.run(rt.mesh)
    assert summary["written"] > 0 and summary["by_type"].get("Concept", 0) > 0
    out = context_tools.similar(rt, "ceat:role/quality-engineer")
    assert out["similar"] and all(x["reason"] and x["method"] == "computed" and x["status"] == "proposed" for x in out["similar"])
    again = similarity.run(rt.mesh)
    assert again["written"] == summary["written"] and again["retired"] == 0
    assert rt.mesh.checks and all(c["ok"] for c in rt.mesh.checks if c["rule"] in ("dangling_link", "type_signature"))


def test_a_node_refresh_does_not_retire_what_an_application_wrote_under_the_same_company(rt):
    from mcp_nodes.auth import CallerContext
    from mcp_nodes.server import export_graph_node

    user = EndUser("insp-7", "ceat", ("group_user",))
    result = context_tools.record_inspection(rt, user, {"inspection_id": "CEAT-T-1", "asset": "ceat.finished_tyre", "grade": "B", "conditions": ["cut"]})
    assert result["accepted"]
    service = CallerContext("svc:mesh-registry", "group", frozenset({"mesh_service"}), "problem_solving")
    rt.mesh.load_node_export(export_graph_node(rt.transport.configs["ceat"], service))
    rt.mesh.rebuild()
    g = rt.mesh.graph
    assert not g.nodes["ceat:asset/finished_tyre"].get("retired") and not g.nodes[result["inspection"]].get("retired")
    assert all(d["status"] == "approved" for _, _, d in g.out_edges(result["inspection"], data=True))
