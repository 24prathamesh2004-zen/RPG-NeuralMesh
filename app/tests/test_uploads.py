"""Uploaded inputs: a mesh admin's file becomes a document of a catalogue item in a named context graph, reaches the
node's pack, its keyword rows and the central graph, and the graph part around it can be searched and downloaded. An
input that belongs to no one company goes to the shared node, read by every company."""
from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from api.auth import issue_poc_token
from api.main import app
from api.routers import mesh as mesh_router
from mcp_nodes.auth import CallerContext
from mcp_nodes.server import export_graph_node, load_node_config
from tests.mesh_harness import build_mesh

DATA = Path(os.environ["NEURALMESH_DATA_PACK"])


@pytest.fixture
def mesh(monkeypatch):
    orchestrator, transport, graph = build_mesh()
    service = CallerContext("svc:mesh-registry", "group", frozenset({"mesh_service"}), "problem_solving")

    async def refresh():  # the real refresh asks the node processes: here the node config is read again from the files
        out = {}
        for node in ("ceat", "kec", "others"):
            counts = graph.load_node_export(export_graph_node(load_node_config(node, DATA), service))
            out[node] = f"loaded {counts['entities']} entities, {counts['relationships']} relationships"
        graph.rebuild()
        return out

    rt = SimpleNamespace(mesh=graph, store=graph.store, orchestrator=orchestrator, export_status={}, group_packs=[], refresh_from_nodes=refresh)
    monkeypatch.setattr(mesh_router, "runtime", lambda: rt)
    mesh_router._graph.cache_clear()
    for node in ("ceat", "others"):
        for folder in ("contributions", "added_items"):
            for path in (DATA / node / folder).glob("*.json"):
                path.unlink()
    return rt


def _headers(company="zensar", roles=("group_user",)):
    token = issue_poc_token({"sub": f"u-{company}", "email": f"{company}@example.com", "company": company, "roles": list(roles)})
    return {"Authorization": f"Bearer {token}"}


ADMIN = _headers("zensar", ("group_user", "mesh_admin"))


def _upload(client, text: str, **fields):
    data = {"node_id": "ceat", "datapoint": "E-03", "kind": "note", "title": "Storage note from the plant", "tags": "storage, rubber", **fields}
    return client.post("/api/v1/mesh/uploads", data=data, files={"file": ("plant_note.txt", text.encode(), "text/plain")}, headers=ADMIN)


def test_an_uploaded_text_becomes_a_document_of_the_item_in_the_pack_the_index_and_the_graph(mesh):
    client = TestClient(app)
    concept = next(d["label"] for n, d in mesh.mesh.graph.nodes(data=True) if d.get("type") == "Concept" and d.get("label"))
    text = (f"Natural rubber lots are kept off the floor and used first in, first out. {concept} is checked at receipt. "
            "A lot stored for more than ninety days gets an ageing check before mixing. " * 3)
    response = _upload(client, text)
    assert response.status_code == 201, response.text
    body = response.json()
    doc_id = body["document"]["id"]
    assert doc_id == "ceat:E-03-U001" and body["status"] == "accepted" and "body" not in body["document"]
    assert body["document"]["summary"].startswith("Natural rubber lots") and body["document"]["tags"] == ["storage", "rubber"]
    assert body["upload"]["format"] == "text" and body["upload"]["by_role"] == "Mesh admin"
    assert body["rebuild"]["pack_id"] == "ceat.engineering" and body["rebuild"]["index_rows"] == 1  # E-03 is summary-only: one row
    # the pack on disk carries the document, and index.db carries its summary row under the item's mode
    pack = json.loads((DATA / "ceat" / "packs" / "engineering" / "pack.json").read_text())
    assert any(d["id"] == doc_id and d["kind"] == "note" for d in pack["documents"])
    rows = sqlite3.connect(DATA / "ceat" / "index.db").execute("SELECT mode, dp FROM idx WHERE doc_id = ?", (doc_id,)).fetchall()
    assert rows == [("SUM", "E-03")]
    # the graph has the document, its item and the concept it mentions
    g = mesh.mesh.graph
    assert g.nodes[doc_id]["type"] == "Document" and g.nodes[doc_id]["datapoint"] == "ceat:E-03"
    mentioned = {b for a, b, d in g.out_edges(doc_id, data=True) if d["type"] == "MENTIONS"}
    assert mentioned and all(g.nodes[c]["label"] for c in mentioned)
    assert set(body["concept_matches"]) == mentioned and set(body["concept_matches"].values()) <= {"phrase", "words", "tag"}
    assert any(g.nodes[c]["label"] == concept and body["concept_matches"][c] == "phrase" for c in mentioned)
    graph = body["graph"]
    types = {n["type"] for n in graph["nodes"]}
    assert graph["centre"] == doc_id and {"Document", "Datapoint", "Concept", "Subsidiary"} <= types
    # the list shows it with its sharing rule, in the graph
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    item = next(u for u in listed["uploads"] if u["document"]["id"] == doc_id)
    assert item["in_graph"] is True and item["sharing"]["ceiling"] == "SUM" and item["sharing"]["never_leave"] is False
    assert "note" in listed["kinds"] and listed["export_formats"][:6] == ["json", "graphml", "csv", "pack", "cypher", "mermaid"]
    # a second upload under the same item gets the next number
    assert _upload(client, text, title="Second note").json()["document"]["id"] == "ceat:E-03-U002"


def test_downloads_in_each_format_carry_the_graph_part(mesh):
    client = TestClient(app)
    doc_id = _upload(client, "Rubber storage is covered and ventilated, and lots are issued first in, first out, every day.").json()["document"]["id"]
    base = f"/api/v1/mesh/uploads/{doc_id}/graph"
    assert client.get(base, headers=ADMIN).json()["centre"] == doc_id
    as_json = client.get(base, params={"format": "json"}, headers=ADMIN)
    assert as_json.headers["content-disposition"].endswith('.json"') and any(n["id"] == doc_id for n in as_json.json()["nodes"])
    graphml = client.get(base, params={"format": "graphml"}, headers=ADMIN)
    assert graphml.headers["content-type"].startswith("application/xml") and f'<node id="{doc_id}">' in graphml.text and "IN_DATAPOINT" in graphml.text
    csv = client.get(base, params={"format": "csv"}, headers=ADMIN).text.splitlines()
    assert csv[0] == "kind,id,type,label,subsidiary,source,target,status" and any(line.startswith(f"node,{doc_id},Document") for line in csv)
    pack = client.get(base, params={"format": "pack"}, headers=ADMIN).json()
    assert pack["format"] == "neuralmesh.knowledge-pack" and pack["documents"][0]["id"] == doc_id and pack["documents"][0]["body"]
    assert client.get(base, params={"format": "xlsx"}, headers=ADMIN).status_code == 400


@pytest.mark.parametrize("as_array", [False, True], ids=["document-object", "business-records"])
def test_business_json_creates_a_saved_context_graph_with_searchable_content(mesh, as_array):
    client = TestClient(app)
    concept_id, concept_label = next((n, d["label"]) for n, d in mesh.mesh.graph.nodes(data=True) if d.get("type") == "Concept" and d.get("label"))
    record = {"title": "JSON storage review", "content": f"Natural rubber storage is covered and ventilated. Lots are issued first in, first out. {concept_label} is checked at receipt.",
              "checks": {"moisture": "Check each lot before mixing", "ageing": "Review lots older than ninety days"}}
    content = json.dumps([record] if as_array else record).encode()
    response = client.post("/api/v1/mesh/uploads", headers=ADMIN,
                           data={"node_id": "others", "datapoint": "G-01", "graph_name": "Business JSON review"},
                           files={"file": ("business-records.json", content, "application/json")})
    assert response.status_code == 201, response.text
    created = response.json()
    doc_id = created["document"]["id"]
    graph_id = created["context_graph"]["id"]
    assert created["upload"]["format"] == "json" and created["status"] == "accepted"
    assert concept_id in created["document"]["concepts"]
    # Fetch again, independently of the creation response, to prove the saved graph and its links are available.
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    assert any(g["id"] == graph_id and g["name"] == "Business JSON review" and g["inputs"] == 1 for g in listed["graphs"])
    graph = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=ADMIN).json()
    assert doc_id in graph["documents"]
    assert any(e["source"] == doc_id and e["target"] == concept_id and e["type"] == "MENTIONS" for e in graph["edges"])
    pack = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=ADMIN, params={"format": "pack"}).json()
    assert "moisture: Check each lot" in pack["documents"][0]["body"]
    rows = sqlite3.connect(DATA / "others" / "index.db").execute("SELECT text FROM idx WHERE doc_id = ? OR doc_id LIKE ?", (doc_id, doc_id + "#%")).fetchall()
    assert any("Natural rubber storage" in row[0] for row in rows)


def test_invalid_json_does_not_create_an_upload_or_context_graph(mesh):
    client = TestClient(app)
    response = client.post("/api/v1/mesh/uploads", headers=ADMIN,
                           data={"node_id": "others", "datapoint": "G-01", "graph_name": "Invalid JSON graph"},
                           files={"file": ("invalid.json", b'{"content": "A business record",}', "application/json")})
    assert response.status_code == 422 and "JSON" in response.json()["detail"]
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    assert listed["uploads"] == [] and listed["graphs"] == []


def test_only_a_mesh_admin_uploads_and_a_bad_upload_is_refused_with_its_reason(mesh):
    client = TestClient(app)
    text = "Rubber storage is covered and ventilated, and lots are issued first in, first out, every day."
    refused = client.post("/api/v1/mesh/uploads", data={"node_id": "ceat", "datapoint": "E-03"},
                          files={"file": ("n.txt", text.encode(), "text/plain")}, headers=_headers("ceat"))
    assert refused.status_code == 403
    assert _upload(client, text, datapoint="Z-99").status_code == 422
    assert "catalogue item" in _upload(client, text, datapoint="Z-99").json()["detail"]
    assert "live item" in _upload(client, text, datapoint="F-04").json()["detail"]
    assert "At least 40" in _upload(client, "short").json()["detail"]
    assert "not a document kind" in _upload(client, text, kind="memo").json()["detail"]
    pack = json.dumps({"format": "neuralmesh.knowledge-pack", "pack": {}})
    sent = client.post("/api/v1/mesh/uploads", data={"node_id": "ceat", "datapoint": "E-03"},
                       files={"file": ("p.json", pack.encode(), "application/json")}, headers=ADMIN)
    assert sent.status_code == 422 and "import tool" in sent.json()["detail"]
    assert client.post("/api/v1/mesh/uploads", data={"node_id": "ceat", "datapoint": "E-03"},
                       files={"file": ("x.xlsx", b"1234" * 20, "application/octet-stream")}, headers=ADMIN).json()["detail"].startswith(".xlsx is not read")
    assert not list((DATA / "ceat" / "contributions").glob("*.json"))  # nothing kept
    items = client.get("/api/v1/mesh/uploads/items/ceat", headers=ADMIN).json()["items"]
    assert any(i["code"] == "E-01" and i["never_leave"] for i in items) and any(i["code"] == "E-03" and i["ceiling"] == "SUM" for i in items)


def test_a_document_under_a_never_leave_item_is_shown_to_its_company_and_admins_only(mesh):
    client = TestClient(app)
    text = "The compound recipe trial of March changed the carbon black grade and the cure time, and the result is recorded here."
    body = _upload(client, text, datapoint="E-01", title="Compound trial of March").json()
    doc_id = body["document"]["id"]
    assert body["rebuild"]["index_rows"] == 1  # a never-leave item keeps the title only in the index
    assert client.get(f"/api/v1/mesh/uploads/{doc_id}/graph", headers=_headers("ceat")).status_code == 200
    assert client.get(f"/api/v1/mesh/uploads/{doc_id}/graph", headers=_headers("kec")).status_code == 404
    assert client.get(f"/api/v1/mesh/graph/entity/{doc_id}", headers=_headers("kec")).status_code == 404
    found_by = lambda company: [r["id"] for r in client.get("/api/v1/mesh/graph/search", params={"q": "compound trial"}, headers=_headers(company)).json()["results"]]  # noqa: E731
    assert doc_id in found_by("ceat") and doc_id not in found_by("kec")
    own = client.get("/api/v1/mesh/uploads", headers=_headers("ceat")).json()["uploads"]
    assert any(u["document"]["id"] == doc_id and u["sharing"]["never_leave"] for u in own)
    assert client.get("/api/v1/mesh/uploads", headers=_headers("kec")).json()["uploads"] == []


def test_graph_search_finds_entities_by_label_alias_and_tag_with_their_sharing_rule(mesh):
    client = TestClient(app)
    results = client.get("/api/v1/mesh/graph/search", params={"q": "natural rubber"}, headers=_headers("kec")).json()
    assert results["results"] and results["by_vector"] is False
    first = results["results"][0]
    assert first["type"] in ("Concept", "Document") and first["matched"] in ("label", "alias or tag")
    doc = next(r for r in results["results"] if r["type"] == "Document")
    assert doc["sharing"]["ceiling"] in ("SUM", "RAG", "MD") and doc["sharing"]["company"] == doc["subsidiary"]
    assert isinstance(doc["connections"], dict)
    by_code = client.get("/api/v1/mesh/graph/search", params={"q": "E-03"}, headers=_headers("kec")).json()["results"]
    assert any(r["type"] == "Datapoint" and r["sharing"]["code"] == "E-03" for r in by_code)
    assert client.get("/api/v1/mesh/graph/search", params={"q": "   "}, headers=_headers("kec")).json()["results"] == []
    entity = client.get(f"/api/v1/mesh/graph/entity/{first['id']}", headers=_headers("kec")).json()
    assert entity["id"] == first["id"] and isinstance(entity["related"], dict) and entity["related"]


def test_a_removed_upload_leaves_the_pack_the_index_and_the_graph_and_its_record_stays(mesh):
    client = TestClient(app)
    doc_id = _upload(client, "Rubber storage is covered and ventilated, and lots are issued first in, first out, every day.").json()["document"]["id"]
    assert client.delete(f"/api/v1/mesh/uploads/{doc_id}", headers=_headers("ceat")).status_code == 403
    gone = client.delete(f"/api/v1/mesh/uploads/{doc_id}", headers=ADMIN)
    assert gone.status_code == 200 and gone.json()["status"] == "removed"
    pack = json.loads((DATA / "ceat" / "packs" / "engineering" / "pack.json").read_text())
    assert not any(d["id"] == doc_id for d in pack["documents"])
    assert sqlite3.connect(DATA / "ceat" / "index.db").execute("SELECT count(*) FROM idx WHERE doc_id = ?", (doc_id,)).fetchone()[0] == 0
    assert doc_id not in mesh.mesh.graph or mesh.mesh.graph.nodes[doc_id].get("retired")
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()["uploads"]
    assert any(u["document"]["id"] == doc_id and u["status"] == "removed" and u["removed"]["by_role"] == "Mesh admin" for u in listed)
    assert client.delete(f"/api/v1/mesh/uploads/ceat:E-03-U999", headers=ADMIN).status_code == 404


def test_markdown_layout_marks_are_not_words():
    from services.uploads import extract_text, summary_of
    text, fmt = extract_text("note.md", b"# Bale storage check\n\nThe store team checked **every** lot.\n\n## Found\n\n- Three lots were old.\n- Two bales were torn.\n")
    assert fmt == "markdown"
    assert text.startswith("Bale storage check\n\nThe store team checked every lot.")
    assert "#" not in text and "**" not in text and "\n- " not in text
    assert summary_of(text).startswith("Bale storage check The store team checked every lot.")


def test_joined_letters_of_a_pdf_or_word_file_are_read_as_their_letters():
    """A PDF or Word file often stores "fi", "fl" and "ff" as one joined letter. Kept as it is, "first" would be read
    as "rst", so the search would miss the word and the phrase "first 100 days" would link no concept."""
    import networkx as nx

    from services.uploads import concepts_in, extract_text
    text, _ = extract_text("review.txt", "The \ufb01rst 100 days: the \ufb01eld of\ufb01ce is on the \ufb02oor, with sta\ufb00 and wa\ufb04es.".encode())
    assert text == "The first 100 days: the field office is on the floor, with staff and waffles."
    graph = nx.DiGraph()
    graph.add_node("concept:acquisition-integration", type="Concept", label="Acquisition integration", aliases=["first 100 days"])
    rt = SimpleNamespace(mesh=SimpleNamespace(graph=graph))
    assert concepts_in(rt, text) == {"concept:acquisition-integration": "phrase"}


def test_an_upload_opens_a_named_context_graph_and_a_second_upload_adds_to_it(mesh):
    client = TestClient(app)
    concept = next(d["label"] for n, d in mesh.mesh.graph.nodes(data=True) if d.get("type") == "Concept" and d.get("label"))
    text = (f"Natural rubber lots are kept off the floor and used first in, first out. {concept} is checked at receipt. "
            "A lot stored for more than ninety days gets an ageing check before mixing.")
    first = _upload(client, text, graph_name="Plant 2 storage review").json()
    ref = first["context_graph"]
    assert ref["id"].startswith("g-") and ref["name"] == "Plant 2 storage review" and first["company"] == "CEAT"
    second = _upload(client, text + " The bales of the second store are checked the same way.", title="Second store", graph_id=ref["id"]).json()
    assert second["context_graph"] == ref
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    graph = next(g for g in listed["graphs"] if g["id"] == ref["id"])
    assert graph == {"id": ref["id"], "name": "Plant 2 storage review", "inputs": 2, "removed": 0, "nodes": ["ceat"], "companies": ["CEAT"],
                     "latest": max(first["upload"]["at"], second["upload"]["at"])}
    assert listed["graphs"][0]["id"] == ref["id"]  # newest first
    # the context graph is the union of the two parts: one company, one item, two documents, each shared concept once
    view = client.get(f"/api/v1/mesh/uploads/graphs/{ref['id']}", headers=ADMIN).json()
    assert view["name"] == ref["name"] and set(view["documents"]) == {first["document"]["id"], second["document"]["id"]}
    assert view["counts"]["Document"] == 2 and view["counts"]["Datapoint"] == 1 and view["counts"]["Subsidiary"] == 1
    shared_concept = next(n for n in view["nodes"] if n["type"] == "Concept" and n["label"] == concept)
    assert sum(1 for e in view["edges"] if e["target"] == shared_concept["id"] and e["type"] == "MENTIONS") == 2
    pack = client.get(f"/api/v1/mesh/uploads/graphs/{ref['id']}", params={"format": "pack"}, headers=ADMIN).json()
    assert {d["id"] for d in pack["documents"]} == set(view["documents"]) and all(d["body"] for d in pack["documents"])
    csv = client.get(f"/api/v1/mesh/uploads/graphs/{ref['id']}", params={"format": "csv"}, headers=ADMIN)
    assert csv.headers["content-disposition"] == 'attachment; filename="context_graph_Plant_2_storage_review.csv"'
    assert sum(1 for line in csv.text.splitlines() if ",Document," in line) == 2
    # a taken name is refused whatever its case, an unknown id cannot be added to, and a graph without inputs is not found
    taken = _upload(client, text, title="Third", graph_name="plant 2 STORAGE review")
    assert taken.status_code == 422 and "exists" in taken.json()["detail"]
    missing = _upload(client, text, title="Third", graph_id="g-00000000")
    assert missing.status_code == 422 and "no context graph" in missing.json()["detail"]
    assert client.get("/api/v1/mesh/uploads/graphs/g-00000000", headers=ADMIN).status_code == 404
    assert "at most 80" in _upload(client, text, title="Third", graph_name="x" * 81).json()["detail"]
    # without a graph, an upload is its own graph, named after its title
    alone = _upload(client, text, title="A note on its own").json()
    assert alone["context_graph"]["name"] == "A note on its own" and alone["context_graph"]["id"] != ref["id"]


def test_dropping_a_context_graph_removes_every_input_and_keeps_the_records(mesh):
    client = TestClient(app)
    first = _upload(client, "Rubber storage is covered and ventilated, and lots are issued first in, first out, every day.", graph_name="Storage across the group").json()
    ref = first["context_graph"]
    second = _upload(client, "Every store keeps the oldest bale in front and the newest at the back, so the issue is first in, first out.",
                     node_id="others", datapoint="G-01", title="Shared storage note", graph_id=ref["id"]).json()
    assert second["node_id"] == "others" and second["company"] == "Others" and second["sharing"]["shared"] is True
    assert second["rebuild"]["pack_id"] == "others.general" and second["rebuild"]["index_rows"] == 1  # G-01 shares the full text: one chunk
    assert client.delete(f"/api/v1/mesh/uploads/graphs/{ref['id']}", headers=_headers("ceat")).status_code == 403
    dropped = client.delete(f"/api/v1/mesh/uploads/graphs/{ref['id']}", headers=ADMIN)
    assert dropped.status_code == 200, dropped.text
    body = dropped.json()
    assert body["graph"] == ref and {r["document"]["id"] for r in body["removed"]} == {first["document"]["id"], second["document"]["id"]}
    assert body["rebuilt"] == ["ceat.engineering", "others.general"] and set(body["refresh"]) == {"ceat", "others"}
    for node, domain, doc_id in (("ceat", "engineering", first["document"]["id"]), ("others", "general", second["document"]["id"])):
        pack = json.loads((DATA / node / "packs" / domain / "pack.json").read_text())
        assert not any(d["id"] == doc_id for d in pack["documents"])
        rows = sqlite3.connect(DATA / node / "index.db").execute("SELECT count(*) FROM idx WHERE doc_id = ? OR doc_id LIKE ?", (doc_id, doc_id + "#%")).fetchone()[0]
        assert rows == 0
        assert doc_id not in mesh.mesh.graph or mesh.mesh.graph.nodes[doc_id].get("retired")
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    graph = next(g for g in listed["graphs"] if g["id"] == ref["id"])
    assert graph["inputs"] == 0 and graph["removed"] == 2 and graph["nodes"] == [] and graph["companies"] == []
    assert all(u["status"] == "removed" and u["removed"]["by_role"] == "Mesh admin" for u in listed["uploads"] if u["context_graph"]["id"] == ref["id"])
    assert client.get(f"/api/v1/mesh/uploads/graphs/{ref['id']}", headers=ADMIN).status_code == 404
    # a second drop removes nothing more and rebuilds the packs again, an unknown id is not found
    again = client.delete(f"/api/v1/mesh/uploads/graphs/{ref['id']}", headers=ADMIN).json()
    assert again["removed"] == [] and again["rebuilt"] == ["ceat.engineering", "others.general"] and again["failed"] == {}
    assert client.delete("/api/v1/mesh/uploads/graphs/g-00000000", headers=ADMIN).status_code == 404
    # the name of a dropped graph is free again, and its id can still be added to
    again = _upload(client, "A new note on covered storage, ventilation and first in, first out issue of the lots.", title="Again", graph_name="Storage across the group").json()
    assert again["context_graph"]["id"] != ref["id"]
    revived = _upload(client, "A later note added to the dropped graph, on the same covered storage rule.", title="Later", graph_id=ref["id"]).json()
    assert revived["context_graph"] == ref


def test_a_shared_input_is_listed_to_every_company_and_found_in_the_search_with_its_rule(mesh):
    from shared.registry import node as registered_node

    client = TestClient(app)
    text = "Group travel policy, shared: every trip over two nights is booked through the group desk, and the itinerary is attached to the expense claim."
    body = _upload(client, text, node_id="others", datapoint="G-01", title="Group travel policy", kind="policy", tags="travel", graph_name="Group policies").json()
    doc_id = body["document"]["id"]
    assert doc_id == "others:G-01-U001" and body["sharing"]["shared"] is True
    for company in ("kec", "ceat"):
        own = client.get("/api/v1/mesh/uploads", headers=_headers(company)).json()
        assert any(u["document"]["id"] == doc_id and u["sharing"]["shared"] and u["sharing"]["ceiling"] == "RAG" and u["company"] == "Others" for u in own["uploads"])
        assert any(g["name"] == "Group policies" and g["companies"] == ["Others"] for g in own["graphs"])
        assert client.get(f"/api/v1/mesh/uploads/{doc_id}/graph", headers=_headers(company)).status_code == 200
    found = client.get("/api/v1/mesh/graph/search", params={"q": "travel policy"}, headers=_headers("kec")).json()["results"]
    hit = next(r for r in found if r["id"] == doc_id)
    assert hit["company"] == "Others" and hit["sharing"]["shared"] is True and hit["sharing"]["ceiling"] == "RAG"
    entity = client.get(f"/api/v1/mesh/graph/entity/{doc_id}", headers=_headers("kec")).json()
    assert entity["company"] == "Others" and entity["sharing"]["shared"] is True
    items = client.get("/api/v1/mesh/uploads/items/others", headers=ADMIN).json()["items"]
    assert items == [{"code": "G-01", "title": "Shared inputs of the group", "ceiling": "RAG", "never_leave": False, "owner_role": "Mesh admin", "domain": "general"}]
    # the shared node is registered as shared, a question never names it, and nobody signs up for it
    assert registered_node("others").shared is True and registered_node("ceat").shared is False
    assert mesh.mesh.graph.nodes["org:others"]["shared"] is True and mesh.mesh.graph.nodes["org:others"]["label"] == "Others"
    assert mesh.mesh.resolve("What do the others do about travel claims?")["named_subsidiaries"] == []
    assert mesh.mesh.resolve("What does CEAT do about travel claims?")["named_subsidiaries"] == ["ceat"]
    assert "others" not in {c["id"] for c in client.get("/api/v1/auth/companies").json()["companies"]}


def test_a_pack_download_carries_only_what_the_person_may_read(mesh):
    client = TestClient(app)
    text = "Natural rubber lots are kept off the floor and used first in, first out, and a lot older than ninety days gets an ageing check."
    own = _upload(client, text, graph_name="Pack download check").json()
    shared = _upload(client, "A shared storage note with the same first in, first out rule, read by every company.", node_id="others", datapoint="G-01",
                     title="Shared rule", graph_id=own["context_graph"]["id"]).json()
    doc_id, shared_id, gid = own["document"]["id"], shared["document"]["id"], own["context_graph"]["id"]
    # the mesh admin and the own company get the text, another company gets the summary of a summary item and the text of a shared input
    for headers in (ADMIN, _headers("ceat")):
        docs = client.get(f"/api/v1/mesh/uploads/{doc_id}/graph", params={"format": "pack"}, headers=headers).json()["documents"]
        assert docs[0]["id"] == doc_id and docs[0]["body"].startswith("Natural rubber lots")
    docs = client.get(f"/api/v1/mesh/uploads/{doc_id}/graph", params={"format": "pack"}, headers=_headers("kec")).json()["documents"]
    assert docs[0]["id"] == doc_id and "body" not in docs[0] and docs[0]["summary"].startswith("Natural rubber lots")
    pack = {d["id"]: d for d in client.get(f"/api/v1/mesh/uploads/graphs/{gid}", params={"format": "pack"}, headers=_headers("kec")).json()["documents"]}
    assert set(pack) == {doc_id, shared_id} and "body" not in pack[doc_id] and pack[shared_id]["body"].startswith("A shared storage note")
    pack = {d["id"]: d for d in client.get(f"/api/v1/mesh/uploads/graphs/{gid}", params={"format": "pack"}, headers=ADMIN).json()["documents"]}
    assert pack[doc_id]["body"] and pack[shared_id]["body"]


def test_a_drop_whose_rebuild_fails_names_the_pack_and_a_second_drop_repairs_it(mesh, monkeypatch):
    from services import uploads

    client = TestClient(app)
    first = _upload(client, "Rubber storage is covered and ventilated, and lots are issued first in, first out, every day.", graph_name="Repair check").json()
    gid = first["context_graph"]["id"]
    second = _upload(client, "A shared note on covered storage and first in, first out issue, kept for every company.", node_id="others", datapoint="G-01",
                     title="Shared note", graph_id=gid).json()
    real = uploads.packgen.rebuild_domain_pack

    def failing(node, domain, build_vectors=True):
        if node == "others":
            raise uploads.PackCheckFailed("Pack validation failed: the embedding model is missing")
        return real(node, domain, build_vectors=build_vectors)

    monkeypatch.setattr(uploads.packgen, "rebuild_domain_pack", failing)
    body = client.delete(f"/api/v1/mesh/uploads/graphs/{gid}", headers=ADMIN).json()
    assert {r["document"]["id"] for r in body["removed"]} == {first["document"]["id"], second["document"]["id"]}
    assert body["rebuilt"] == ["ceat.engineering"] and body["failed"] == {"others.general": "the embedding model is missing"}
    pack = json.loads((DATA / "others" / "packs" / "general" / "pack.json").read_text())
    assert any(d["id"] == second["document"]["id"] for d in pack["documents"])  # the stale pack still holds the document
    monkeypatch.setattr(uploads.packgen, "rebuild_domain_pack", real)
    repaired = client.delete(f"/api/v1/mesh/uploads/graphs/{gid}", headers=ADMIN).json()
    assert repaired["removed"] == [] and repaired["rebuilt"] == ["ceat.engineering", "others.general"] and repaired["failed"] == {}
    pack = json.loads((DATA / "others" / "packs" / "general" / "pack.json").read_text())
    assert not any(d["id"] == second["document"]["id"] for d in pack["documents"])


def test_a_failed_upload_leaves_no_document_in_the_pack(mesh, monkeypatch):
    from services import uploads

    client = TestClient(app)
    real = uploads.packgen.rebuild_domain_pack

    def failing_after_write(node, domain, build_vectors=True):
        real(node, domain, build_vectors=False)  # the pack and the index are written, as before the vectors are built
        raise uploads.PackCheckFailed("Pack validation failed: the embedding model is missing")

    monkeypatch.setattr(uploads.packgen, "rebuild_domain_pack", failing_after_write)
    refused = _upload(client, "Rubber storage is covered and ventilated, and lots are issued first in, first out, every day.", title="Lost note")
    assert refused.status_code == 422 and "embedding model" in refused.json()["detail"]
    pack = json.loads((DATA / "ceat" / "packs" / "engineering" / "pack.json").read_text())
    assert not any(d["title"] == "Lost note" for d in pack["documents"])
    assert sqlite3.connect(DATA / "ceat" / "index.db").execute("SELECT count(*) FROM idx WHERE title = 'Lost note'").fetchone()[0] == 0
    assert not list((DATA / "ceat" / "contributions").glob("*.json"))


def test_the_kind_other_keeps_the_typed_name_and_is_refused_without_one(mesh):
    client = TestClient(app)
    text = "Bales are turned every two weeks in the monsoon months and the floor is checked for damp before stacking. " * 3
    refused = _upload(client, text, kind="other")
    assert refused.status_code == 422 and "Name the kind" in refused.json()["detail"]
    response = _upload(client, text, kind="other", kind_label="  Site  visit   log ")
    assert response.status_code == 201, response.text
    assert response.json()["document"]["kind"] == "other" and response.json()["document"]["kind_label"] == "Site visit log"
    pack = json.loads((DATA / "ceat" / "packs" / "engineering" / "pack.json").read_text())
    assert any(d["kind"] == "other" and d.get("kind_label") == "Site visit log" for d in pack["documents"])


def test_a_new_catalogue_item_named_at_upload_never_leaves_the_company(mesh):
    from knowledge import packgen
    client = TestClient(app)
    text = "The fire drill of the bale store found two blocked exits and a hose reel without pressure, both fixed the same day. " * 3
    try:
        areas = client.get("/api/v1/mesh/uploads/items/ceat", headers=ADMIN).json()["new_item_areas"]
        assert "lessons" in [a["domain"] for a in areas]
        assert client.get("/api/v1/mesh/uploads/items/others", headers=ADMIN).json()["new_item_areas"] == []
        # refusals leave no item behind
        for fields, words in [({"new_item_area": "talent"}, "no talent area"), ({"new_item_title": "Camso integration playbook and post-mortems"}, "Choose it from the list"),
                              ({"node_id": "others", "datapoint": "G-01"}, "shared node")]:
            r = _upload(client, text, **{"datapoint": "new", "new_item_title": "Bale store fire drills", "new_item_area": "lessons", **fields})
            assert r.status_code == 422 and words in r.json()["detail"], r.text
        r = client.post("/api/v1/mesh/uploads", data={"node_id": "ceat", "datapoint": "new", "kind": "note", "new_item_title": "Bale store fire drills", "new_item_area": "lessons"},
                        files={"file": ("short.txt", b"too short", "text/plain")}, headers=ADMIN)
        assert r.status_code == 422
        assert not list((DATA / "ceat" / "added_items").glob("*.json"))
        # the upload names the item, which takes the next free code of the area and the strictest rule
        response = _upload(client, text, datapoint="new", new_item_title="Bale store fire drills", new_item_area="lessons")
        assert response.status_code == 201, response.text
        body = response.json()
        assert body["new_item"] == {"code": "L-02", "title": "Bale store fire drills", "domain": "lessons"}
        assert body["document"]["datapoint"] == "ceat:L-02" and body["rebuild"]["pack_id"] == "ceat.lessons"
        pack = json.loads((DATA / "ceat" / "packs" / "lessons" / "pack.json").read_text())
        dp = next(d for d in pack["datapoints"] if d["id"] == "ceat:L-02")
        assert dp["never_leave"] is True and dp["ceiling"] == "MD" and dp["sensitivity"] == "Restricted"
        rows = sqlite3.connect(DATA / "ceat" / "index.db").execute("SELECT mode FROM idx WHERE doc_id = ?", (body["document"]["id"],)).fetchall()
        assert rows == [("MD",)]
        items = client.get("/api/v1/mesh/uploads/items/ceat", headers=ADMIN).json()["items"]
        assert {"code": "L-02", "never_leave": True}.items() <= next(i for i in items if i["code"] == "L-02").items()
        # the item stays across a rebuild of its pack, and another company does not see the document in its list
        packgen.rebuild_domain_pack("ceat", "lessons", build_vectors=False)
        assert any(d["id"] == "ceat:L-02" for d in json.loads((DATA / "ceat" / "packs" / "lessons" / "pack.json").read_text())["datapoints"])
        listed = client.get("/api/v1/mesh/uploads", headers=_headers("kec")).json()["uploads"]
        assert body["document"]["id"] not in [u["document"]["id"] for u in listed]
    finally:
        for folder in ("contributions", "added_items"):
            for path in (DATA / "ceat" / folder).glob("*.json"):
                path.unlink()
        packgen.rebuild_domain_pack("ceat", "lessons", build_vectors=False)


def test_the_kind_is_detected_when_it_is_left_to_the_mesh(mesh):
    client = TestClient(app)
    text = "Teardown of the six failed joints found water entry as the cause in three, a preparation error in two and a connector defect in one. " * 3
    response = _upload(client, text, kind="auto", title="Teardown findings, failed joints")
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["document"]["kind"] == "rca"
    assert body["kind_detected"]["by"] in ("model", "rules") and body["kind_detected"]["reason"]
    record = json.loads((DATA / "ceat" / "contributions" / f"{body['document']['id'].split(':', 1)[1]}.json").read_text())
    assert record["kind_detected"] == body["kind_detected"]


def test_the_kind_falls_back_to_the_rules_when_the_model_reply_is_unusable():
    from services import upload_kind
    kinds = ["report", "rca", "note", "other"]
    assert upload_kind.detect("Group forum, minutes of September", "m.txt", "", kinds, call_model=lambda *a: "not json")["by"] == "rules"
    assert upload_kind.detect("x", "x.txt", "", kinds, call_model=lambda *a: '{"kind": "made_up"}')["kind"] == "report"
    by_model = upload_kind.detect("x", "x.txt", "", kinds, call_model=lambda *a: '{"kind": "other", "label": "Site visit log", "reason": "a visit"}')
    assert by_model == {"kind": "other", "label": "Site visit log", "by": "model", "reason": "a visit"}
    assert upload_kind.detect("x", "x.txt", "", kinds, call_model=lambda *a: '{"kind": "other", "label": ""}')["by"] == "rules"


def test_a_mesh_admin_adds_and_removes_a_download_format(mesh, monkeypatch, tmp_path):
    monkeypatch.setenv("NEURALMESH_EXPORT_FORMATS", str(tmp_path / "formats"))
    client = TestClient(app)
    text = "Natural rubber lots are kept off the floor and used first in, first out. A lot stored for more than ninety days is checked. " * 3
    graph_id = _upload(client, text).json()["context_graph"]["id"]
    listed = client.get("/api/v1/mesh/uploads", headers=ADMIN).json()
    assert {"cypher", "mermaid"} <= set(listed["export_formats"]) and {f["id"] for f in listed["export_format_list"]} >= {"json", "cypher"}
    cypher = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}?format=cypher", headers=ADMIN)
    assert cypher.status_code == 200 and "MERGE (n:Entity" in cypher.text
    fields = {"name": "Tab separated", "extension": "tsv", "escape": "none", "header": "id\ttype\tlabel",
              "node_line": "{id}\t{type}\t{label}", "edge_line": "{source}\t{type}\t{target}"}
    assert client.post("/api/v1/mesh/uploads/formats", json=fields, headers=_headers("ceat")).status_code == 403
    bad = client.post("/api/v1/mesh/uploads/formats", json={**fields, "node_line": "{id} {secret}"}, headers=ADMIN)
    assert bad.status_code == 422 and "{secret} is not a placeholder" in bad.json()["detail"]
    assert client.post("/api/v1/mesh/uploads/formats", json={**fields, "name": "Cypher (for Neo4j)"}, headers=ADMIN).status_code == 422
    added = client.post("/api/v1/mesh/uploads/formats", json=fields, headers=ADMIN)
    assert added.status_code == 201, added.text
    assert added.json()["format"]["id"] == "tab-separated"
    out = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}?format=tab-separated", headers=ADMIN)
    assert out.status_code == 200 and out.text.startswith("id\ttype\tlabel\n") and 'filename="context_graph_' in out.headers["content-disposition"] and out.headers["content-disposition"].endswith('.tsv"')
    assert client.delete("/api/v1/mesh/uploads/formats/cypher", headers=ADMIN).status_code == 404
    assert client.delete("/api/v1/mesh/uploads/formats/tab-separated", headers=ADMIN).status_code == 200
    assert client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}?format=tab-separated", headers=ADMIN).status_code == 400


def test_an_output_template_file_is_kept_and_gives_the_graph_in_its_lines(mesh, monkeypatch, tmp_path):
    monkeypatch.setenv("NEURALMESH_EXPORT_FORMATS", str(tmp_path / "formats"))
    client = TestClient(app)
    text = "Natural rubber lots are kept off the floor and used first in, first out. A lot stored for more than ninety days is checked. " * 3
    graph_id = _upload(client, text).json()["context_graph"]["id"]
    template = b"[extension] txt\n[header]\nEntities and links\n[entity]\n- {label} ({type})\n[link]\n- {source} {type} {target}\n"
    kept = client.post("/api/v1/mesh/uploads/formats/file", files={"file": ("plain_list.txt", template, "text/plain")}, headers=ADMIN)
    assert kept.status_code == 201, kept.text
    fid = kept.json()["format"]["id"]
    again = client.post("/api/v1/mesh/uploads/formats/file", files={"file": ("plain_list.txt", template, "text/plain")}, headers=ADMIN)
    assert again.status_code == 201 and again.json()["format"]["id"] == fid  # the same template file is chosen again, not refused
    out = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}?format={fid}", headers=ADMIN)
    assert out.status_code == 200 and out.text.startswith("Entities and links\n- ") and "(Document)" in out.text
    assert client.post("/api/v1/mesh/uploads/formats/file", files={"file": ("x.txt", b"no sections", "text/plain")}, headers=ADMIN).status_code == 422
    assert client.post("/api/v1/mesh/uploads/formats/file", files={"file": ("x.txt", template, "text/plain")}, headers=_headers("ceat")).status_code == 403


def test_the_text_of_an_upload_is_kept_once_in_its_record_and_the_pack_points_to_it(mesh):
    client = TestClient(app)
    text = "A shared storage note for every company. Bales are kept on pallets in a covered bay and issued first in, first out. " * 4
    body = _upload(client, text, node_id="others", datapoint="G-01").json()
    doc_id = body["document"]["id"]
    local = doc_id.split(":", 1)[1]
    record = json.loads((DATA / "others" / "contributions" / f"{local}.json").read_text())
    assert record["document"]["body"].startswith("A shared storage note")  # the one copy of the text
    pack = json.loads((DATA / "others" / "packs" / "general" / "pack.json").read_text())
    doc = next(d for d in pack["documents"] if d["id"] == doc_id)
    assert "body" not in doc and doc["body_file"] == f"contributions/{local}.json"
    rows = sqlite3.connect(DATA / "others" / "index.db").execute("SELECT mode, text FROM idx WHERE doc_id LIKE ?", (doc_id + "#%",)).fetchall()
    assert rows and all(mode == "RAG" for mode, _ in rows) and rows[0][1].startswith("A shared storage note")  # passages read from the record


def test_rebuilding_one_pack_keeps_the_index_rows_of_uploads_in_the_other_packs(mesh):
    from knowledge import packgen
    client = TestClient(app)
    text = "Bales are kept on pallets in a covered bay and issued first in, first out, and every lot is checked at receipt. " * 3
    first = _upload(client, text, datapoint="O-01").json()["document"]["id"]  # operations, passages
    _upload(client, text, datapoint="E-03")  # engineering: its rebuild must not touch the operations rows
    con = sqlite3.connect(DATA / "ceat" / "index.db")
    assert con.execute("SELECT count(*) FROM idx WHERE doc_id LIKE ?", (first + "#%",)).fetchone()[0] > 0
    for folder in ("contributions",):
        for path in (DATA / "ceat" / folder).glob("*.json"):
            path.unlink()
    packgen.rebuild_domain_pack("ceat", "operations", build_vectors=False)


def test_the_form_is_filled_from_the_file_and_nothing_is_kept(mesh):
    client = TestClient(app)
    labels = [d["label"] for n, d in mesh.mesh.graph.nodes(data=True) if d.get("type") == "Concept" and d.get("label")][:3]
    body = "# Bale storage humidity check, Plant 3\n\n" + " ".join(f"The check covered {label.lower()} in the bay." for label in labels) * 2
    first = _upload(client, body, title="", tags="")  # empty title and tags: read from the file
    assert first.status_code == 201, first.text
    doc = first.json()["document"]
    assert doc["title"] == "Bale storage humidity check, Plant 3" and doc["tags"]  # the heading, and the concepts it names
    graph = first.json()["context_graph"]
    before = sorted(p.name for p in (DATA / "ceat" / "contributions").glob("*.json"))
    files = {"file": ("second_check.md", ("# Second humidity check\n\n" + body.split("\n\n", 1)[1]).encode(), "text/markdown")}
    suggested = client.post("/api/v1/mesh/uploads/suggest", data={"node_id": "ceat", "datapoint": "E-03"}, files=files, headers=ADMIN)
    assert suggested.status_code == 200, suggested.text
    s = suggested.json()
    assert s["title"] == "Second humidity check" and s["kind"]["kind"] in ("report", "note") and len(s["concepts"]) >= 2
    assert s["graph"]["mode"] == "append" and s["graph"]["id"] == graph["id"] and len(s["graph"]["shared"]) >= 2
    assert sorted(p.name for p in (DATA / "ceat" / "contributions").glob("*.json")) == before  # nothing kept
    other = client.post("/api/v1/mesh/uploads/suggest", files={"file": ("solar_plan.md", b"# Solar inverter plan\n\nEach rooftop inverter is cleaned every quarter and its fan checked every month.", "text/markdown")}, headers=ADMIN)
    assert other.json()["graph"] == {"mode": "new", "id": None, "name": "Solar inverter plan", "shared": [], "reason": other.json()["graph"]["reason"]}
    assert client.post("/api/v1/mesh/uploads/suggest", files=files, headers=_headers("ceat")).status_code == 403


def test_a_title_comes_from_the_heading_a_json_title_or_the_file_name():
    from services.upload_suggest import title_of
    assert title_of("x.md", "Plant 3 audit\n\nText.", "markdown") == "Plant 3 audit"
    assert title_of("05_supplier_lot_rejections_q3_2026.csv", "supplier,lots", "csv") == "Supplier lot rejections Q3 2026"
    assert title_of("02_kec_site_delay_log_jul_sep_2026.csv", "a,b", "csv") == "KEC International site delay log Jul Sep 2026"
    assert title_of("s.json", '{"title": "Month 4 status", "a": 1}', "json") == "Month 4 status"
    assert title_of("s.json", "title: Month 4 status\n\nnote: x", "json") == "Month 4 status"
    long = "This first line is a full sentence with far more than fifteen words in it, so it is not a heading at all."
    assert title_of("field_notes.txt", long + "\nmore", "text") == "Field notes"


def test_tags_and_the_graph_follow_strong_matches_only(mesh):
    """A one-word other name of a concept links the document, but does not make a tag or decide the graph."""
    from services import upload_suggest
    g = mesh.mesh.graph
    cid, data = next((n, d) for n, d in g.nodes(data=True) if d.get("type") == "Concept" and any(len(a.split()) == 1 for a in d.get("aliases") or []))
    one_word = next(a for a in data["aliases"] if len(a.split()) == 1)
    weak = upload_suggest.ordered_concepts(mesh, f"The team kept a {one_word} for the work.", {cid: "phrase"})
    strong = upload_suggest.ordered_concepts(mesh, f"The team wrote about {data['label']} for the work.", {cid: "phrase"})
    assert weak[0]["strong"] is False and upload_suggest.tags_of(weak) == []
    assert strong[0]["strong"] is True and upload_suggest.tags_of(strong)
    records = [("ceat", {"context_graph": {"id": "g-1", "name": "One"}, "document": {"id": "ceat:E-03-U001", "title": "x"},
                         "concept_matches": {cid: "phrase", "concept:other": "phrase"}, "upload": {"at": "2026-11-10"}})]
    assert upload_suggest.graph_for({cid}, "A new topic", records, lambda r: r["context_graph"])["mode"] == "new"  # 1 shared strong concept
    assert upload_suggest.graph_for({cid, "concept:other"}, "A new topic", records, lambda r: r["context_graph"])["id"] == "g-1"


def test_code_accepts_only_listed_concepts_and_graphs_from_the_model():
    from services import upload_suggest as us
    cands = [{"id": "concept:a", "label": "A", "found_by": "full name"}, {"id": "concept:b", "label": "B", "found_by": "a one-word name only"}]
    graphs = [{"id": "g-1", "name": "One", "concepts": {"concept:a"}, "inputs": ["x"]}]
    kinds = ["report", "rca", "other"]
    ask = lambda reply: us.confirm(lambda *a: reply, "f.md", "T", "text", cands, graphs, kinds, lambda c: c, reply)  # noqa: E731
    good = ask('{"kind": "rca", "concepts": ["concept:a", "concept:zzz"], "graph": "g-1", "reason": "same subject"}')
    assert good["concepts"] == ["concept:a"] and good["graph"] == "g-1" and good["kind"] == "rca"  # an unlisted concept is dropped
    assert ask('{"kind": "rca", "concepts": [], "graph": "g-999"}') is None  # a graph not in the list: the code result stands
    assert ask('{"kind": "made_up", "concepts": [], "graph": "new"}') is None
    assert ask('{"kind": "other", "label": "", "concepts": [], "graph": "new"}') is None
    assert ask("not json") is None
    assert us.confirm(None, "f.md", "T", "text", cands, graphs, kinds, lambda c: c, "k") is None  # no model: the code result stands


def test_the_form_suggestion_says_whether_the_model_or_code_decided(mesh):
    client = TestClient(app)
    files = {"file": ("plan.md", b"# Solar inverter plan\n\nEach rooftop inverter is cleaned every quarter and its fan checked every month.", "text/markdown")}
    s = client.post("/api/v1/mesh/uploads/suggest", files=files, headers=ADMIN).json()
    assert s["decided_by"] in ("model", "code") and isinstance(s["candidates"], list) and s["graph"]["mode"] == "new"


def test_the_form_reads_a_file_under_the_rule_of_its_item_and_as_restricted_without_one(mesh, monkeypatch):
    from services import uploads
    bound = []
    monkeypatch.setattr(uploads, "_kind_caller", lambda rt, sensitivity: bound.append(sensitivity))  # gives None: no model call
    data = b"# Solar inverter plan\n\nEach rooftop inverter is cleaned every quarter and its fan checked every month."
    for node, code in (("ceat", "E-03"), ("ceat", "new"), (None, None)):
        assert uploads.suggest(mesh, "plan.md", data, node, code)["decided_by"] == "code"
    assert bound == [uploads.datapoints_of("ceat")["E-03"]["sensitivity"], "Restricted", "Restricted"]  # a new item, and none chosen


def test_the_last_complete_answer_of_the_model_counts():
    from services.upload_suggest import last_json_object
    corrected = '{"kind": "other", "concepts": ["a", "b"]}\n\nWait, b is wrong.\n\n{"kind": "other", "concepts": ["a"]}'
    assert last_json_object(corrected) == {"kind": "other", "concepts": ["a"]}
    assert last_json_object('Here it is: {"kind": "rca", "graph": "new"} as asked.') == {"kind": "rca", "graph": "new"}
    assert last_json_object('{"kind": "rca", "label": "') is None


def first_std(client, graph_id):
    got = client.get(f"/api/v1/mesh/uploads/json-templates?graph_id={graph_id}", headers=ADMIN).json()
    return {"own": got["own"], "can_change": got["can_change"]}


def test_the_standard_output_keeps_every_key_and_is_a_whole_graph(mesh, monkeypatch):
    """One structure for every graph: a value the graph does not have is null, an empty list is [], and an edge whose end
    is not among the nodes brings that end in as a node of type Unknown."""
    from services import json_templates as jt, uploads
    view = {"id": "g-x", "name": "Thin graph", "documents": [],
            "nodes": [{"id": "c:1", "type": "Concept", "label": "Raw material storage"}, {"id": "c:2", "type": "Concept", "label": "", "subsidiary": "ceat"}],
            "edges": [{"id": "e1", "type": "RELATED_TO", "source": "c:1", "target": "c:gone", "status": "approved"},
                      {"id": "e2", "type": "RELATED_TO", "source": "c:gone", "target": "c:2"}]}
    monkeypatch.setattr(uploads, "context_graph_view", lambda *a, **k: view)
    out = jt.render(jt.DEFAULT, jt.data_of(None, "g-x", "ceat", []))
    assert list(out) == ["graph", "companies", "documents", "nodes", "edges"] and out["documents"] == [] and out["companies"] == []
    keys = set(jt.DEFAULT["nodes"][0]) - {"$each"}
    assert all(set(n) == keys for n in out["nodes"])
    assert out["nodes"] == [{"id": "c:1", "type": "Concept", "name": "Raw material storage", "company": None},
                            {"id": "c:2", "type": "Concept", "name": None, "company": "CEAT"},
                            {"id": "c:gone", "type": "Unknown", "name": None, "company": None}]
    ids = {n["id"] for n in out["nodes"]}
    assert all(e["source"] in ids and e["target"] in ids for e in out["edges"])
    assert out["edges"][0]["to"] is None and out["edges"][1]["from"] is None and out["edges"][1]["status"] is None and out["edges"][1]["to"] is None
    view["edges"] = []
    assert jt.render(jt.DEFAULT, jt.data_of(None, "g-x", "ceat", []))["edges"] == []


def test_a_json_template_is_checked_and_filled_from_the_graph(mesh, monkeypatch, tmp_path):
    from services import json_templates as jt
    monkeypatch.setenv("NEURALMESH_JSON_TEMPLATES", str(tmp_path / "templates"))
    assert jt.check(jt.DEFAULT) == []
    bad = {"graph": "{graph.nam}", "docs": {"$each": "documents", "t": "{title}"}, "items": {"$each": "document", "x": "{titel}", "inner": {"$each": "concept"}}}
    problems = jt.check(bad)
    assert any("{graph.nam} is not a field" in p for p in problems) and any('"documents" is not a list' in p for p in problems)
    assert any("items.x: {titel} is not a field of a document" in p for p in problems) and any('inside another "$each"' in p for p in problems)
    client = TestClient(app)
    text = "Natural rubber lots are kept off the floor and used first in, first out. A lot stored for more than ninety days is checked. " * 3
    graph_id = _upload(client, text).json()["context_graph"]["id"]
    out = client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id, "template": jt.DEFAULT}, headers=ADMIN)
    assert out.status_code == 200, out.text
    o = out.json()["output"]
    assert o["graph"] == "Storage note from the plant" and o["companies"] == ["CEAT"] and isinstance(o["documents"], list)
    doc = o["documents"][0]
    assert doc["title"] == "Storage note from the plant" and doc["company"] == "CEAT" and doc["sharing"] == "Summary leaves CEAT" and doc["kind"] == "Note"
    # the suggested template carries the graph itself: every node with its id and type, every edge between two of those ids
    ids = {n["id"] for n in o["nodes"]}
    assert {"Document", "Concept"} <= {n["type"] for n in o["nodes"]} and all(n["name"] for n in o["nodes"])
    assert o["edges"] and all(e["source"] in ids and e["target"] in ids and e["from"] and e["to"] for e in o["edges"])
    old = {"concepts": {"$each": "concept", "name": "{label}"}, "links": {"$each": "link", "to": "{target_label}"}}  # earlier templates still work
    was = client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id, "template": old}, headers=ADMIN).json()["output"]
    assert was["concepts"] and len(was["links"]) == len(o["edges"])
    small = {"name": "{graph.name}", "rows": {"$each": "document", "line": "{title} by {company}"}}
    assert client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id, "template": small}, headers=ADMIN).json()["output"] == \
        {"name": "Storage note from the plant", "rows": [{"line": "Storage note from the plant by CEAT"}]}
    refused = client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id, "template": bad}, headers=ADMIN)
    assert refused.status_code == 422
    # another company gets a summary item's document with its summary, as on the page
    as_kec = client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id, "template": jt.DEFAULT}, headers=_headers("kec"))
    assert as_kec.status_code == 200 and as_kec.json()["output"]["documents"][0]["sharing"] == "Summary leaves CEAT"
    # a never-leave document of another company is not in the output: its graph is not shown at all
    secret = _upload(client, text.replace("Natural rubber", "Tread compound"), datapoint="E-01", title="Compound note", graph_name="Compound graph").json()["context_graph"]["id"]
    assert client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": secret, "template": jt.DEFAULT}, headers=_headers("kec")).status_code == 404
    assert client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": secret, "template": jt.DEFAULT}, headers=ADMIN).status_code == 200
    # the standard structure for every graph: a template of its own is refused, with the upload and by itself, and nothing is kept
    import json as _json
    assert first_std(client, graph_id) == {"own": False, "can_change": False}
    assert client.put(f"/api/v1/mesh/uploads/graphs/{graph_id}/template", json={"template": small}, headers=ADMIN).status_code == 422
    held = len(client.get("/api/v1/mesh/uploads", headers=ADMIN).json()["uploads"])
    no = _upload(client, text, title="Second note", graph_id=graph_id, output_template=_json.dumps(small))
    assert no.status_code == 422 and "standard structure" in no.json()["detail"]
    assert len(client.get("/api/v1/mesh/uploads", headers=ADMIN).json()["uploads"]) == held
    assert "nodes" in client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id}, headers=ADMIN).json()["output"]
    # kept and switched off: a template of its own for each context graph. With the switch on, every later output of
    # that graph follows it, for everyone who may see the graph
    monkeypatch.setenv("NEURALMESH_TEMPLATE_PER_GRAPH", "1")
    first = client.get(f"/api/v1/mesh/uploads/json-templates?graph_id={graph_id}", headers=_headers("kec")).json()
    assert first["own"] is False and first["template"] == jt.DEFAULT and "node" in first["fields"]
    put = f"/api/v1/mesh/uploads/graphs/{graph_id}/template"
    assert client.put(put, json={"template": bad}, headers=ADMIN).status_code == 422
    assert client.put(put, json={"template": small}, headers=_headers("ceat")).status_code == 403
    assert client.put(f"/api/v1/mesh/uploads/graphs/{secret}/template", json={"template": small}, headers=_headers("kec")).status_code in (403, 404)
    assert client.put(put, json={"template": small}, headers=ADMIN).json() == {"template": small, "own": True}
    kept = client.get(f"/api/v1/mesh/uploads/json-templates?graph_id={graph_id}", headers=_headers("kec")).json()
    assert kept["own"] is True and kept["template"] == small and kept["suggested"] == jt.DEFAULT
    assert client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id}, headers=_headers("kec")).json()["output"] == \
        {"name": "Storage note from the plant", "rows": [{"line": "Storage note from the plant by CEAT"}]}
    # another graph is not touched, and a graph not shown gives nothing
    assert "nodes" in client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": secret}, headers=ADMIN).json()["output"]
    assert client.get(f"/api/v1/mesh/uploads/json-templates?graph_id={secret}", headers=_headers("kec")).status_code == 404
    # the suggested template put back: the graph has none of its own again
    assert client.put(put, json={"template": jt.DEFAULT}, headers=ADMIN).json()["own"] is False
    assert "nodes" in client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id}, headers=ADMIN).json()["output"]
    assert not list((tmp_path / "templates").glob("*.json"))
    # the template can come with the upload: checked before anything is kept, then kept with the graph of that upload
    before = len(client.get("/api/v1/mesh/uploads", headers=ADMIN).json()["uploads"])
    refused = _upload(client, text, title="Second note", graph_id=graph_id, output_template=_json.dumps(bad))
    assert refused.status_code == 422 and "nothing was kept" in refused.json()["detail"]
    assert _upload(client, text, title="Second note", graph_id=graph_id, output_template="{not json").status_code == 422
    assert len(client.get("/api/v1/mesh/uploads", headers=ADMIN).json()["uploads"]) == before
    assert _upload(client, text.replace("ninety", "sixty"), title="Second note", graph_id=graph_id, output_template=_json.dumps(small)).status_code == 201
    again = client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id}, headers=ADMIN).json()["output"]
    assert again["name"] == "Storage note from the plant" and len(again["rows"]) == 2
    # a later upload without a template leaves the template of the graph as it is
    assert _upload(client, text.replace("ninety", "thirty"), title="Third note", graph_id=graph_id).status_code == 201
    assert client.get(f"/api/v1/mesh/uploads/json-templates?graph_id={graph_id}", headers=ADMIN).json()["own"] is True
