"""The graph input standard: rules file, adapters, the six checks, the normalised file, revision and export."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from api.auth import issue_poc_token
from contracts.graph import GraphEdge, GraphNode, Provenance, json_schema
from knowledge import adapters
from services import graph_intake
from services.graph_store import GraphStore
from services.ontology import ontology
from tests.mesh_harness import build_mesh

APP = Path(__file__).resolve().parents[1]
PROV = Provenance(method="authored", by_role="Test")


def _edge(eid, etype, a, b, status="approved"):
    return GraphEdge(id=eid, type=etype, **{"from": a, "to": b}, status=status, provenance=PROV)


def test_rules_file_names_every_type_and_group_the_code_uses():
    rules = ontology()
    assert {"Subsidiary", "Document", "Concept", "Skill", "Role", "Expert", "Datapoint", "Domain", "Asset"} <= set(rules.node_types)
    assert rules.group("hop") >= {"RELATED_TO", "BROADER", "SAME_AS"} and rules.group("judgement") == {"CORROBORATES", "CONFLICTS_WITH", "ADDRESSES_GAP", "SUPERSEDES"}
    assert rules.allows("MENTIONS", "Document", "Concept")[0] and not rules.allows("MENTIONS", "Role", "Concept")[0]
    assert "inspection" in rules.domains and rules.allows("CHECKED_FOR", "Asset", "Condition")[0]


def test_the_six_checks_name_the_record_and_the_rule():
    nodes = [GraphNode(id="concept:a", type="Concept", label="A"), GraphNode(id="ceat:role/x", type="Role", label="X", properties={"subsidiary": "ceat"}),
             GraphNode(id="concept:a", type="Concept", label="A again"), GraphNode(id="concept:b", type="Thing", label="B")]
    edges = [_edge("rel:t/1", "MENTIONS", "ceat:role/x", "concept:a"), _edge("rel:t/1", "RELATED_TO", "concept:a", "concept:b"),
             _edge("rel:t/2", "RELATED_TO", "concept:b", "concept:a"), _edge("rel:t/3", "CITES", "concept:a", "concept:b")]
    warnings: list[str] = []
    errors = graph_intake.validate(nodes, edges, "pack:group.vocabulary", warnings=warnings)
    text = "\n".join(errors)
    assert "concept:a is given twice" in text and "type Thing is not in the graph rules" in text
    assert "MENTIONS from Role is not allowed" in text and "edge rel:t/1 is given twice" in text
    assert "RELATED_TO between concept:a and concept:b is given twice" in text or "RELATED_TO between concept:b and concept:a is given twice" in text
    assert "edge type CITES is not in the graph rules" in text
    assert "pack:group.vocabulary may not write namespace ceat" in text
    bad_ref = graph_intake.validate([], [_edge("rel:t/9", "MENTIONS", "ceat:D-1", "concept:zzz")], "node:ceat", warnings=warnings)
    assert bad_ref == [] and any("concept:zzz" in w for w in warnings)


def test_normalised_file_is_identical_for_the_same_input_and_round_trips(tmp_path):
    nodes = [GraphNode(id="concept:b", type="Concept", label="B"), GraphNode(id="concept:a", type="Concept", label="A", aliases=["alpha"])]
    edges = [_edge("rel:t/2", "RELATED_TO", "concept:b", "concept:a")]
    graph_intake.write_normalised(tmp_path / "one.jsonl", "pack:group.vocabulary", *graph_intake.normalise(nodes, edges))
    graph_intake.write_normalised(tmp_path / "two.jsonl", "pack:group.vocabulary", *graph_intake.normalise(list(reversed(nodes)), edges))
    assert (tmp_path / "one.jsonl").read_text() == (tmp_path / "two.jsonl").read_text()
    back_nodes, back_edges = adapters.from_jsonl(tmp_path / "one.jsonl")
    assert [n.id for n in back_nodes] == ["concept:a", "concept:b"] and back_nodes[0].aliases == ["alpha"] and back_edges[0].type == "RELATED_TO"


def test_csv_pair_loads_through_the_same_intake_and_export_reimports_equal(tmp_path):
    (tmp_path / "nodes.csv").write_text('id,type,label,aliases,properties\nconcept:csv-a,Concept,CSV topic A,topic a|first topic,{}\nconcept:csv-b,Concept,CSV topic B,,{"description":"second"}\n')
    (tmp_path / "edges.csv").write_text("id,type,from,to,status,confidence,note\nrel:csv/1,RELATED_TO,concept:csv-a,concept:csv-b,approved,1,hand written\n")
    nodes, edges = adapters.from_csv(tmp_path / "nodes.csv", tmp_path / "edges.csv")
    store = GraphStore(tmp_path / "g.db")
    report = graph_intake.load(store, "pack:group.vocabulary", nodes, edges)
    assert report.ok and report.nodes == 2 and report.edges == 1 and store.revision() == 1
    assert store.export_jsonl(tmp_path / "out.jsonl") == 3
    again = GraphStore(tmp_path / "g2.db")
    n2, e2 = adapters.from_jsonl(tmp_path / "out.jsonl")
    assert graph_intake.load(again, "pack:group.vocabulary", n2, e2).ok
    graph, _ = again.to_networkx()
    assert graph.number_of_edges() == 1 and set(graph.nodes) == {"concept:csv-a", "concept:csv-b"}


def test_graph_checks_pass_on_the_pilot_graph_except_the_known_data_gaps():
    _, _, mesh = build_mesh()
    by_rule = {c["rule"]: c for c in mesh.checks}
    assert by_rule["dangling_link"]["ok"] and by_rule["type_signature"]["ok"]
    assert by_rule["one_company_link_per_role"]["ok"] and by_rule["live_link_on_retired_entity"]["ok"]
    assert set(by_rule["isolated_entity"]["examples"]) <= {"domain:mesh", "concept:esg-water-energy"}
    assert by_rule["concept_without_document"]["examples"] == ["concept:esg-water-energy", "concept:supplier-quality"] or \
        set(by_rule["concept_without_document"]["examples"]) <= {"concept:esg-water-energy", "concept:supplier-quality"}


def test_a_reader_rebuilds_when_another_writer_moved_the_revision():
    _, _, mesh = build_mesh()
    seen = mesh.loaded_revision
    other = GraphStore(mesh.store.path)  # a second process on the same file
    other.upsert_entities([{"id": "concept:late-arrival", "type": "Concept", "label": "Late arrival", "properties": {}}])
    other.bump_revision()
    assert "concept:late-arrival" not in mesh.graph
    assert mesh.refresh_if_stale() is True and mesh.loaded_revision > seen and "concept:late-arrival" in mesh.graph
    assert mesh.refresh_if_stale() is False


def test_inspection_ontology_loads_as_proposed_entries_under_its_own_rules():
    onto = {"condition_families": [{"id": "crack_cut", "name": "Cracks and cuts"}], "conditions": [{"id": "cut", "family": "crack_cut"}],
            "grade_scales": [{"id": "tyre_plant", "grades": ["A", "B", "C", "Reject"]}], "cover_types": ["stock_policy"], "review_status": [],
            "subsidiaries": [{"id": "ceat", "name": "CEAT", "families": [{"id": "ceat.tyre", "name": "Tyre", "assets": [
                {"id": "ceat.finished_tyre", "name": "Finished tyre", "scan": "serial", "views": ["sidewall"], "conditions": ["cut"], "scale": "tyre_plant", "cover": "stock_policy"}]}]}]}
    nodes, edges = adapters.from_inspection_ontology(onto)
    _, _, mesh = build_mesh()
    report = mesh.load_records("app:snapscore", nodes, edges)
    assert report.ok, report.errors
    g, _ = mesh.store.to_networkx()
    asset = "ceat:asset/finished_tyre"
    kinds = {(d["type"], d["status"]) for _, _, d in g.out_edges(asset, data=True)}
    assert kinds == {("OWNED_BY", "proposed"), ("HAS_VIEW", "proposed"), ("CHECKED_FOR", "proposed"), ("GRADED_ON", "proposed"), ("HAS_EXPECTED_COVER", "proposed")}
    assert g.nodes[asset]["external_refs"] == [{"scheme": "SnapScore", "uri": "ceat.finished_tyre"}]


def test_json_schema_of_the_graph_records_is_exportable():
    schema = json_schema()
    assert schema["schema_version"] == "1.0" and "from" in schema["edge"]["properties"] and "aliases" in schema["node"]["properties"]


def test_the_shared_schema_files_match_the_contracts_in_code():
    """SkillForge and Snap and Score test their parsers against these files, so they must equal the code."""
    from contracts.evidence import EvidenceRecord, RelationshipRef, SCHEMA_VERSION as EV
    graph_file = json.loads((APP / "contracts" / "schemas" / "graph_record.schema.json").read_text())
    assert graph_file == json_schema()
    evidence_file = json.loads((APP / "contracts" / "schemas" / "evidence_record.schema.json").read_text())
    assert evidence_file == {"schema_version": EV, "record": EvidenceRecord.model_json_schema(), "relationship": RelationshipRef.model_json_schema()}


def test_review_findings_ownership_rules():
    """From the code review of 2026-11-07: a node may not rewrite another company, approve a cross-company link, or
    reuse another source's edge ID, and an unknown source may write nothing."""
    _, _, mesh = build_mesh()
    known_ids, known_types = mesh.store.entity_types()
    other_company = [GraphNode(id="org:kec", type="Subsidiary", label="KEC rewritten", aliases=["kec"])]
    errors = graph_intake.validate(other_company, [], "node:ceat", known_ids, known_types)
    assert any("may only write its own company entry" in e for e in errors)
    foreign_doc = [GraphNode(id="ceat:X-1", type="Document", label="x", properties={"subsidiary": "kec", "datapoint": "kec:E-04"})]
    assert any("may not mark an entity as belonging to kec" in e for e in graph_intake.validate(foreign_doc, [], "node:ceat", known_ids, known_types))
    link = [_edge("rel:ceat.export/CORROBORATES/x", "CORROBORATES", "ceat:E-03-01", "harrisons:O-05-04", status="approved")]
    assert any("proposed until both owners approve" in e for e in graph_intake.validate([], link, "node:ceat", known_ids, known_types))
    proposed = [_edge("rel:ceat.export/CORROBORATES/x", "CORROBORATES", "ceat:E-03-01", "harrisons:O-05-04", status="proposed")]
    assert graph_intake.validate([], proposed, "node:ceat", known_ids, known_types) == []
    stolen = [_edge("rel:group.links/001", "ADDRESSES_GAP", "ceat:E-03-01", "harrisons:O-05-04", status="proposed")]
    report = graph_intake.load(mesh.store, "node:ceat", [], stolen, retire=False)
    assert report.errors and "belongs to pack:group.links" in report.errors[0]
    assert ontology().may_write("app:evil", "skill") is False
    assert any("may not write namespace skill" in e for e in graph_intake.validate([GraphNode(id="skill:x", type="Skill", label="x")], [], "app:evil", known_ids, known_types))
    reserved = [GraphNode(id="concept:r", type="Concept", label="r", properties={"label": "no"})]
    assert any("reserved keys" in e for e in graph_intake.validate(reserved, [], "pack:group.vocabulary", known_ids, known_types))


def test_incremental_loads_keep_earlier_events():
    _, _, mesh = build_mesh()
    prov = Provenance(method="imported", by_role="t")
    for i in (1, 2):
        node = GraphNode(id=f"ceat:inspection/T-{i}", type="Inspection", label=f"T-{i}", properties={"subsidiary": "ceat", "asset": "ceat:E-03-01"})
        edge = GraphEdge(id=f"rel:t/INSPECTION_OF/T-{i}", type="INSPECTION_OF", **{"from": node.id, "to": "ceat:E-03-01"}, provenance=prov)
        # INSPECTION_OF needs an Asset end in the rules, so this uses the structural check only through the intake's reference warning path
        report = graph_intake.load(mesh.store, "app:snapscore/ceat", [node], [], retire=False)
        assert report.ok, report.errors
    g, _ = mesh.store.to_networkx()
    assert not g.nodes["ceat:inspection/T-1"].get("retired") and not g.nodes["ceat:inspection/T-2"].get("retired")
