"""Entities and links taken from the text of an upload: code links known concepts named in one sentence, the model adds
entities only where the text holds them, every link starts proposed and keeps its decision, the view shows them by the
rule for the text, and the quality notes of a context graph name what to look at."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from api.main import app
from services import context_graph_ingest as ingested
from services import graph_extract
from tests.test_uploads import ADMIN, DATA, _headers, _upload, mesh  # noqa: F401 - mesh is the fixture


def _concepts(rt, n=2):
    return [d["label"] for _, d in rt.mesh.graph.nodes(data=True) if d.get("type") == "Concept" and d.get("label") and len(d["label"]) > 4][:n]


def _clean():
    for node in ("ceat", "others"):
        for path in (DATA / node / graph_extract.FOLDER).glob("*.json"):
            path.unlink()


def test_two_known_concepts_in_one_sentence_become_a_proposed_link_shown_and_decided(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    text = f"Our plant checks {a} together with {b} at every receipt. The rest of this note is about storage and first in, first out issue."
    up = _upload(client, text, graph_name="Extraction check", datapoint="E-02")
    assert up.status_code == 201, up.text
    body = up.json()
    assert body["extraction"]["links"] == 1 and body["extraction"]["proposed"] == 1 and body["extraction"]["model"] == "no model"
    doc_id, graph_id = body["document"]["id"], body["context_graph"]["id"]
    kept = graph_extract.read(doc_id)
    link = kept["links"][0]
    assert link["type"] == "RELATED_TO" and link["by"] == "code" and link["status"] == "proposed" and a in link["evidence"]
    # the view shows the link, proposed, with its evidence, and the quality notes say it waits for review
    view = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=ADMIN).json()
    edge = next(e for e in view["edges"] if e["id"] == link["id"])
    assert edge["status"] == "proposed" and edge["document"] == doc_id and edge["evidence"] == link["evidence"]
    assert edge["priority"] == "low"  # a link between two topics: no person is asked, it stays proposed
    assert any("1 link of low priority is kept as proposed without asking anyone" in q["text"] for q in view["quality"])
    # another company may not decide, the owning company and a mesh admin may
    url = f"/api/v1/mesh/uploads/{doc_id}/links/{link['id']}"
    assert client.post(url, json={"status": "approved"}, headers=_headers("kec")).status_code == 403
    assert client.post(url, json={"status": "maybe"}, headers=ADMIN).status_code == 422
    decided = client.post(url, json={"status": "approved"}, headers=_headers("ceat"))
    assert decided.status_code == 200 and decided.json()["status"] == "approved" and decided.json()["decided"]["by_company"] == "ceat"
    # a second extraction keeps the decision
    from services import uploads
    graph_extract.extract(mesh, "ceat", uploads.record_of("ceat", doc_id))
    assert graph_extract.read(doc_id)["links"][0]["status"] == "approved"
    # a rejected link leaves the view
    client.post(url, json={"status": "rejected"}, headers=ADMIN)
    view = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=ADMIN).json()
    assert all(e["id"] != link["id"] for e in view["edges"])
    # the JSON download carries the approved link as an edge
    client.post(url, json={"status": "approved"}, headers=ADMIN)
    made = client.post("/api/v1/mesh/uploads/json-templates/render", json={"graph_id": graph_id}, headers=ADMIN).json()["output"]
    assert any(e["id"] == link["id"] and e["status"] == "approved" for e in made["edges"])


def test_the_text_of_a_summary_item_gives_its_links_to_its_own_company_only(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"The team reviews {a} and {b} in one meeting each month, and records the outcome.", graph_name="Summary item links", datapoint="E-02").json()
    graph_id = up["context_graph"]["id"]  # E-02 of CEAT gives its summary only to the other companies
    own = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=_headers("ceat")).json()
    other = client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=_headers("kec"))
    assert any(e.get("by") for e in own["edges"])
    assert other.status_code == 404 or not any(e.get("by") for e in other.json()["edges"])


def test_the_model_part_keeps_only_what_the_text_holds(mesh):
    _clean()
    a = _concepts(mesh, 1)[0]
    text = f"Mixer M-01 uses the rotor seal RS-200. The seal RS-200 wears near {a} after six months."
    reply = {"entities": [{"name": "RS-200", "type": "part"}, {"name": "Mixer M-01", "type": "Machine"}, {"name": "Turbine T-9", "type": "Machine"},
                          {"name": a, "type": "Concept"}],
             "links": [{"source": "Mixer M-01", "relation": "uses part", "target": "RS-200", "evidence": "Mixer M-01 uses the rotor seal RS-200."},
                       {"source": "RS-200", "relation": "WEARS_NEAR", "target": a, "evidence": f"The seal RS-200 wears near {a} after six months."},
                       {"source": "Turbine T-9", "relation": "DRIVES", "target": "RS-200", "evidence": "Turbine T-9 drives RS-200."},
                       {"source": "Mixer M-01", "relation": "FEEDS", "target": "RS-200", "evidence": "Mixer M-01 feeds RS-200 every day."}]}
    calls = []
    record = {"document": {"id": "ceat:E-03-U900", "body": text, "concepts": [next(n for n, d in mesh.mesh.graph.nodes(data=True) if d.get("label") == a)]}}
    out = graph_extract.extract(mesh, "ceat", record, lambda *args: calls.append(args) or json.dumps(reply))
    assert calls and calls[0][0] == "extract" and calls[0][3] == "mesh_extract_v3"
    names = {e["name"]: e for e in out["entities"]}
    assert set(names) == {"RS-200", "Mixer M-01"} and names["RS-200"]["type"] == "Part" and names["Mixer M-01"]["type"] == "Asset" and names["RS-200"]["id"] == "entity:ceat:rs-200"
    kinds = {(link["type"], link["by"]) for link in out["links"]}
    assert ("USES", "model") in kinds  # "uses part" is read as the listed relation USES
    assert not any(link["type"] == "WEARS_NEAR" for link in out["links"])  # a relation outside the list is left out
    assert not any(link["type"] in ("DRIVES", "FEEDS") for link in out["links"])  # not in the text, or evidence not in the text
    assert all(link["status"] == "proposed" for link in out["links"]) and out["model"] == "made"
    # a reply that is not JSON leaves the code part only
    bad = graph_extract.extract(mesh, "ceat", record, lambda *args: "no idea")
    assert bad["entities"] == [] and all(link["by"] == "code" for link in bad["links"])


def test_quality_notes_name_an_input_with_no_concept_and_a_repeated_file(mesh):
    _clean()
    client = TestClient(app)
    first = _upload(client, "Zorbly quint flaxen tessellate wobbling yurt, and more zorbly quint words that name nothing known.",
                    graph_name="Quality check", tags="", datapoint="E-02").json()
    graph_id = first["context_graph"]["id"]
    _upload(client, "Zorbly quint flaxen tessellate wobbling yurt, and more zorbly quint words that name nothing known.", title="Copy", graph_id=graph_id, tags="", datapoint="E-02")
    texts = [q["text"] for q in client.get(f"/api/v1/mesh/uploads/graphs/{graph_id}", headers=ADMIN).json()["quality"]]
    assert any(t.startswith("2 inputs link to no known concept") for t in texts), texts
    assert any("are the same file" in t for t in texts), texts


def test_quality_of_an_ingested_graph():
    record = {"nodes": [{"id": "a", "type": "Part", "name": "Seal"}, {"id": "b", "type": "Part", "name": "seal"}, {"id": "c", "type": "Machine", "name": "Mixer"},
                        {"id": "d", "type": "Unknown", "name": "d"}, {"id": "e", "type": "Site", "name": "Plant"}, {"id": "f", "type": "Site", "name": "Store"}],
              "edges": [{"source": "a", "target": "c"}, {"source": "d", "target": "c"}, {"source": "e", "target": "f"}]}
    texts = [q["text"] for q in ingested.quality(record)]
    assert texts[0] == '1 node has no edge: "seal"' and 'Part "seal"' in texts[1] and "1 node is of type Unknown" in texts[2] and "2 separate parts" in texts[3]
    whole = {"nodes": record["nodes"][:3], "edges": [{"source": "a", "target": "c"}, {"source": "b", "target": "c"}]}
    whole["nodes"][1] = {"id": "b", "type": "Part", "name": "Gasket"}
    assert ingested.quality(whole)[0]["level"] == "ok"


def test_extraction_of_existing_inputs_writes_nothing_without_write(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    doc_id = _upload(client, f"{a} and {b} are checked in the same sentence here, for the dry run.", graph_name="Dry run", datapoint="E-02").json()["document"]["id"]
    (DATA / "ceat" / graph_extract.FOLDER / f"{doc_id.split(':')[1]}.json").unlink()  # as if it was uploaded before the step existed
    assert client.post("/api/v1/mesh/uploads/extractions", headers=_headers("ceat")).status_code == 403
    dry = client.post("/api/v1/mesh/uploads/extractions", headers=ADMIN).json()
    row = next(d for d in dry["documents"] if d["document"] == doc_id)
    assert dry["written"] is False and row["links"] == 1 and graph_extract.read(doc_id) is None
    wet = client.post("/api/v1/mesh/uploads/extractions?write=true", headers=ADMIN).json()
    assert any(d["document"] == doc_id for d in wet["documents"]) and graph_extract.read(doc_id)["links"][0]["status"] == "proposed"


def test_the_model_reads_the_whole_of_a_long_text_in_parts_that_cut_no_sentence(mesh):
    line = "The mixer M-07 uses the rotor seal RS-200 on the second shift of every week. "
    text = (line * 30 + "\n") * 9  # about 21,000 characters
    parts = graph_extract._parts(text)
    assert len(parts) == 4 and "".join(parts) == text and all(len(p) <= graph_extract.MODEL_TEXT_CHARS for p in parts)
    assert all(p.endswith(("\n", ". ")) for p in parts[:-1])
    seen = []
    reply = json.dumps({"entities": [{"name": "mixer M-07", "type": "Machine"}, {"name": "rotor seal RS-200", "type": "Part"}],
                        "links": [{"source": "mixer M-07", "relation": "USES_PART", "target": "rotor seal RS-200", "evidence": line.strip()}]})
    record = {"document": {"id": "ceat:E-03-U901", "body": text, "concepts": []}}
    out = graph_extract.extract(mesh, "ceat", record, lambda step, system, user, version: seen.append(user) or reply)
    assert len(seen) == 4 and out["model"] == "made, 4 of 4 parts read"
    assert [(link["type"], link["by"]) for link in out["links"] if link["by"] == "model"] == [("USES", "model")]  # the same link from four parts is kept once
    assert len(graph_extract._parts("x" * (graph_extract.MODEL_PARTS * graph_extract.MODEL_TEXT_CHARS + 5))) == graph_extract.MODEL_PARTS
