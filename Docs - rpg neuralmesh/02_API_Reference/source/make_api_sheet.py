#!/usr/bin/env python3
"""Make RPG_NeuralMesh_API_Complete_List_v1.xlsx beside this folder, from the same inputs as the HTML page:
recorded.json (the calls sent to the running development API with their answers), routes.json (every REST route read
from the code), contract.json (the published context contract) and the registry files of the applications. The REST
tab is checked against routes.json, so a route added or removed in the code stops this script until the tab follows.
Run: python3 make_api_sheet.py, then recalculate the counts of the Read me tab (scripts/recalc.py of the xlsx skill)."""
from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import yaml
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

HERE = Path(__file__).resolve().parent
OUT = HERE.parent / "RPG_NeuralMesh_API_Complete_List_v1.xlsx"
APPS = HERE.parents[2] / "app" / "config" / "applications"  # this folder sits in the RPG-NeuralMesh repository
CALLS = {c["id"]: c for c in json.loads((HERE / "recorded.json").read_text())}
ROUTES = json.loads((HERE / "routes.json").read_text())
CONTRACT = json.loads((HERE / "contract.json").read_text())
SENT_ON = "11 November 2026"
NOT_SENT = "Not sent, because it changes data"

# ── REST routes: (group, method, path, who, what it does, what to send, what comes back, changes data, call id or example request)
R = [
    ("Health and sign-in", "GET", "/health", "Anyone, no token needed",
     "Tells whether the NeuralMesh API is running. It always answers the same fixed text, so it shows that the service is up, not that every company node is healthy.",
     "Nothing.", "status (ok) and the version number.", "No", "health"),
    ("Health and sign-in", "GET", "/api/v1/auth/companies", "Anyone, no token needed",
     "Lists the companies a person can choose when signing up: every registered company node, by id and by name. It is read before sign-in.",
     "Nothing.", "companies: a list of id and label, for example ceat and CEAT.", "No", "companies"),
    ("Health and sign-in", "POST", "/api/v1/auth/signup", "Anyone, no token needed",
     "Creates an account and signs the new person in. The person chooses their company from the list of companies. In this development setup sign-up is open to anyone, which a real deployment replaces with company sign-in.",
     "email (5 to 254 characters), password (10 to 128 characters), display_name and company (an id from the list of companies). A person who wants to appear in Expert Finder also sends expert_opt_in true, expert_title and up to 20 expert_skills.",
     "access_token, token_type (bearer) and user, the same as sign-in.", "Yes",
     'POST /api/v1/auth/signup\n{"email": "new.user@example.com", "password": "<10 or more characters>", "display_name": "New User", "company": "ceat"}'),
    ("Health and sign-in", "POST", "/api/v1/auth/signin", "Anyone, no token needed",
     "Signs a person in with email and password and gives the token every later call sends in the header Authorization: Bearer. The token is valid for 12 hours.",
     "email and password.", "access_token, token_type (bearer) and user: id, email, name, company, company name, roles and expert profile.", "No", "signin"),
    ("Health and sign-in", "GET", "/api/v1/auth/me", "A signed-in person",
     "Tells who the token belongs to. The company and the roles in the token decide what the person may see in every other call.",
     "Nothing but the token.", "user_id, email, display_name, company, company_name, roles and expert_profile.", "No", "me"),

    ("Ask and search the mesh", "POST", "/api/v1/mesh/query", "A signed-in person",
     "Asks the mesh a question. NeuralMesh finds the companies whose knowledge fits the question, asks their nodes under each company's own rules, ranks what comes back and writes an answer that cites the documents it used. Items a company keeps to itself are listed as withheld, with the reason.",
     "question (3 to 2,000 characters) and purpose (problem_solving, compliance, bid_support, learning, career_mobility or inspection). If wanted: nodes (a list of company ids to ask, up to 16), mode (MD, SUM, RAG or LIVE) and as_of (a date the nodes use for the results blackout check).",
     "status, answer, answer_status (answered, or why the answer is not shown), citations, the checks that failed, the evidence used, the withheld items, other documents found, the routing, the steps with their times, the answer of each company node, the model calls and a trace id.", "No", "ask"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/routing", "A signed-in person",
     "Shows where a question would go without asking any company: the concepts it names, and the companies and catalogue items that hold them.",
     "q: the question, in the address.", "concepts, subsidiaries, datapoints, documents, fallback and the companies left out.", "No", "routing"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/graph", "A signed-in person",
     "Gives the whole mesh graph as the person may see it: its entities and links, without the never-leave entities of other companies.",
     "Nothing.", "nodes, edges, counts by type, store counts, the last export of each company node, the revision and the graph checks.", "No", "graph"),
    ("Ask and search the mesh", "POST", "/api/v1/mesh/graph/refresh", "A mesh admin",
     "Asks every company node for its export again and reloads the mesh graph from them.",
     "Nothing.", "The result of each export, the store counts, the new revision and the graph checks.", "Yes", "POST /api/v1/mesh/graph/refresh"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/graph/search", "A signed-in person",
     "Finds entities of the mesh graph whose name, other name, tag or catalogue code holds the words. When no name matches, the concepts closest in meaning are given instead.",
     "q: a word or phrase of up to 300 characters, in the address.", "results: id, type, label, company, owner, how it matched, sharing rule and number of links of each. Also by_vector and total.", "No", "search"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/graph/entity/{entity_id}", "A signed-in person",
     "Gives one entity of the mesh graph with its fields, its sharing rule and its neighbours one link away, grouped by link type.",
     "The entity id in the path, for example concept:latex-collection-and-transport.", "id, type, label, owner, company, aliases, properties, sharing, connections and related.", "No", "entity"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/domains", "A signed-in person",
     "Lists the layers of the mesh graph: each domain with its node types and edge types and their live counts.",
     "Nothing.", "domains, groups, sources, revision and checks.", "No", "domains"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/applications", "A signed-in person",
     "Lists the applications connected to the mesh, read from their registry files: what each may call and what each loaded into the graph.",
     "Nothing.", "applications and revision.", "No", "applications"),
    ("Ask and search the mesh", "GET", "/api/v1/mesh/nodes", "A signed-in person",
     "Lists the company nodes with their health, level, port and the catalogue items each one shares.",
     "Nothing.", "nodes: one entry for each company node.", "No", "nodes"),
    ("Ask and search the mesh", "POST", "/api/v1/mesh/experts/search", "A signed-in person",
     "Finds consented experts by skill or topic across the companies. Each company node answers for its own people, and a name is shown only after an approved introduction.",
     "query (2 to 500 characters). If wanted: purpose and nodes.", "The answer of each company node, and experts: role, company, skills and evidence of each, never a name.", "No", "experts"),
    ("Ask and search the mesh", "POST", "/api/v1/mesh/experts/{node_id}/intro", "A signed-in person",
     "Asks for an introduction to one expert. The company node opens a request that its owner approves or denies.",
     "expert_id (from the expert search) and justification (10 to 500 characters). If wanted: purpose.", "The request the company node opened, waiting for its owner.", "Yes",
     'POST /api/v1/mesh/experts/harrisons/intro\n{"expert_id": "<expert id from the expert search>", "justification": "Advice on latex preservation at collection points."}'),

    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/graph/links", "A signed-in person",
     "Lists the links between documents of two companies (CORROBORATES, CONFLICTS_WITH, ADDRESSES_GAP and SUPERSEDES) with their status and the approval of each side.",
     "Nothing.", "links.", "No", "links"),
    ("Links, governance and the dashboard", "POST", "/api/v1/mesh/graph/links/{rel_id}/review", "A signed-in person, in development only and with a local demo account",
     "One company approves or rejects a link that touches its documents. A link is shown in answers only when both sides approved it.",
     "decision (approve or reject). If wanted: subsidiary.", "The link after the review.", "Yes", 'POST /api/v1/mesh/graph/links/<link id>/review\n{"decision": "approve"}'),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/proposals", "A signed-in person",
     "Lists the entries applications proposed for the graph, grouped by application and link type, with the sides that approve each entry.",
     "Nothing.", "groups and your_sides.", "No", "proposals"),
    ("Links, governance and the dashboard", "POST", "/api/v1/mesh/proposals/review", "A signed-in person, in development only and with a local demo account",
     "Approves or rejects proposed entries for the reviewer's own side: their company, and the group for a mesh admin.",
     "decision (approve or reject). If wanted: ids (up to 2,000), application and type.", "reviewed and decision.", "Yes", 'POST /api/v1/mesh/proposals/review\n{"decision": "approve", "ids": ["<entry id>"]}'),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/governance", "A signed-in person",
     "Shows the access requests waiting for approval and the latest lines of the company nodes' decision logs.",
     "Nothing.", "pending, audit and mode.", "No", "governance"),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/governance/audit/verify", "A signed-in person",
     "Checks that each company node's decision log is an unbroken hash chain, so a line that was changed, added or removed would show.",
     "Nothing.", "nodes, with the result of each, and valid.", "No", "verify"),
    ("Links, governance and the dashboard", "POST", "/api/v1/mesh/governance/{node_id}/requests/{request_id}/review", "A signed-in person of the owning company, in development only and with a local demo account",
     "The owning company approves or denies an access request. An approval lasts the number of hours given.",
     "decision (approve or deny). If wanted: hours, from 1 to 168, 24 when missing.", "The request after the review.", "Yes", 'POST /api/v1/mesh/governance/kec/requests/<request id>/review\n{"decision": "approve", "hours": 24}'),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/admin", "A signed-in person",
     "Shows the setup of the mesh: the node registry, the vocabulary, the graph counts, the guardrails, the model policy and the pipeline steps.",
     "Nothing.", "registry, ontology, graph_counts, guardrails, model_policy and orchestrator_stage.", "No", "admin"),
    ("Links, governance and the dashboard", "GET", "/api/v1/mesh/dashboard", "A signed-in person",
     "Gives the figures of the Dashboard page: company node health, search decisions, pending approvals, recent activity and the number of graphs ingested as JSON.",
     "Nothing.", "nodes, connected_nodes, total_nodes, search_decisions, allowed_decisions, blocked_decisions, pending_approvals, activity_by_node, recent_activity and ingested_graphs.", "No", "dashboard"),

    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads", "A signed-in person",
     "Lists the uploaded documents the person may see, newest first, and the context graphs they form. A mesh admin sees every company's, anyone else their own company's and the shared inputs.",
     "Nothing.", "uploads, graphs, kinds, formats and export formats.", "No", "uploads"),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads", "A mesh admin",
     "Keeps one uploaded file as a document of a company's catalogue item, in a new or an existing context graph. The company's pack, keyword index and vectors are rebuilt and the mesh graph is refreshed.",
     "A form with file (.txt, .md, .csv, .json, .pdf or .docx, up to 20 MB), node_id, datapoint, and graph_id of an existing graph or graph_name of a new one. If wanted: kind, title, tags, version, kind_label, new_item_title, new_item_area, and synthetic, true for invented data. A file sent without synthetic is real.",
     "The upload record, the result of the refresh and the part of the graph around the new document.", "Yes",
     "POST /api/v1/mesh/uploads (a form)\nfile=@plant_note.txt, node_id=ceat, datapoint=E-03, graph_name=Plant storage notes"),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/suggest", "A mesh admin",
     "Reads a file without keeping it and proposes what the Upload input form fills in: the title, tags, kind, concepts and the context graph it fits.",
     "A form with file. If wanted: node_id and datapoint.", "title, tags, kind, concepts, graph and who decided. Nothing is kept.", "No", "suggest"),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/items/{node_id}", "A mesh admin",
     "Lists the catalogue items of a company that an upload can go under, each with its sharing rule, and the areas a new item can be made in.",
     "The company id in the path.", "node_id, items and new_item_areas.", "No", "items"),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/graphs/{graph_id}", "A signed-in person",
     "Gives one uploaded context graph: the documents the person may see, their items and companies, the entities one link away and the links among them. With format it gives a file instead.",
     "If wanted: format (json, graphml, csv or pack), in the address.", "id, name, documents, nodes, edges and counts, or the file.", "No", "upload_graph"),
    ("Uploaded context graphs (Upload input)", "DELETE", "/api/v1/mesh/uploads/graphs/{graph_id}", "A mesh admin",
     "Takes every document of a context graph out of the packs, the indexes and the mesh graph. The upload records stay, marked removed.",
     "Nothing.", "graph, removed, rebuilt, failed and refresh.", "Yes", "DELETE /api/v1/mesh/uploads/graphs/<graph id>"),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/{doc_id}/graph", "A signed-in person",
     "Gives the part of the graph around one uploaded document, or a file with format.",
     "If wanted: format (json, graphml, csv or pack), in the address.", "nodes, edges, counts and centre, or the file.", "No", "doc_graph"),
    ("Uploaded context graphs (Upload input)", "DELETE", "/api/v1/mesh/uploads/{doc_id}", "A mesh admin",
     "Takes one uploaded document out of its pack, its index and the mesh graph. The record stays, marked removed.",
     "Nothing.", "The record and the result of the refresh.", "Yes", "DELETE /api/v1/mesh/uploads/<document id>"),
    ("Uploaded context graphs (Upload input)", "GET", "/api/v1/mesh/uploads/json-templates", "A signed-in person",
     "Gives the JSON structure every context graph is written in, with the values it can fill.",
     "If wanted: graph_id, in the address.", "template, own, suggested, fields and can_change.", "No", "structure"),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/json-templates/render", "A signed-in person",
     "Writes a context graph in the JSON structure, as the person may see it. This is the file Upload input downloads, and Ingest data accepts it.",
     "graph_id.", "output: the graph in the JSON structure.", "No", "render"),
    ("Uploaded context graphs (Upload input)", "PUT", "/api/v1/mesh/uploads/graphs/{graph_id}/template", "A mesh admin",
     "Would keep a JSON structure of its own with one context graph. It is refused while one structure for every graph is the rule.",
     "template.", "The reason it is refused.", "Yes", 'PUT /api/v1/mesh/uploads/graphs/<graph id>/template\n{"template": {"graph": "{graph.name}"}}'),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/formats", "A mesh admin",
     "Keeps a download format a mesh admin wrote: a name, a file extension, the escaping, and a header, a line for each entity, a line for each link and a footer, with names in braces filled from the graph.",
     "name, extension, escape, header, node_line, edge_line and footer.", "format and export_format_list.", "Yes",
     'POST /api/v1/mesh/uploads/formats\n{"name": "Edge list", "extension": "txt", "escape": "none", "header": "", "node_line": "", "edge_line": "{source} {type} {target}", "footer": ""}'),
    ("Uploaded context graphs (Upload input)", "POST", "/api/v1/mesh/uploads/formats/file", "A mesh admin",
     "Keeps a download format uploaded as a text file of up to 20,000 bytes.",
     "A form with file.", "format and export_format_list.", "Yes", "POST /api/v1/mesh/uploads/formats/file (a form)\nfile=@edge_list_format.txt"),
    ("Uploaded context graphs (Upload input)", "DELETE", "/api/v1/mesh/uploads/formats/{format_id}", "A mesh admin",
     "Removes a download format a mesh admin added. The built-in formats stay.",
     "Nothing.", "removed and export_format_list.", "Yes", "DELETE /api/v1/mesh/uploads/formats/<format id>"),

    ("Ingested context graphs (Ingest data)", "POST", "/api/v1/context-graphs", "A signed-in person for their own company, a mesh admin for any company",
     "Keeps the JSON a person wrote as a context graph, or replaces the graph its graph_id names. Code makes the missing ids, uses the safe value for a missing sensitivity, sharing or synthetic flag, and refuses a missing node type, edge end or company with the place to fix. With check=true it only checks and keeps nothing.",
     "The JSON: graph, company, nodes and edges, and if wanted sensitivity, sharing, synthetic, description and graph_id (see the tab Ingest JSON fields). Add ?check=true to the address to check without keeping.",
     "201 when created, 200 when replaced, unchanged or only checked: graph (id, name, company, counts, sensitivity, sharing and the routes), filled, defaults, ignored and warnings. 422 with problems when a field needs a change, and then nothing is kept.", "Yes, unless check=true", "cg_check"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs", "A signed-in person",
     "Lists the ingested graphs the person may see, the latest first.", "Nothing.", "graphs: a summary of each.", "No", "cg_list"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs/sample", "A signed-in person",
     "Gives a small invented graph in the JSON structure, for the person's company, to show how a graph is written.", "Nothing.", "The sample JSON.", "No", "cg_sample"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs/{graph_id}", "A signed-in person who may see the graph",
     "Gives one graph in the format it was ingested in, with its graph_id, so it can be changed and sent back to replace it.",
     "Nothing.", "graph_id, graph, company, description, sensitivity, sharing, synthetic, nodes and edges.", "No", "cg_get"),
    ("Ingested context graphs (Ingest data)", "GET", "/api/v1/context-graphs/{graph_id}/view", "A signed-in person who may see the graph",
     "Gives the nodes and edges of a graph in the shape a drawing takes, with the graph's summary.",
     "Nothing.", "id, name, nodes, edges, counts and graph.", "No", "cg_view"),
    ("Ingested context graphs (Ingest data)", "POST", "/api/v1/context-graphs/{graph_id}/query", "A signed-in person who may see the graph",
     "Asks one graph by its id: what it holds, nodes by type, name or property, one node and its neighbours, relationships, how two nodes are connected, what is similar to a node, or a question in plain words. See the tab Context graph queries.",
     "One of the seven query bodies, for example {\"overview\": true}.", "graph and kind, then the answer of that kind of query.", "No", "q_overview"),
    ("Ingested context graphs (Ingest data)", "DELETE", "/api/v1/context-graphs/{graph_id}", "A signed-in person of the owning company, or a mesh admin",
     "Deletes an ingested graph. The ingest log keeps its id, name, company and counts, never its content.",
     "Nothing.", "dropped: id, name, company and counts.", "Yes", "DELETE /api/v1/context-graphs/<graph id>"),

    ("Help", "POST", "/api/v1/help/chat", "A signed-in person",
     "Asks the in-app help chat, which answers from the help guides of the application.",
     "question (2 to 2,000 characters). If wanted: history (up to 20 earlier turns) and page.", "answer, sources and mode (model, or passages when no model may answer).", "No", "help"),

    ("Applications: the context contract", "GET", "/api/v1/context/contract", "A registered application, with its service token",
     "Gives the published context contract: version 1.1, the request and answer schemas, the statuses, the problem codes and every tool. An application compares the sha256 with its pinned copy to see a change.",
     "Nothing but the service token.", "contract, version, supported_versions, endpoint, statuses, problem_codes, rules, request, answer, tools and sha256.", "No", "contract"),
    ("Applications: the context contract", "POST", "/api/v1/context/{tool}", "A registered application, with its service token",
     "Calls one tool of the contract. Every call names the purpose and the end user's company and roles, so each company node applies its rules to the real user. See the tab Contract tools.",
     "The envelope: schema_version (1.1), tool, purpose, caller (subsidiary, roles, and user_ref for a person) and input.",
     "schema_version, tool, status (ok, partial, no_evidence, blocked, needs_input or refused), records, answer, also_found, omitted, data, problem and trace_id.", "Only for record_inspection and import", "t_role"),
]

TOOLS_TEXT = {
    "role_context": "The skills a role of a company needs, with the level of each, the concepts behind them, how many documents and experts exist for each skill, and similar roles at other companies.",
    "skill_context": "One skill with its description, other names, related skills, the roles that need it and the evidence documents its owners released.",
    "learning_sources": "Study documents other companies released for learning that reach the level asked, given by reference.",
    "find_mentors": "Consented experts of a skill, without names. A name needs an approved introduction.",
    "vocabulary_export": "The group vocabulary of skills and concepts with their other names, as one pack.",
    "ask": "A written answer from cited documents, checked sentence by sentence, with the evidence records.",
    "entity": "One entity of the mesh graph with its fields and its link counts.",
    "related": "The neighbours of an entity grouped by link type, one or two hops away.",
    "similar": "Entities computed as similar, with the reason and a score.",
    "live": "A fact that is never stored, asked of the owning company node at that moment with the user's identity, for example the cover status of an asset.",
    "inspection_profile": "What is checked when an asset is inspected: the conditions, the views, the grade scale, the expected cover and the governing standards.",
    "inspection_history": "The past inspections of an asset, newest first.",
    "record_inspection": "Records one inspection as an event in the graph. The images stay with the application.",
    "import": "Sends the packs the registry allows. Each pack is loaded, unchanged, or refused with its reason.",
}
TOOL_CALL = {"role_context": "t_role", "entity": "t_entity", "related": "t_related", "similar": "t_similar", "ask": "t_ask", "skill_context": "t2_skill",
             "learning_sources": "t2_learning", "find_mentors": "t2_mentors", "vocabulary_export": "t2_vocab", "inspection_profile": "t2_profile",
             "inspection_history": "t2_history", "live": "t2_live"}
TOOL_EXAMPLE = {
    "record_inspection": {"schema_version": "1.1", "tool": "record_inspection", "purpose": "inspection", "caller": {"subsidiary": "ceat", "roles": ["user"], "user_ref": "app-user-1042"},
                          "input": {"inspection_id": "CEAT-INS-0001", "asset": "ceat:asset/finished_tyre", "grade": "B", "conditions": ["<condition id>"], "image_ref": "<a reference kept by the application>"}},
    "import": {"schema_version": "1.1", "tool": "import", "purpose": "career_mobility", "caller": {"subsidiary": "group", "roles": ["service"]},
               "input": {"packs": ["<a knowledge pack the registry allows, such as group.skillforge-skills>"]}},
}

QUERIES = [
    ("What does the graph hold", "overview", '{"overview": true}',
     "The number of nodes and edges, the node types with their counts, the edge types with their counts and the node types each one joins, and the number of nodes without edges.",
     "Nothing else is needed.", "q_overview"),
    ("Find things by type, name or property", "nodes", '{"nodes": {"type": "Supplier", "name": "part of a name", "properties": {"material": "FKM"}}}',
     "nodes (up to 200) and total.", "Give one or more of type, name and properties. type and properties must be equal (in any case), name may be a part of the name or of another name.", "q_nodes"),
    ("One thing and what is around it", "node", '{"node": "Mixer 1", "hops": 1}',
     "node, its neighbours and the edges walked to reach them, with totals.", "The node is named by its id, its name or another name, in any case. hops is 1 or 2, 1 when missing.", "q_node"),
    ("Relationships", "edges", '{"edges": {"type": "SUPPLIES", "source": "Supplier X", "target": "Rotor seal RS-200"}}',
     "edges (up to 500), each with its type, its source and target nodes and a line of text, and total.", "Give one or more of type, source and target. relationships is read as another name for edges.", "q_edges"),
    ("How two things are connected", "path", '{"path": {"from": "Supplier X", "to": "Plant A", "max_hops": 4}}',
     "hops and paths: up to 3 shortest ways, each a list of edges and a line of text.", "An edge is walked in either direction and given back as it is stored. max_hops is 1 to 6, 4 when missing. When no way is short enough, paths is empty with a note.", "q_path"),
    ("What is similar to one thing", "similar", '{"similar": {"node": "Supplier X", "top": 5}}',
     "similar: nodes of the same type, each with a score, the shared neighbours and the reason, and total.", "The score is the shared neighbours divided by all the neighbours of the two (the Jaccard index), from 0 to 1. top is 1 to 20, 5 when missing.", "q_similar"),
    ("A question in plain words", "question", '{"question": "Which suppliers supply the rotor seal?"}',
     "matched nodes, numbered nodes (N1 onwards) and edges (E1 onwards), and an answer that cites them, or answer_note saying why there is no written answer.",
     "Code finds the nodes the question names and the edges around them. The answer model writes only when the model rules allow it for the graph, and a sentence that cites no given node or edge is left out. A graph with synthetic false never reaches a cloud model.", "q_question"),
]

FIELDS = [
    ("graph", "Top of the JSON", "Yes", "The name of the graph, 3 to 80 characters. A company has one graph of each name.", "Refused: graph is missing.", '"graph": "Example: mixing line spare parts"'),
    ("company", "Top of the JSON", "Yes", "The company that owns the data, by id or by name. A person writes their own company, a mesh admin may write any company.", "Refused: company is missing.", '"company": "CEAT"'),
    ("nodes", "Top of the JSON", "Yes", "The list of the things in the graph.", "Refused: nodes is missing or empty.", '"nodes": [ ... ]'),
    ("nodes: type", "Each node", "Yes", "What the node is, in the words of the person, for example Supplier.", "Refused with the place, for example nodes[1].", '"type": "Supplier"'),
    ("nodes: name", "Each node", "Yes", "The name of the node.", "Taken from the id and listed under Filled in. Refused when the id is missing too.", '"name": "Supplier X"'),
    ("nodes: id", "Each node", "No", "A short id the edges use.", "Made from the type and the name and listed under Filled in, for example supplier-supplier-x.", '"id": "sup-x"'),
    ("nodes: aliases", "Each node", "No", "Other names of the node, up to 50, each up to 200 characters. A query finds the node by any of them.", "No other names.", '"aliases": ["Mixer 1"]'),
    ("nodes: properties", "Each node", "No", "Values of the node: text, numbers, true or false, or lists of them. A field written beside type and name is kept as a property too.", "No properties.", '"properties": {"stock": 14}'),
    ("edges", "Top of the JSON", "Yes, can be empty", "The list of relationships. relationships is read as another name for edges.", "A graph of nodes only, with a warning.", '"edges": [ ... ]'),
    ("edges: type", "Each edge", "Yes", "The kind of relationship, in the words of the person, for example SUPPLIES.", "Refused with the place, for example edges[2].", '"type": "SUPPLIES"'),
    ("edges: source and target", "Each edge", "Yes", "The node the edge starts at and the node it ends at, by id, or by name when the name fits one node.", "Refused with the place. A name that fits no node or several nodes is refused too.", '"source": "sup-x", "target": "rs-200"'),
    ("edges: id", "Each edge", "No", "A short id of the edge.", "Made from the type and listed under Filled in, for example supplies-1.", '"id": "e6"'),
    ("edges: properties", "Each edge", "No", "Values of the edge, the same kinds as on a node.", "No properties.", '"properties": {"preferred": true}'),
    ("sensitivity", "Top of the JSON", "No", "Public, Internal, Confidential or Restricted.", "Restricted, listed under Defaults used.", '"sensitivity": "Internal"'),
    ("sharing", "Top of the JSON", "No", "company: only the owning company and mesh admins see the graph. group: every company sees it, which needs Internal or Public. A graph of Others needs group.", "company, listed under Defaults used.", '"sharing": "company"'),
    ("synthetic", "Top of the JSON", "No", "true when the data is invented for testing. Only a mesh admin writes true.", "false: the data is treated as real and no cloud model reads it. Listed under Defaults used.", '"synthetic": false'),
    ("description", "Top of the JSON", "No", "A text of up to 1,000 characters.", "No description.", '"description": "Spare parts of mixing line 1"'),
    ("graph_id", "Top of the JSON", "No", "The id of a graph to replace. The graph keeps its id and its company.", "A new graph is made.", '"graph_id": "cg-1cc11e1e"'),
]

NODE_TOOLS = [
    ("health", "Tells the company node's identity and health.", "None"),
    ("describe_capabilities", "Lists the catalogue items the company allows for the purpose, with their sharing ceilings.", "purpose"),
    ("search", "Searches the company's own approved index and gives the results its policy allows, with citations, and what it withheld.", "query, purpose. If wanted: mode, as_of, domains, concepts"),
    ("summarize", "Gives the company's approved summary of one document, with its citation.", "document_id, purpose"),
    ("find_experts", "Finds the company's consented experts by role, skills and the concepts of their evidence. Names need an approved introduction.", "query, purpose. If wanted: concepts"),
    ("lookup", "Gives a live fact of the company, read at that moment and never stored in the mesh, for example the cover status of an asset.", "fact, key. If wanted: purpose"),
    ("aggregate", "Gives a grouped view of the company's own database, computed at that moment, for example spoilage by month.", "datapoint_id, view. If wanted: purpose"),
    ("export_graph", "Gives the metadata of the company's packs for the mesh graph, never document text. Only the mesh service identity may call it.", "None"),
    ("request_access", "Opens a request for content access, or for a consented introduction to an expert, which the company's owner approves.", "datapoint_id, mode, purpose, justification. If wanted: kind, expert_id"),
]

HTTP_CODES = [
    ("200", "The call worked. A contract call also answers 200 when it refuses: its status and problem say what is needed."),
    ("201", "The call made something new, for example an ingested graph."),
    ("401", "The token is missing, invalid or expired. Sign in again."),
    ("403", "The token is fine, but the route needs a role the person does not have, or the call is not allowed for this person."),
    ("404", "The id is not there, or it is not shown to the caller. The two read the same, so a hidden graph is never revealed."),
    ("409", "A name fits several nodes of a graph. The answer lists the candidates, so the caller can send the id of one."),
    ("413", "The body is larger than 8,000,000 bytes."),
    ("422", "A field needs a change. The answer says which field and what is wrong."),
    ("503", "A company node did not answer."),
]
STATUS_TEXT = {
    "ok": "The tool answered fully.",
    "partial": "The tool answered, but at least one company node did not answer.",
    "no_evidence": "The tool found nothing that answers the request.",
    "blocked": "The owners released nothing for this purpose.",
    "needs_input": "A choice is needed before the tool can answer. The problem lists the choices.",
    "refused": "An input is missing or wrong, or the id is not in the graph. The problem says what is needed and may suggest ids.",
}

GLOSSARY = [
    ("API", "Application programming interface: the routes a program calls to use NeuralMesh."),
    ("Route", "One method and path of the API, for example POST /api/v1/context-graphs/{graph_id}/query."),
    ("Bearer token", "A signed text sent in the header Authorization: Bearer and the token. Sign-in gives one that is valid for 12 hours."),
    ("Service token", "The token of a registered application, with the role context_client. In development it comes from python -m scripts.issue_service_token in the app folder."),
    ("Envelope", "The one request body of the context contract: schema_version, tool, purpose, caller and input."),
    ("Context contract", "The published set of 14 tools that applications call, version 1.1. Its sha256 lets an application see that it changed."),
    ("Purpose", "Why a call is made: problem_solving, compliance, bid_support, learning, career_mobility or inspection. Company nodes release data by purpose."),
    ("Caller", "In the envelope, the end user's company (subsidiary), their roles and, for a person, an opaque user reference (user_ref)."),
    ("Mesh", "The company nodes of the group joined through one central service."),
    ("Company node", "The server one company runs over its own documents, with its own rules and its own decision log. Not the same as a node of a graph."),
    ("Mesh graph", "The central graph of entities and links taken from the company nodes and the group vocabulary. It holds no document text."),
    ("Entity", "One item of the mesh graph: a company, a catalogue item, a document, a concept, a skill, a role, an expert or an asset."),
    ("Context graph", "A named graph of related inputs. Uploaded ones are made by Upload input from files. Ingested ones are written as JSON on Ingest data."),
    ("Node", "One thing in an ingested context graph, with a type and a name, for example a Supplier named Supplier X."),
    ("Edge", "One relationship between two nodes, with a type, a source and a target, for example Supplier X SUPPLIES Rotor seal RS-200."),
    ("Hop", "One edge walked from a node to its neighbour."),
    ("Path", "A chain of edges that joins two nodes. The path query gives the shortest ones."),
    ("Jaccard index", "The shared neighbours of two nodes divided by all the neighbours of the two, from 0 to 1. The similar query ranks by it."),
    ("Sensitivity", "Public, Internal, Confidential or Restricted. A missing one is Restricted."),
    ("Sharing", "company: only the owning company and mesh admins see an ingested graph. group: every company sees it."),
    ("Never-leave", "Items shown to other companies as a title only, such as formulations and finance before results."),
    ("Synthetic", "Data invented for testing. A cloud model may read synthetic data in development only."),
    ("Stand-in model", "The local model of the development stack. It writes answers from the evidence by fixed rules, with no cloud call."),
    ("MCP", "Model Context Protocol, the protocol AI agents use to call tools. The gateway serves it over HTTP at port 8100."),
    ("curl", "A command-line program that sends one HTTP request."),
]


# ── helpers ───────────────────────────────────────────────────────────────────────────────────────────────────────
FONT = "Arial"
MONO = "Courier New"
thin = Side(style="thin", color="D0D0D0")
BORDER = Border(left=thin, right=thin, top=thin, bottom=thin)
HEAD_FILL = PatternFill("solid", fgColor="DCE6F2")
GROUP_FILL = PatternFill("solid", fgColor="F2F2F2")


def _norm(path: str) -> str:
    return re.sub(r"\{(\w+):path\}", r"{\1}", path)


def check_routes() -> None:
    code = {(r["method"], _norm(r["path"])) for r in ROUTES}
    sheet = {(m, p) for _, m, p, *_ in R}
    if code != sheet or len(R) != len(ROUTES):
        sys.exit(f"The REST tab does not match the code. Missing: {sorted(code - sheet)}. Not in the code: {sorted(sheet - code)}")


def short(value, depth: int = 0):
    if isinstance(value, dict):
        return {k: short(v, depth + 1) for k, v in value.items()}
    if isinstance(value, list):
        kept = [short(v, depth + 1) for v in value[:2]]
        if len(value) > 2:
            kept.append(f"... {len(value) - 2} more")
        return kept
    if isinstance(value, str) and len(value) > 160:
        return value[:160] + " ..."
    return value


def as_text(value, limit: int = 1600) -> str:
    text = json.dumps(short(value), indent=1, ensure_ascii=False)
    return text if len(text) <= limit else text[:limit] + "\n... (shortened, the full answer is in source/recorded.json)"


def request_text(c: dict) -> str:
    from urllib.parse import urlencode
    line = f"{c['method']} {c['path']}" + ("?" + urlencode(c["params"]) if c.get("params") else "")
    if c.get("multipart"):
        return line + " (a form)\n" + ", ".join(f"{k}={v}" for k, v in c["body"].items())
    return line + ("\n" + json.dumps(c["body"], indent=1, ensure_ascii=False) if c.get("body") is not None else "")


def write_table(ws, top: int, headers: list[str], rows: list[list], widths: list[int], mono: set[int] = frozenset(), group_col: int | None = None) -> int:
    for i, h in enumerate(headers, 1):
        cell = ws.cell(row=top, column=i, value=h)
        cell.font = Font(name=FONT, bold=True, size=10)
        cell.fill = HEAD_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        cell.border = BORDER
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    r = top
    for row in rows:
        r += 1
        lines = 1
        for i, value in enumerate(row, 1):
            cell = ws.cell(row=r, column=i, value=value)
            cell.font = Font(name=MONO if i in mono else FONT, size=9 if i in mono else 10)
            cell.alignment = Alignment(wrap_text=True, vertical="top")
            cell.border = BORDER
            if group_col and i == group_col:
                cell.fill = GROUP_FILL
            text = "" if value is None else str(value)
            per_line = max(8, int(widths[i - 1] * (1.25 if i in mono else 1.15)))
            need = sum(max(1, math.ceil(len(part) / per_line)) for part in text.split("\n"))
            lines = max(lines, need)
        ws.row_dimensions[r].height = min(409, max(15, 12.6 * lines + 4))
    ws.freeze_panes = ws.cell(row=top + 1, column=1)
    ws.auto_filter.ref = f"A{top}:{get_column_letter(len(headers))}{r}"
    return r


def title(ws, text: str, note: str) -> None:
    ws["A1"] = text
    ws["A1"].font = Font(name=FONT, bold=True, size=14)
    ws["A2"] = note
    ws["A2"].font = Font(name=FONT, size=10, italic=True, color="555555")
    ws["A2"].alignment = Alignment(wrap_text=False, vertical="top")


def build() -> Workbook:
    check_routes()
    registry = {p.stem: yaml.safe_load(p.read_text()) for p in sorted(APPS.glob("*.yaml"))}
    wb = Workbook()

    # REST routes
    ws = wb.active
    ws.title = "REST routes"
    title(ws, "REST routes", f"Every route of the API, read from the code. Sent on {SENT_ON} to the running development API, on invented data, unless the last column says why not.")
    rows = []
    for n, (group, method, path, who, does, send, back, changes, ref) in enumerate(R, 1):
        if ref in CALLS:
            c = CALLS[ref]
            example_req, example_ans, checked = request_text(c), as_text(c["response"]), f"Sent: {c['status']}"
        else:
            example_req, example_ans = ref + "\n(an example, not sent)", "Not sent. The answer holds what the column What comes back says."
            checked = NOT_SENT
        rows.append([n, group, method, path, who, does, send, back, changes, example_req, example_ans, checked])
    write_table(ws, 3, ["No.", "Group", "Method", "Path", "Who can call it", "What it does", "What to send", "What comes back", "Changes data",
                        "Example request", "Example answer (shortened)", f"Checked on {SENT_ON}"],
                rows, [5, 20, 8, 34, 22, 48, 40, 40, 11, 46, 60, 16], mono={10, 11}, group_col=2)

    # Context graph queries
    ws = wb.create_sheet("Context graph queries")
    title(ws, "Context graph queries", "Every query is POST /api/v1/context-graphs/{graph_id}/query with one key in the body. The examples ask the graph cg-1cc11e1e, invented data.")
    rows = []
    for n, (want, kind, body, back, rules, ref) in enumerate(QUERIES, 1):
        c = CALLS[ref]
        rows.append([n, want, kind, body, back, rules, as_text(c["response"]), f"Sent: {c['status']}"])
    write_table(ws, 3, ["No.", "What you want to know", "Query kind", "Body to send", "What comes back", "Rules", "Example answer (shortened)", f"Checked on {SENT_ON}"],
                rows, [5, 26, 11, 40, 44, 52, 70, 14], mono={4, 7})

    # Ingest JSON fields
    ws = wb.create_sheet("Ingest JSON fields")
    title(ws, "Ingest JSON fields", "The JSON sent to POST /api/v1/context-graphs. When a needed field is missing or wrong, the answer is 422 with each place to fix, and nothing is kept.")
    write_table(ws, 3, ["Field", "Where", "Needed", "What it means", "When it is missing", "Example"],
                [list(f) for f in FIELDS], [22, 16, 14, 60, 48, 42], mono={6})

    # Contract tools
    ws = wb.create_sheet("Contract tools")
    title(ws, "Contract tools", "Each tool is POST /api/v1/context/{tool} with the envelope and an application's service token. The same tools, except import, are on the MCP gateway.")
    rows = []
    for n, (name, t) in enumerate(sorted(CONTRACT["tools"].items()), 1):
        inp = t["input"]
        req = set(inp.get("required") or [])
        fields = ", ".join(f"{k}" + ("" if k in req else " (if wanted)") for k in inp.get("properties", {})) or "Nothing"
        caller = {"person": "An end user (caller with user_ref)", "service": "The application itself", "either": "An end user or the application"}[t["caller"]]
        purposes = ", ".join(t["purposes"]) if isinstance(t["purposes"], list) else "Any purpose the application's registry allows"
        apps = ", ".join(a for a, reg in registry.items() if name in (reg.get("tools") or [])) or "None registered"
        reached = "REST only" if name == "import" else "REST and MCP"
        if name in TOOL_CALL:
            c = CALLS[TOOL_CALL[name]]
            example, answer, checked = json.dumps(c["body"], indent=1, ensure_ascii=False), as_text(c["response"]), f"Sent: {c['status']}, status {c['response'].get('status')}"
        else:
            example, answer, checked = json.dumps(TOOL_EXAMPLE[name], indent=1, ensure_ascii=False) + "\n(an example, not sent)", "Not sent. See What it gives.", NOT_SENT
        rows.append([n, name, TOOLS_TEXT[name], caller, purposes, fields, apps, reached, example, answer, checked])
    write_table(ws, 3, ["No.", "Tool", "What it gives", "Called for", "Purposes", "Input fields", "Applications that may call it", "Reached by",
                        "Example envelope", "Example answer (shortened)", f"Checked on {SENT_ON}"],
                rows, [5, 18, 46, 24, 22, 34, 20, 12, 52, 60, 18], mono={9, 10})

    # MCP gateway tools
    ws = wb.create_sheet("MCP gateway tools")
    title(ws, "MCP gateway tools", "AI agents call these at http://127.0.0.1:8100/mcp with an application's service token. Each answers exactly what the REST route of the same tool answers.")
    rows = [[n, name, TOOLS_TEXT[name], "purpose, caller, input, and schema_version (1.1 when missing)", "The same answer as POST /api/v1/context/" + name,
             "A fault of the token or of the envelope comes back as a tool error whose text is the problem as JSON."]
            for n, name in enumerate([t for t in sorted(CONTRACT["tools"]) if t != "import"], 1)]
    write_table(ws, 3, ["No.", "Tool", "What it gives", "Arguments", "What comes back", "When something is wrong"], rows, [5, 18, 56, 40, 40, 50])

    # Company node tools
    ws = wb.create_sheet("Company node tools")
    title(ws, "Company node tools", "Each company node (ports 8101 to 8108 in development) serves these tools to the centre only, with a node token the centre makes for each call. Applications never call them directly.")
    rows = [[n, name, does, args, "The central NeuralMesh service only", "8101 to 8108"] for n, (name, does, args) in enumerate(NODE_TOOLS, 1)]
    write_table(ws, 3, ["No.", "Tool", "What it does", "Arguments", "Who calls it", "Ports"], rows, [5, 22, 64, 40, 30, 14])

    # Answers and errors
    ws = wb.create_sheet("Answers and errors")
    title(ws, "Answers and errors", "What the HTTP status of an answer means, the statuses of a contract answer and the problem codes it can carry.")
    end = write_table(ws, 3, ["HTTP status", "What it means"], [list(x) for x in HTTP_CODES], [20, 100])
    top = end + 2
    end = write_table(ws, top, ["Contract status", "What it means"], [[s, STATUS_TEXT[s]] for s in CONTRACT["statuses"]], [20, 100])
    top = end + 2
    rows = [[code, str(p["http"]), p["status"] or "None, the HTTP status says it", p["title"]] for code, p in CONTRACT["problem_codes"].items()]
    write_table(ws, top, ["Problem code", "HTTP status", "Contract status", "What it means"], rows, [24, 12, 30, 100])
    ws.freeze_panes = "A4"
    ws.auto_filter.ref = None
    top = ws.max_row + 2
    refused = CALLS["cg_refused"]
    ws.cell(row=top, column=1, value="An example 422").font = Font(name=FONT, bold=True, size=10)
    cell = ws.cell(row=top, column=2, value=as_text(refused["response"]))
    cell.font = Font(name=MONO, size=9)
    cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[top].height = 140

    # Glossary, the last tab
    ws = wb.create_sheet("Glossary")
    title(ws, "Glossary", "Every term of this workbook in plain words.")
    write_table(ws, 3, ["Term", "What it means"], [list(g) for g in GLOSSARY], [24, 110])

    # Read me, the first tab
    ws = wb.create_sheet("Read me", 0)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 120
    ws.column_dimensions["C"].width = 40
    ws["A1"] = "RPG NeuralMesh API: the complete list"
    ws["A1"].font = Font(name=FONT, bold=True, size=16)
    intro = [
        ("What this workbook is", "Every way to reach RPG NeuralMesh: the REST routes for people, the tools of the context contract for applications, the same tools over MCP for AI agents, and the tools each company node serves to the centre. Each row says who can call it, what to send, what comes back and gives an example."),
        ("When it was checked", f"The calls that only read were sent to the running development API on {SENT_ON}, and each example answer is the one the API gave. The data in them is invented for testing. Calls that change data were not sent, and their rows say so."),
        ("Address", "http://127.0.0.1:8000 for the REST routes in development. http://127.0.0.1:8100/mcp for the MCP gateway."),
        ("How to get a token", "A person signs in with POST /api/v1/auth/signin and sends the access_token in the header Authorization: Bearer <token>. It is valid for 12 hours. An application uses its service token. In development: python -m scripts.issue_service_token skillforge, run in the app folder."),
        ("How to send a call", "Use the example request of a row with curl, or open http://127.0.0.1:8000/docs in a browser, press Authorize and paste the token. The page RPG_NeuralMesh_API_How_It_Works_v1.html in this folder shows each important call with its curl command and its full answer."),
        ("Shortened examples", "Long answers are shortened: lists show their first 2 items and long texts are cut. The full answers are in source/recorded.json."),
    ]
    r = 2
    for label, text in intro:
        r += 1
        ws.cell(row=r, column=1, value=label).font = Font(name=FONT, bold=True, size=10)
        cell = ws.cell(row=r, column=2, value=text)
        cell.font = Font(name=FONT, size=10)
        cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.cell(row=r, column=1).alignment = Alignment(vertical="top")
        ws.row_dimensions[r].height = 12.6 * max(1, math.ceil(len(text) / 135)) + 4
    r += 2
    for i, h in enumerate(["Count", "Number", "Counted from"], 1):
        cell = ws.cell(row=r, column=i, value=h)
        cell.font = Font(name=FONT, bold=True, size=10)
        cell.fill = HEAD_FILL
        cell.border = BORDER
    counts = [
        ("REST routes", "=COUNTA('REST routes'!D4:D200)", "The tab REST routes"),
        (f"REST routes sent on {SENT_ON}", "=COUNTIF('REST routes'!L4:L200,\"Sent*\")", "The last column of REST routes"),
        ("REST routes not sent, because they change data", "=COUNTIF('REST routes'!L4:L200,\"Not sent*\")", "The last column of REST routes"),
        ("Context graph query kinds", "=COUNTA('Context graph queries'!C4:C100)", "The tab Context graph queries"),
        ("Ingest JSON fields", "=COUNTA('Ingest JSON fields'!A4:A100)", "The tab Ingest JSON fields"),
        ("Contract tools", "=COUNTA('Contract tools'!B4:B100)", "The tab Contract tools"),
        (f"Contract tools sent on {SENT_ON}", "=COUNTIF('Contract tools'!K4:K100,\"Sent*\")", "The last column of Contract tools"),
        ("MCP gateway tools", "=COUNTA('MCP gateway tools'!B4:B100)", "The tab MCP gateway tools"),
        ("Company node tools", "=COUNTA('Company node tools'!B4:B100)", "The tab Company node tools"),
    ]
    for label, formula, source in counts:
        r += 1
        for i, value in enumerate([label, formula, source], 1):
            cell = ws.cell(row=r, column=i, value=value)
            cell.font = Font(name=FONT, size=10)
            cell.border = BORDER
            cell.alignment = Alignment(horizontal="left", vertical="top")
    r += 2
    for i, h in enumerate(["Tab", "What it holds"], 1):
        cell = ws.cell(row=r, column=i, value=h)
        cell.font = Font(name=FONT, bold=True, size=10)
        cell.fill = HEAD_FILL
        cell.border = BORDER
    tabs = [
        ("REST routes", "Every REST route: group, method, path, who can call it, what it does, what to send, what comes back, whether it changes data, an example request and answer, and whether it was sent."),
        ("Context graph queries", "The seven ways to ask an ingested context graph, with the body to send, what comes back, the rules and a real answer."),
        ("Ingest JSON fields", "Every field of the JSON that keeps a context graph: what it means and what happens when it is missing."),
        ("Contract tools", "The tools applications call: what each gives, for whom, with which purposes and input, which applications may call it, and an example."),
        ("MCP gateway tools", "The same tools for AI agents over MCP, except import."),
        ("Company node tools", "The tools each company node serves to the centre only."),
        ("Answers and errors", "What each HTTP status, contract status and problem code means, with an example of a refusal."),
        ("Glossary", "Every term of this workbook in plain words."),
    ]
    for name, text in tabs:
        r += 1
        for i, value in enumerate([name, text], 1):
            cell = ws.cell(row=r, column=i, value=value)
            cell.font = Font(name=FONT, size=10, bold=(i == 1))
            cell.border = BORDER
            cell.alignment = Alignment(wrap_text=True, vertical="top")
        ws.row_dimensions[r].height = 12.6 * max(1, math.ceil(len(text) / 135)) + 4
    wb.calculation.fullCalcOnLoad = True  # Excel, Numbers and Google Sheets compute the counts of Read me when the file opens
    return wb


if __name__ == "__main__":
    wb = build()
    wb.save(OUT)
    print(f"wrote {OUT}")
