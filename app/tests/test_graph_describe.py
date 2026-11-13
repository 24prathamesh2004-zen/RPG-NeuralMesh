"""What the lead's review of the graph view asked for: a link carries the relation its sentence states, a person is asked
only about a link the text does not settle, two inputs that share topics are linked, every graph has a description that
a person may write, an input that does not match its graph is listed until a person keeps it, the graph API reads and
queries a graph made by Upload input, and a question finds the graphs it is about."""
from __future__ import annotations

import json
import re

from fastapi.testclient import TestClient

from api.main import app
from services import graph_describe, graph_extract, uploads
from tests.test_graph_extract import _clean, _concepts
from tests.test_uploads import ADMIN, DATA, _headers, _upload, mesh  # noqa: F401 - mesh is the fixture

GRAPHS = "/api/v1/mesh/uploads/graphs"


def _router(monkeypatch, pick=None, intent="clear", suggestions=(), seen=None):
    """The model of the choose step, as a test stand-in: it picks the listed graph named ``pick``."""
    def model(step, system, user, version=None):
        if seen is not None:
            seen.append(user)
        names = {line.split(": ", 1)[1]: line.split(":", 1)[0] for line in user.splitlines() if re.match(r"^G\d+: ", line)}
        question = user.split("\n", 1)[0].removeprefix("Question: ")
        return json.dumps({"intent": intent, "understood_as": question, "graphs": [names[pick]] if pick in names else [],
                           "suggestions": list(suggestions), "reason": f"about {pick}"})
    monkeypatch.setattr(graph_describe, "model_caller", lambda backend, app_env: model)


def _view(client, graph_id, headers=ADMIN):
    return client.get(f"{GRAPHS}/{graph_id}", headers=headers).json()


def test_a_link_carries_the_relation_of_its_sentence_and_only_an_unclear_link_waits_for_a_person(mesh):
    _clean()
    client = TestClient(app)
    a, b, c, d = _concepts(mesh, 4)
    text = (f"The plan says that {a} depends on {b} for every release. A second point is that {c} came up once with {a} in the review. "
            f"The team named {b} and {d} in the opening. The team named {b} and {d} again at the close of the meeting.")
    up = _upload(client, text, graph_name="Relations check", datapoint="E-02").json()
    assert up["extraction"]["links"] >= 3 and up["extraction"]["proposed"] >= 1
    view = _view(client, up["context_graph"]["id"])
    label = {n["id"]: n["label"] for n in view["nodes"]}
    found = {(label[e["source"]], e["type"], label[e["target"]]): e for e in view["edges"] if e.get("by") == "code"}
    named = found[(a, "DEPENDS_ON", b)]
    assert named["status"] == "approved" and named["settled_by"] == "rule" and named["settled_reason"] == "relation" and "depends on" in named["evidence"]
    twice = next(e for k, e in found.items() if set(k[::2]) == {b, d})
    assert twice["type"] == "RELATED_TO" and twice["status"] == "approved" and twice["settled_reason"] == "repeated" and twice["sentences"] == 2
    once = next(e for k, e in found.items() if set(k[::2]) == {a, c})
    assert once["type"] == "RELATED_TO" and once["status"] == "proposed" and "settled_by" not in once
    unsure = sum(1 for e in view["edges"] if e.get("status") == "proposed" and e.get("priority") == "low")
    assert unsure and any(f"{unsure} link" in q["text"] and "without asking anyone" in q["text"] for q in view["quality"])
    # a person's decision stands over the rule
    doc_id = up["document"]["id"]
    client.post(f"/api/v1/mesh/uploads/{doc_id}/links/{named['id']}", json={"status": "rejected"}, headers=ADMIN)
    assert all(e["id"] != named["id"] for e in _view(client, up["context_graph"]["id"])["edges"])
    # a link kept as RELATED_TO before relations were read is named when the graph is read, and keeps its id on a new extraction
    path = DATA / "ceat" / graph_extract.FOLDER / f"{doc_id.split(':')[1]}.json"
    kept = json.loads(path.read_text())
    for link in kept["links"]:
        if link["id"] == named["id"]:
            link.update(type="RELATED_TO", status="proposed", source=min(link["source"], link["target"]), target=max(link["source"], link["target"]))
            link.pop("decided", None)
    path.write_text(json.dumps(kept))
    old = next(e for e in _view(client, up["context_graph"]["id"])["edges"] if e["id"] == named["id"])
    assert old["type"] == "DEPENDS_ON" and label[old["source"]] == a and old["status"] == "approved"
    graph_extract.extract(mesh, "ceat", uploads.record_of("ceat", doc_id))
    again = next(x for x in graph_extract.read(doc_id)["links"] if x["type"] == "DEPENDS_ON")
    assert again["id"] == named["id"]


def test_every_graph_has_a_description_and_a_person_of_the_company_may_write_it(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"A note on {a} and {b} for the storage team, written after the monthly review of the store.", graph_name="Described graph", datapoint="E-02").json()
    graph_id = up["context_graph"]["id"]
    made = _view(client, graph_id)["description"]
    assert made["by"] == "code" and made["can_write"] and made["text"].startswith("1 input from CEAT, kept under the catalogue item ") and a in made["text"] and "Uploaded on" in made["text"]
    url = f"{GRAPHS}/{graph_id}/description"
    assert client.put(url, json={"text": "Too short"}, headers=ADMIN).status_code == 422
    assert client.put(url, json={"text": "What the storage team agreed about rubber lots."}, headers=_headers("kec")).status_code in (403, 404)
    written = client.put(url, json={"text": "What the storage team agreed about   rubber lots and their issue order."}, headers=_headers("ceat"))
    assert written.status_code == 200 and written.json()["description"] == {**written.json()["description"], "by": "person", "text": "What the storage team agreed about rubber lots and their issue order."}
    assert _view(client, graph_id)["description"]["by"] == "person"
    assert client.put(url, json={"text": ""}, headers=ADMIN).json()["description"]["by"] == "code"


def test_two_inputs_that_share_topics_are_linked_and_an_input_that_does_not_match_waits_for_a_person(mesh):
    _clean()
    client = TestClient(app)
    a, b, c = _concepts(mesh, 3)
    first = _upload(client, f"The first meeting covered {a}, then {b}, then {c}, with one owner for each of the three.", graph_name="Meetings", datapoint="E-02").json()
    graph_id = first["context_graph"]["id"]
    second = _upload(client, f"The second meeting came back to {a}, to {b} and to {c}, and closed two of the actions.", title="Second meeting", graph_id=graph_id, datapoint="E-02").json()
    odd = _upload(client, "Zorbly quint flaxen tessellate wobbling yurt, and more zorbly quint words that name nothing known.", title="Odd one", graph_id=graph_id, tags="", datapoint="E-02").json()
    view = _view(client, graph_id)
    link = next(e for e in view["edges"] if e["type"] == "SHARES_TOPICS_WITH")
    assert {link["source"], link["target"]} == {first["document"]["id"], second["document"]["id"]} and link["by"] == "calculated" and link["status"] == "approved"
    assert link["evidence"].startswith("Both name ") and " topics: " in link["evidence"]  # the tags of the upload add topics to the three named
    assert [r["document"] for r in view["review"]] == [odd["document"]["id"]] and "no known topic" in view["review"][0]["reason"]
    assert client.post(f"/api/v1/mesh/uploads/{odd['document']['id']}/keep", headers=_headers("kec")).status_code == 403
    assert client.post(f"/api/v1/mesh/uploads/{odd['document']['id']}/keep", headers=ADMIN).status_code == 200
    assert _view(client, graph_id)["review"] == []


def test_the_graph_api_reads_and_queries_a_graph_made_by_upload_input(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"The release note says that {a} depends on {b}, and nothing else changed this month.", graph_name="API graph", datapoint="E-02").json()
    graph_id = up["context_graph"]["id"]
    base = f"/api/v1/context-graphs/{graph_id}"
    got = client.get(base, headers=ADMIN)
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["graph_id"] == graph_id and body["graph"] == "API graph" and body["description"].startswith("1 input from CEAT")
    assert any(n["name"] == a for n in body["nodes"]) and any(e["type"] == "DEPENDS_ON" for e in body["edges"])
    overview = client.post(f"{base}/query", json={"overview": True}, headers=ADMIN)
    assert overview.status_code == 200 and overview.json()["graph"]["id"] == graph_id
    asked = client.post(f"{base}/query", json={"question": f"What does {a} depend on?"}, headers=ADMIN).json()
    assert any(n["name"] == a for n in asked["nodes"]) and any(e["type"] == "DEPENDS_ON" for e in asked["edges"])
    assert asked["answer"] is None and asked["answer_note"]  # a real upload gets no written answer from a cloud model
    listed = client.get("/api/v1/context-graphs?uploaded=true", headers=ADMIN).json()
    row = next(g for g in listed["uploaded"] if g["id"] == graph_id)
    assert row["endpoints"]["query"] == f"{base}/query" and row["description"].startswith("1 input")
    assert "uploaded" not in client.get("/api/v1/context-graphs", headers=ADMIN).json()
    assert client.get("/api/v1/context-graphs/g-00000000", headers=ADMIN).status_code == 404
    assert client.delete(base, headers=ADMIN).status_code == 404  # an uploaded graph is dropped on its own page, not here
    assert uploads.record_of("ceat", up["document"]["id"])["status"] == "accepted"


def test_a_question_finds_the_graphs_it_is_about(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"Notes of the quarterly budget review, where {a} and {b} were the two open points.", graph_name="Quarterly budget review", datapoint="E-02").json()
    graph_id = up["context_graph"]["id"]
    concept = next(n for n, d in mesh.mesh.graph.nodes(data=True) if d.get("label") == a)
    by_concept = graph_describe.match(mesh, f"What is known about {a}?", {concept}, "zensar", ["group_user", "mesh_admin"], meaning=False)
    assert by_concept[0]["id"] == graph_id and by_concept[0]["matched_on"] == "concepts" and by_concept[0]["shared_concepts"] == [a]
    by_words = graph_describe.match(mesh, "What did the quarterly budget review decide?", set(), "zensar", ["group_user", "mesh_admin"], meaning=False)
    assert by_words[0]["id"] == graph_id and by_words[0]["matched_on"] == "words" and {"quarterly", "budget", "review"} <= set(by_words[0]["shared_words"])
    assert graph_describe.match(mesh, "zorbly quint flaxen", set(), "zensar", ["group_user", "mesh_admin"], meaning=False) == []
    # the graph of an input that never leaves its company is found by that company only
    own = _upload(client, f"Internal plant decision on {a} and the vendor shortlist for the next tender round.", graph_name="Vendor shortlist decision", datapoint="E-01").json()
    for company, seen in (("ceat", True), ("harrisons", False)):
        found = graph_describe.match(mesh, "vendor shortlist decision", {concept}, company, ["group_user"], meaning=False)
        assert any(g["id"] == own["context_graph"]["id"] for g in found) is seen
    routing = client.get("/api/v1/mesh/routing", params={"q": f"What is known about {a}?"}, headers=ADMIN)
    assert routing.status_code == 200


def test_a_catalogue_item_named_at_upload_is_known_to_the_policy_of_its_node(mesh):
    from mcp_nodes.auth import CallerContext
    from mcp_nodes.policy import evaluate_access
    from mcp_nodes.server_config import load_node_config
    from knowledge import packgen
    client = TestClient(app)
    a, b = _concepts(mesh)
    try:
        up = client.post("/api/v1/mesh/uploads", data={"node_id": "ceat", "datapoint": "new", "kind": "note", "new_item_title": "Shift handover notes of the mixing line", "new_item_area": "lessons"},
                         files={"file": ("handover.txt", f"The night shift handed over {a} and {b} with two open actions for the morning.".encode(), "text/plain")}, headers=ADMIN)
        assert up.status_code == 201, up.text
        code = up.json()["new_item"]["code"]
        config = load_node_config("ceat", DATA)
        assert config.datapoints[code]["never_leave"] is True and config.datapoints[code]["ceiling"] == "MD"
        caller = CallerContext("u-ceat", "ceat", frozenset({"group_user"}), "problem_solving")
        title_only = evaluate_access(config, caller, code, "MD")
        assert title_only.code == "ALLOWED" and "Unknown" not in title_only.reason
        text = evaluate_access(config, caller, code, "RAG")
        assert text.code == "BLOCKED_BY_POLICY" and text.reason == "Datapoint is metadata-only"  # the rule of a never-leave item, not an unknown item

    finally:
        for folder in ("contributions", "added_items"):
            for path in (DATA / "ceat" / folder).glob("*.json"):
                path.unlink()
        packgen.rebuild_domain_pack("ceat", "lessons", build_vectors=False)

def test_ask_gets_what_the_matched_graph_holds_about_the_question(mesh, monkeypatch):
    import asyncio
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"Notes of the tender board, where {a} depends on {b} and nothing else was open.", graph_name="Tender board notes", datapoint="E-02").json()
    concept = next(n for n, d in mesh.mesh.graph.nodes(data=True) if d.get("label") == a)
    state = {"question": f"What does {a} depend on in the tender board notes?", "company": "zensar", "roles": ["group_user", "mesh_admin"]}
    _router(monkeypatch, "Tender board notes")
    found, check = mesh.orchestrator._context_graphs(state, [concept])
    assert check["intent"] == "clear" and found[0]["chosen"] and found[0]["chosen_by"] == "model"
    assert found[0]["id"] == up["context_graph"]["id"] and a in found[0]["found"]["nodes"]
    assert {"source": a, "type": "DEPENDS_ON", "target": b} in found[0]["found"]["links"]
    routed = asyncio.run(mesh.orchestrator.route({**state, "resolved": {"concepts": {}, "named_subsidiaries": []}}))["routing"]
    assert routed["method"] == "context_graph" and routed["subsidiaries"] == ["ceat"] and "Tender board notes" in routed["reason"]


def test_what_a_text_states_becomes_a_decision_an_action_or_a_risk_linked_from_its_input(mesh):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    text = (f"Asha Rao: Asha Rao: We agreed to move the review of {a} to the first week of the month for every plant.\n\n"
            f"Vik Shah: The follow-up is to send the checklist for {b} to the three site leads before the next call.\n\n"
            "Asha Rao: My concern is that the new store has no cover for the monsoon weeks and no second forklift.\n\n"
            "Vik Shah: What is the decision we need today and what can stay open until the next meeting?")
    up = _upload(client, text, graph_name="Statements check", datapoint="E-02").json()
    view = _view(client, up["context_graph"]["id"])
    label = {n["id"]: n for n in view["nodes"]}
    stated = {e["type"]: e for e in view["edges"] if e["type"] in graph_extract.STATEMENT_LINKS}
    assert set(stated) == {"HAS_DECISION", "HAS_ACTION", "HAS_RISK"}  # the question at the end is not a statement
    decision = label[stated["HAS_DECISION"]["target"]]
    assert decision["type"] == "Decision" and decision["label"].startswith("Move the review of") and len(decision["label"].split()) <= 11  # a short name, the speaker left out
    assert all(e["source"] == up["document"]["id"] and e["status"] == "approved" and e["settled_by"] == "rule" for e in stated.values())
    about = [(e["source"], label[e["target"]]["label"]) for e in view["edges"] if e["type"] == "ABOUT"]
    assert (decision["id"], a) in about and (stated["HAS_ACTION"]["target"], b) in about
    assert not any("Asha" in n["label"] or "Vik" in n["label"] for n in view["nodes"])
    # another company, which may read the summary only, gets none of the statements
    other = client.get(f"{GRAPHS}/{up['context_graph']['id']}", headers=_headers("kec"))
    assert other.status_code == 404 or not any(n["type"] in ("Decision", "Action", "Risk") for n in other.json()["nodes"])
    # the same sentences keep their ids when every extraction is made again
    again = client.post("/api/v1/mesh/uploads/extractions?write=true&refresh=true", headers=ADMIN).json()
    assert any(d["document"] == up["document"]["id"] for d in again["documents"])
    assert {e["id"] for e in _view(client, up["context_graph"]["id"])["edges"] if e["type"] in graph_extract.STATEMENT_LINKS} == {e["id"] for e in stated.values()}


def test_a_topic_found_by_one_word_of_its_name_does_not_settle_a_link(mesh):
    """Two sentences name both topics, but one of them only by another name or a single word: a person is asked."""
    from services.mesh_graph import norm_tokens
    g = mesh.mesh.graph
    a = _concepts(mesh, 1)[0]
    a_id = next(n for n, d in g.nodes(data=True) if d.get("label") == a)
    b_id, alias = next((n, x) for n, d in g.nodes(data=True) if d.get("type") == "Concept" and n != a_id
                       for x in (d.get("aliases") or []) if norm_tokens(x) and norm_tokens(x) != norm_tokens(d.get("label") or "") and len(x) > 4
                       and not set(norm_tokens(x)) & set(norm_tokens(a)))
    text = f"The first review raised {a} together with {alias} for the plant. The second review raised {a} together with {alias} again."
    links = graph_extract.code_links(mesh, text, [a_id, b_id])
    link = next(x for x in links if {x["source"], x["target"]} == {a_id, b_id})
    assert link["sentences"] == 2 and link["full_names"] == 0 and graph_extract.settled(link) is None
    assert graph_extract.effective({**link, "status": "proposed"})["status"] == "proposed"
    full = graph_extract.code_links(mesh, text.replace(alias, g.nodes[b_id]["label"]), [a_id, b_id])
    assert graph_extract.settled(next(x for x in full if {x["source"], x["target"]} == {a_id, b_id})) == "repeated"
    # a link kept before the full names were counted waits for a person as well
    assert graph_extract.settled({"by": "code", "type": "RELATED_TO", "sentences": 4}) is None


def test_the_model_writes_the_description_from_the_facts_and_it_holds_only_while_the_inputs_are_the_same(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"The storage team agreed that {a} depends on {b} for every lot of the plant store.", graph_name="Model described", datapoint="E-02").json()
    graph_id, doc_id = up["context_graph"]["id"], up["document"]["id"]
    seen = []
    paragraph = ("This graph covers how the plant store handles its lots. It names the checks and the topics each lot depends on. "
                 "It can answer what a lot needs before it is issued. It belongs to CEAT.")
    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: (lambda step, system, user, version: seen.append((step, user, version)) or paragraph))
    assert _view(client, graph_id)["description"]["by"] == "code"
    made = client.post(f"{GRAPHS}/{graph_id}/description/generate", headers=_headers("kec"))
    assert made.status_code in (403, 404)
    made = client.post(f"{GRAPHS}/{graph_id}/description/generate", headers=ADMIN).json()
    assert made["written"] and made["description"]["by"] == "model" and made["description"]["text"] == paragraph
    step, facts, version = seen[-1]
    assert step == "describe" and version == "mesh_describe_v1" and facts.startswith("Graph: Model described") and f"{a} depends on {b}" in facts
    assert "The storage team agreed" not in facts.split("What the inputs state between them:")[0]  # the raw text is not given, only what was taken from it
    # another company, which sees the input but may not read its text, gets the description made by code
    other = client.get(f"{GRAPHS}/{graph_id}", headers=_headers("kec"))
    assert other.status_code == 404 or other.json()["description"]["by"] == "code"
    # a person's description stands over the model's, and comes back off again
    client.put(f"{GRAPHS}/{graph_id}/description", json={"text": "What the store team agreed about the order of issue."}, headers=ADMIN)
    assert _view(client, graph_id)["description"]["by"] == "person"
    client.put(f"{GRAPHS}/{graph_id}/description", json={"text": ""}, headers=ADMIN)
    assert _view(client, graph_id)["description"]["by"] == "model"
    # a reply that is no paragraph is not kept
    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: (lambda *args: "ok"))
    assert client.post(f"{GRAPHS}/{graph_id}/description/generate", headers=ADMIN).json()["written"] is False
    # the extraction made again changes what the description rests on: the one made by code shows until the model writes again
    graph_extract.extract(mesh, "ceat", uploads.record_of("ceat", doc_id))
    kept = graph_extract.read(doc_id)
    kept["made"] = "2030-01-01T00:00:00+00:00"
    (DATA / "ceat" / graph_extract.FOLDER / f"{doc_id.split(':')[1]}.json").write_text(json.dumps(kept))
    assert _view(client, graph_id)["description"]["by"] == "code"


def test_a_question_that_names_a_thing_of_a_graph_finds_that_graph_and_ask_gets_the_graphs_own_answer(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    text = f"A ticket for a repair is raised on the ZenDesk Plant Portal, and {a} is reviewed there with {b} every week."
    reply = json.dumps({"entities": [{"name": "ZenDesk Plant Portal", "type": "System"}, {"name": "ticket", "type": "Form"}],
                        "links": [{"source": "ticket", "relation": "RAISED_ON", "target": "ZenDesk Plant Portal", "evidence": text}]})
    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: (lambda *args: reply))  # a reply that is JSON is no description
    up = _upload(client, text, graph_name="Repairs of the plant", datapoint="E-02").json()
    assert _view(client, up["context_graph"]["id"])["description"]["by"] == "code"
    graph_id = up["context_graph"]["id"]
    found = graph_describe.match(mesh, "Where is the ZenDesk Plant Portal used?", set(), "ceat", ["group_user"], meaning=False)
    assert found[0]["id"] == graph_id and found[0]["matched_on"] == "things" and found[0]["shared_things"] == ["ZenDesk Plant Portal"]
    assert graph_describe.match(mesh, "Where is the ZenDesk Plant Portal used?", set(), "harrisons", ["group_user"], meaning=False) == []  # may not read the text
    assert graph_describe.match(mesh, "Which ticket is open?", set(), "ceat", ["group_user"], meaning=False) == []  # one common word names no graph
    from services import context_graph_ingest as ingested
    monkeypatch.setattr(ingested, "ask", lambda record, question, **kw: {"answer": "A ticket is raised on the ZenDesk Plant Portal [N1, E1].", "answer_note": None})
    state = {"question": "Where is the ZenDesk Plant Portal used?", "company": "ceat", "roles": ["group_user"]}
    _router(monkeypatch, "Repairs of the plant")
    first = mesh.orchestrator._context_graphs(state, [])[0][0]
    assert first["answer"] == "A ticket is raised on the ZenDesk Plant Portal." and first["answer_note"] is None
    monkeypatch.setattr(ingested, "ask", lambda record, question, **kw: {"answer": None, "answer_note": "No answer model is configured, so the nodes and edges are the answer."})
    first = mesh.orchestrator._context_graphs(state, [])[0][0]
    assert first["answer"] is None and "No answer model" in first["answer_note"]


def test_the_model_uses_listed_types_and_relations_short_names_and_the_things_already_in_the_graph(mesh):
    _clean()
    a = _concepts(mesh, 1)[0]
    text = ("A hardware repair ticket is raised on the IS Service Desk by the employee. The Reporting Manager approves the Leave Request. "
            "The new joiner reads the full welcome booklet that explains the culture and values of the company in detail. "
            f"The IS Service Desk handles {a} questions as well.")
    reply = json.dumps({"entities": [{"name": "hardware repair ticket", "type": "ticket"}, {"name": "IS Service Desk", "type": "Service Desk"},
                                     {"name": "Reporting Manager", "type": "Role"}, {"name": "Leave Request", "type": "Form"},
                                     {"name": "the full welcome booklet that explains the culture and values", "type": "Form"},
                                     {"name": "employee", "type": "Audience Segment"}],
                        "links": [{"source": "hardware repair ticket", "relation": "RAISED_ON", "target": "IS Service Desk", "evidence": "A hardware repair ticket is raised on the IS Service Desk by the employee."},
                                  {"source": "Reporting Manager", "relation": "APPROVES", "target": "Leave Request", "evidence": "The Reporting Manager approves the Leave Request."},
                                  {"source": "hardware repair ticket", "relation": "SUBMITTED_BY", "target": "employee", "evidence": "A hardware repair ticket is raised on the IS Service Desk by the employee."},
                                  {"source": "IS Service Desk", "relation": "HANDLES", "target": a, "evidence": f"The IS Service Desk handles {a} questions as well."}]})
    seen = []
    record = {"document": {"id": "ceat:E-03-U902", "body": text, "concepts": []}}
    out = graph_extract.extract(mesh, "ceat", record, lambda step, system, user, version: seen.append(user) or reply, existing=[("IS service desk", "Service")])
    assert "Things already in the graph:\n- IS service desk (Service)" in seen[0]
    things = {e["name"]: e for e in out["entities"] if e["by"] == "model"}
    assert set(things) == {"hardware repair ticket", "IS service desk", "Reporting Manager", "Leave Request"}  # no description as a name, no type outside the list
    assert things["hardware repair ticket"]["type"] == "Form" and things["IS service desk"].get("existing")
    assert things["IS service desk"]["id"] == graph_extract.thing_id("ceat", "IS Service Desk")  # the thing already in the graph keeps its id
    ends = {(link["type"], link["source"].rsplit(":", 1)[1], link["target"].rsplit(":", 1)[1]) for link in out["links"] if link["by"] == "model"}
    assert ("RAISED_ON", "hardware-repair-ticket", "is-service-desk") in ends
    assert ("APPROVED_BY", "leave-request", "reporting-manager") in ends  # APPROVES is turned round to the listed relation
    assert not any(link["type"] in ("SUBMITTED_BY", "HANDLES") for link in out["links"])  # relations outside the list are left out


def test_the_model_checks_every_link_and_a_person_is_asked_only_about_an_unsure_link_of_high_priority(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    text = (f"The Reporting Manager approves the Leave Request before payroll closes. The Leave Request is kept in ZenFusion. "
            f"Payroll uses the Leave Request for {a} and {b} every month.")
    things = {"entities": [{"name": "Reporting Manager", "type": "Role"}, {"name": "Leave Request", "type": "Form"}, {"name": "ZenFusion", "type": "System"}, {"name": "Payroll", "type": "Team"}],
              "links": [{"source": "Leave Request", "relation": "APPROVED_BY", "target": "Reporting Manager", "evidence": "The Reporting Manager approves the Leave Request before payroll closes."},
                        {"source": "Leave Request", "relation": "ACCESSED_VIA", "target": "ZenFusion", "evidence": "The Leave Request is kept in ZenFusion."},
                        {"source": "Payroll", "relation": "USES", "target": "Leave Request", "evidence": f"Payroll uses the Leave Request for {a} and {b} every month."}]}
    asked = []

    def model(step, system, user, version=None):
        if step == "verify":
            asked.append(user)
            ids = re.findall(r"^id: (\S+)", user, re.M)
            out = []
            for i in ids:
                block = user.split(f"id: {i}\n", 1)[1].split("\n\n", 1)[0]
                verdict = ("unsure" if "APPROVED_BY" in block else "not_supported" if "ACCESSED_VIA" in block else "supported")
                out.append({"id": i, "verdict": verdict, "reason": "test"})
            return json.dumps(out)
        return json.dumps(things) if step == "extract" else None

    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: model)
    up = _upload(client, text, graph_name="Checked links", datapoint="E-02").json()
    view = _view(client, up["context_graph"]["id"])
    label = {n["id"]: n["label"] for n in view["nodes"]}
    by = {(label.get(e["source"]), e["type"], label.get(e["target"])): e for e in view["edges"] if e.get("by") == "model"}
    approve = by[("Leave Request", "APPROVED_BY", "Reporting Manager")]
    assert approve["status"] == "proposed" and approve["priority"] == "high"  # unsure, and it says who approves: a person is asked
    uses = by[("Payroll", "USES", "Leave Request")]
    assert uses["status"] == "approved" and uses["settled_by"] == "model"  # supported by the check: nobody is asked
    assert ("Leave Request", "ACCESSED_VIA", "ZenFusion") not in by  # not supported: set aside, not drawn
    aside = [x for x in view["set_aside"] if x["type"] == "ACCESSED_VIA"]
    assert aside and aside[0]["target_label"] == "ZenFusion" and aside[0]["reason"] == "test"
    assert any(q["text"].startswith("1 link found in the text waits for review") for q in view["quality"])
    # a person may still approve a link the check set aside
    client.post(f"/api/v1/mesh/uploads/{up['document']['id']}/links/{aside[0]['id']}", json={"status": "approved"}, headers=ADMIN)
    again = _view(client, up["context_graph"]["id"])
    assert any(e["id"] == aside[0]["id"] and e["status"] == "approved" for e in again["edges"]) and not again["set_aside"]
    # each link was asked about once, and a second extraction keeps the verdicts without asking again
    n = len(asked)
    graph_extract.extract(mesh, "ceat", uploads.record_of("ceat", up["document"]["id"]))
    graph_extract.verify(mesh, up["document"]["id"], model)
    assert len(asked) == n


def test_a_topic_the_document_is_not_about_is_taken_off_it(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    text = f"This note is about {a} at the plant, which the team reviews every week. A second line mentions {b} in passing only."

    def model(step, system, user, version=None):
        if step == "verify":
            out = []
            for i, block in re.findall(r"^id: (\S+)\n(.*?)(?=\n\nid: |\Z)", user, re.M | re.S):
                out.append({"id": i, "verdict": "not_supported" if f"target: {b}" in block else "supported", "reason": "in passing only" if f"target: {b}" in block else "the note is about it"})
            return json.dumps(out)
        return json.dumps({"entities": [], "links": []}) if step == "extract" else None

    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: model)
    up = _upload(client, text, graph_name="Topic check", datapoint="E-02", tags="").json()
    record = uploads.record_of("ceat", up["document"]["id"])
    ca = next(n for n, d in mesh.mesh.graph.nodes(data=True) if d.get("label") == a)
    cb = next(n for n, d in mesh.mesh.graph.nodes(data=True) if d.get("label") == b)
    assert ca in record["document"]["concepts"] and cb not in record["document"]["concepts"]
    assert record["topics_set_aside"][0]["concept"] == cb and record["topics_set_aside"][0]["reason"] == "in passing only"
    assert up["extraction"]["topics_set_aside"] == 1


def test_a_link_the_model_finds_is_noise_is_left_out_also_when_true_and_a_person_can_bring_it_back(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    text = "The Reporting Manager approves the Leave Request. The company uses the Leave Request."
    things = {"entities": [{"name": "Reporting Manager", "type": "Role"}, {"name": "Leave Request", "type": "Form"}, {"name": "company", "type": "Organisation"}],
              "links": [{"source": "Leave Request", "relation": "APPROVED_BY", "target": "Reporting Manager", "evidence": "The Reporting Manager approves the Leave Request."},
                        {"source": "company", "relation": "USES", "target": "Leave Request", "evidence": "The company uses the Leave Request."}]}

    def model(step, system, user, version=None):
        if step == "verify":
            return json.dumps([{"id": i, "verdict": "supported", "keep": "target: Reporting Manager" in block, "reason": "generic end" if "source: company" in block else "who approves"}
                               for i, block in re.findall(r"^id: (\S+)\n(.*?)(?=\n\nid: |\Z)", user, re.M | re.S)])
        return json.dumps(things) if step == "extract" else None

    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: model)
    up = _upload(client, text, graph_name="Noise check", datapoint="E-02").json()
    view = _view(client, up["context_graph"]["id"])
    label = {n["id"]: n["label"] for n in view["nodes"]}
    kept = [(label[e["source"]], e["type"], label[e["target"]]) for e in view["edges"] if e.get("by") == "model"]
    assert kept == [("Leave Request", "APPROVED_BY", "Reporting Manager")] and "company" not in label.values()
    noise = next(x for x in view["set_aside"] if x["type"] == "USES")
    assert noise["why"] == "not_needed" and noise["reason"] == "generic end"
    client.post(f"/api/v1/mesh/uploads/{up['document']['id']}/links/{noise['id']}", json={"status": "approved"}, headers=ADMIN)
    assert any(e["id"] == noise["id"] and e["status"] == "approved" for e in _view(client, up["context_graph"]["id"])["edges"])


def test_a_question_without_a_graph_id_is_routed_by_the_model_and_an_unclear_one_gets_suggestions(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    one = _upload(client, f"The quarterly tender review of {a} agreed the vendor shortlist for the next round.", graph_name="Tender reviews", datapoint="E-01").json()  # never leaves CEAT
    two = _upload(client, f"The plant storage audit of {b} found two damp racks and moved the lots to rack seven.", graph_name="Storage audits", datapoint="E-02").json()
    url = "/api/v1/context-graphs/query"
    assert client.post(url, json={"overview": True}, headers=ADMIN).status_code == 422
    # no model: nothing is chosen, and the reply says why
    monkeypatch.setattr(graph_describe, "model_caller", lambda backend, app_env: None)
    none = client.post(url, json={"question": "Where did the lots go?"}, headers=ADMIN).json()
    assert none["graph"] is None and none["chosen_by"] == "none" and "needs the model" in none["answer_note"]
    # a clear question: the model's graph answers it, as understood, and the reply names the graph
    seen = []
    _router(monkeypatch, "Storage audits", seen=seen)
    clear = client.post(url, json={"question": "Where did the lots go?"}, headers=ADMIN).json()
    assert clear["graph"]["id"] == two["context_graph"]["id"] and clear["chosen_by"] == "model" and clear["intent"] == "clear" and clear["why"] == "about Storage audits"
    assert "G1: " in seen[-1] and "Inputs: " in seen[-1]  # the model reads names, descriptions and input titles
    # an unclear question: no answer, full questions to ask instead, at most three
    _router(monkeypatch, "Storage audits", intent="unclear", suggestions=["Where were the damp lots moved?", "Which racks were damp?", "Who did the audit?", "A fourth one"])
    vague = client.post(url, json={"question": "lots"}, headers=ADMIN).json()
    assert vague["graph"] is None and vague["answer"] is None and vague["intent"] == "unclear" and "unclear" in vague["answer_note"]
    assert vague["suggestions"] == ["Where were the damp lots moved?", "Which racks were damp?", "Who did the audit?"] and vague["also_close"][0]["id"] == two["context_graph"]["id"]
    # off topic and a greeting: no graph, no answer
    for intent, words in (("off_topic", "None of the context graphs"), ("greeting", "Ask a question")):
        _router(monkeypatch, None, intent=intent)
        r = client.post(url, json={"question": "hello"}, headers=ADMIN).json()
        assert r["graph"] is None and words in r["answer_note"]
    # another company never sees the never-leave graph: the model is not shown it, and a graph the model names that is not listed is ignored
    seen.clear()
    _router(monkeypatch, "Tender reviews", seen=seen)
    other = client.post(url, json={"question": "What did the tender review agree?"}, headers=_headers("kec")).json()
    assert "Tender reviews" not in seen[-1] and other["graph"] is None


def test_a_graph_answers_by_meaning_and_from_the_text_the_caller_may_read(mesh):
    from services import context_graph_ingest as ingested
    record = {"id": "g-test", "nodes": [{"id": "a", "type": "Form", "name": "Hardware Repair Ticket"}, {"id": "b", "type": "Service", "name": "IS Service Desk"}],
              "edges": [{"id": "e1", "type": "RAISED_ON", "source": "a", "target": "b", "properties": {"evidence": "A hardware repair ticket is raised on the IS Service Desk."}}],
              "_texts": [{"doc": "ceat:E-03-U903", "title": "IT guide", "text": "Laptops are issued on the first day. A broken laptop is reported through a hardware repair ticket on the IS Service Desk portal, and the IT team replaces it within two days."}]}
    found = ingested.retrieve(record, "Where should I report a broken laptop?")
    held = {n["name"] for n in found["nodes"]}
    texts = ingested.passages(record, "Where should I report a broken laptop?")
    assert held or texts  # by meaning, though the question names no node
    assert texts and texts[0]["ref"] == "P1" and "broken laptop" in texts[0]["text"]
    assert ingested.passages({**record, "_texts": []}, "Where should I report a broken laptop?") == []  # no text for a caller who may not read it
    assert "P1" in {ref for m in ingested.CITATION.finditer("It goes to the desk [P1].") for ref in m.group(1).split(",")}


def test_review_fixes_decision_during_check_tagged_topic_and_unreadable_record(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    text = f"The Reporting Manager approves the Leave Request. This note covers {b} in passing."
    things = {"entities": [{"name": "Reporting Manager", "type": "Role"}, {"name": "Leave Request", "type": "Form"}],
              "links": [{"source": "Leave Request", "relation": "APPROVED_BY", "target": "Reporting Manager", "evidence": "The Reporting Manager approves the Leave Request."}]}
    decided = {}

    def model(step, system, user, version=None):
        if step == "verify":
            if "IS_ABOUT" in user:  # the topic check: the model says the note is about none of its topics
                return json.dumps([{"id": i, "verdict": "not_supported", "reason": "passing"} for i in re.findall(r"^id: (\S+)", user, re.M)])
            # a person rejects the link while the model is being asked about it
            doc = decided["doc"]
            link = graph_extract.read(doc)["links"][0]
            graph_extract.decide(doc, link["id"], "rejected", {"company": "ceat", "roles": ["group_user"]})
            return json.dumps([{"id": i, "verdict": "supported", "keep": True, "reason": "t"} for i in re.findall(r"^id: (\S+)", user, re.M)])
        if step == "extract":
            return json.dumps(things)
        return None

    real_extract = graph_extract.extract

    def remember(rt, node, record, call_model=None, existing=()):
        decided["doc"] = record["document"]["id"]
        return real_extract(rt, node, record, call_model, existing)

    monkeypatch.setattr(graph_extract, "extract", remember)
    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: model)
    up = _upload(client, text, graph_name="Review fixes", datapoint="E-02", tags=a).json()
    doc_id = up["document"]["id"]
    link = next(x for x in graph_extract.read(doc_id)["links"] if x["type"] == "APPROVED_BY")
    assert link["status"] == "rejected" and link["decided"]["by_company"] == "ceat" and "check" not in link  # the decision made during the check was kept
    record = uploads.record_of("ceat", doc_id)
    ca = next(n for n, d in mesh.mesh.graph.nodes(data=True) if d.get("label") == a)
    assert ca in record["document"]["concepts"]  # the topic the person tagged was not taken off
    assert uploads.is_real(doc_id) and not uploads.is_real("ceat:E-02-01")
    assert uploads.is_real("ceat:E-02-U999")  # an upload whose record cannot be read counts as real


def test_a_model_description_is_shown_only_to_a_viewer_who_may_read_every_input(mesh, monkeypatch):
    _clean()
    client = TestClient(app)
    a, b = _concepts(mesh)
    up = _upload(client, f"A note on {a} and {b} for the storage team, written after the monthly review.", graph_name="Read rule", datapoint="E-02").json()
    paragraph = "This graph covers the storage team's monthly review. It names the checks the store runs. It belongs to CEAT and answers questions on storage."
    monkeypatch.setattr(uploads, "_extract_caller", lambda rt, sensitivity, synthetic: (lambda *args: paragraph))
    client.post(f"{GRAPHS}/{up['context_graph']['id']}/description/generate", headers=ADMIN)
    assert _view(client, up["context_graph"]["id"])["description"]["by"] == "model"
    monkeypatch.setattr(uploads, "_may_read_text", lambda node, record, company, roles: "mesh_admin" in roles)
    ceat = client.get(f"{GRAPHS}/{up['context_graph']['id']}", headers=_headers("ceat")).json()
    assert ceat["description"]["by"] == "code"  # a viewer who may not read the text gets the description made from what they see
