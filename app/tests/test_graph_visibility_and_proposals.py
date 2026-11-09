"""Who may see an entity of the central graph, and who approves the entries an application proposed.

An entity of a never-leave datapoint (the datapoint, or a document in it) is shown only to its company and to mesh
admins. An application's entry is approved by each of its sides: the company of each end that has a Mesh Node, and the
group (a mesh admin as curator) for an end of the application's own vocabulary."""
from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.auth import issue_poc_token
from api.main import app
from api.routers import mesh as mesh_router
from services.mesh_runtime import load_application_files
from tests.mesh_harness import build_mesh

SECRET_DOC = "ceat:E-01-01"      # Compound formulation record A, in CEAT's never-leave datapoint E-01
SECRET_DATAPOINT = "ceat:E-01"
ORDINARY_DOC = "ceat:E-03-01"    # a CEAT summary every company may see


@pytest.fixture
def graph(monkeypatch):
    _, _, mesh = build_mesh()
    load_application_files(mesh)
    mesh.rebuild()
    rt = SimpleNamespace(mesh=mesh, store=mesh.store, export_status={}, group_packs=[])
    monkeypatch.setattr(mesh_router, "runtime", lambda: rt)
    return rt


def _as(company: str, *roles: str, email: str | None = None) -> dict:
    token = issue_poc_token({"sub": f"{company}-user", "email": email or f"{company}.reviewer@neuralmesh.local",
                             "company": company, "roles": list(roles or ("group_user",))})
    return {"Authorization": f"Bearer {token}"}


def _graph_ids(headers: dict) -> tuple[set[str], set[tuple[str, str]], dict]:
    body = TestClient(app).get("/api/v1/mesh/graph", headers=headers).json()
    return {n["id"] for n in body["nodes"]}, {(e["source"], e["target"]) for e in body["edges"]}, body["counts"]


def test_a_never_leave_entity_is_shown_only_to_its_company_and_to_mesh_admins(graph):
    kec_nodes, kec_edges, kec_counts = _graph_ids(_as("kec"))
    assert SECRET_DOC not in kec_nodes and SECRET_DATAPOINT not in kec_nodes
    assert not any(SECRET_DOC in pair or SECRET_DATAPOINT in pair for pair in kec_edges)
    assert ORDINARY_DOC in kec_nodes
    ceat_nodes, _, ceat_counts = _graph_ids(_as("ceat"))
    admin_nodes, _, _ = _graph_ids(_as("zensar", "group_user", "mesh_admin"))
    assert SECRET_DOC in ceat_nodes and SECRET_DOC in admin_nodes
    assert kec_counts["Document"] < ceat_counts["Document"]  # the counts follow what is shown


def test_the_links_list_leaves_out_links_into_a_never_leave_entity_of_another_company(graph):
    edges = graph.mesh.graph
    hidden = [d["id"] for a, b, d in edges.edges(data=True) if SECRET_DOC in (a, b)]
    assert hidden
    shown = {link["id"] for link in TestClient(app).get("/api/v1/mesh/graph/links", headers=_as("kec")).json()["links"]}
    assert not shown & set(hidden)


def _groups(headers: dict) -> dict[str, dict]:
    body = TestClient(app).get("/api/v1/mesh/proposals", headers=headers).json()
    return {g["type"]: g for g in body["groups"] if g["application"] == "snapscore"}


def _review(headers: dict, **payload) -> dict:
    response = TestClient(app).post("/api/v1/mesh/proposals/review", headers=headers, json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def _status(rt, entry_id: str) -> str:
    return next(p["status"] for p in rt.mesh.proposals() if p["id"] == entry_id)


def test_application_entries_are_listed_by_type_with_their_sides(graph):
    groups = _groups(_as("ceat"))
    assert {"OWNED_BY", "HAS_VIEW", "HAS_EXPECTED_COVER"} <= set(groups)
    owned = groups["OWNED_BY"]
    assert owned["name"] == "Snap and Score" and owned["counts"]["proposed"] == len(owned["entries"])
    ceat_owned = [e for e in owned["entries"] if e["sides"] == ["ceat"]]
    assert ceat_owned and all(e["you_review"] == ["ceat"] for e in ceat_owned)
    assert all(e["you_review"] == [] for e in owned["entries"] if "ceat" not in e["sides"])  # another company's side is not yours


def test_an_entry_is_approved_only_when_every_side_approved_it(graph):
    cover = [e for e in _groups(_as("ceat"))["HAS_EXPECTED_COVER"]["entries"]]
    ceat_entry = next(e for e in cover if e["sides"] == ["ceat", "group"])
    kec_entry = next(e for e in cover if e["sides"] == ["group", "kec"])
    done = _review(_as("ceat"), decision="approve", application="snapscore", type="HAS_EXPECTED_COVER")
    assert done["reviewed"] == sum(1 for e in cover if "ceat" in e["sides"])
    assert _status(graph, ceat_entry["id"]) == "proposed"  # the group side has not approved yet
    _review(_as("zensar", "group_user", "mesh_admin", email="presenter@neuralmesh.local"),
            decision="approve", application="snapscore", type="HAS_EXPECTED_COVER")
    assert _status(graph, ceat_entry["id"]) == "approved"
    assert _status(graph, kec_entry["id"]) == "proposed"  # KEC has not approved its side
    again = _review(_as("ceat"), decision="approve", application="snapscore", type="HAS_EXPECTED_COVER")
    assert again["reviewed"] == 0  # nothing left for CEAT's side


def test_one_side_that_rejects_rejects_the_entry(graph):
    owned = next(e for e in _groups(_as("kec"))["OWNED_BY"]["entries"] if e["sides"] == ["kec"])
    _review(_as("kec"), decision="reject", ids=[owned["id"]])
    assert _status(graph, owned["id"]) == "rejected"
    assert next(e for e in _groups(_as("kec"))["OWNED_BY"]["entries"] if e["id"] == owned["id"])["you_review"] == []


def test_a_review_needs_a_demo_account_and_names_what_it_reviews(graph):
    client = TestClient(app)
    outsider = client.post("/api/v1/mesh/proposals/review", headers=_as("ceat", email="someone@ceat.example"),
                           json={"decision": "approve", "application": "snapscore", "type": "OWNED_BY"})
    assert outsider.status_code == 403
    vague = client.post("/api/v1/mesh/proposals/review", headers=_as("ceat"), json={"decision": "approve"})
    assert vague.status_code == 422


def test_a_company_reviews_only_its_own_access_requests():
    """A CEAT reviewer cannot decide a request held by KEC's node. The check runs before any node store is opened."""
    refused = TestClient(app).post("/api/v1/mesh/governance/kec/requests/req-1/review", headers=_as("ceat"),
                                   json={"decision": "approve", "hours": 24})
    assert refused.status_code == 403 and refused.json()["detail"] == "Only the owning company reviews this request"


def test_the_ledger_names_a_never_leave_datapoint_only_to_its_company_and_mesh_admins(monkeypatch, tmp_path):
    import json
    from types import SimpleNamespace

    audit = tmp_path / "audit.jsonl"
    audit.write_text("\n".join(json.dumps({"timestamp": "2026-11-08T10:00:00Z", "trace_id": f"t{i}", "caller_company": "kec",
                                           "action": "search", "datapoint_id": dp, "decision": "BLOCKED_BY_POLICY",
                                           "rule_id": "R-NL-01"}) for i, dp in enumerate(["E-01", "E-03"])) + "\n")
    store = SimpleNamespace(pending=lambda: [], audit_path=audit)
    monkeypatch.setattr(mesh_router, "_node_stores", lambda: [("ceat", store)])
    titles = lambda headers: {e["datapoint_id"]: e["datapoint_title"]  # noqa: E731
                              for e in TestClient(app).get("/api/v1/mesh/governance", headers=headers).json()["audit"]}
    kec = titles(_as("kec"))
    assert kec["E-01"] is None and kec["E-03"]  # E-01 never leaves CEAT
    assert titles(_as("ceat"))["E-01"] and titles(_as("zensar", "group_user", "mesh_admin"))["E-01"]
