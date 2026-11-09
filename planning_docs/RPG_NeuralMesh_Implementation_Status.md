# RPG NeuralMesh: Implementation Status of the Knowledge Mesh Plan v2

Branch `dev_raja`, 2026-11-05. Nothing is committed.

## What Is Built, by Phase

| Phase | Built | Where |
|---|---|---|
| 0 | One node registry read by the API, orchestrator, nodes and pack builder. A node starts from its registry entry with `python -m mcp_nodes <id>`, no module file. Node profiles from listed metadata. A development stack script (start, stop, status, restart a node, restart the API). Placeholders removed from `api/main.py` and the Makefile | `app/config/nodes.yaml`, `app/shared/registry.py`, `app/mcp_nodes/__main__.py`, `app/scripts/dev_stack.sh`, `app/Makefile` |
| 1 | 19 packs from the YAML, validated with the group packs. An embedded Chroma store per pack over the text the node may release (FAISS until 2026-11-05). Keyword search with Porter stemming, vector search and the routed concepts merged by reciprocal rank fusion. Purpose checked per datapoint. Every returned item is an evidence record. Canary check over the Chroma stores. Injection sentences removed from the text users receive, with the record flagged | `app/knowledge/`, `app/mcp_nodes/knowledge_view.py`, `app/contracts/evidence.py`, `app/neuralmesh_kb_pack/kbgen.py` |
| 2 | `export_graph` tool, central graph store with link reviews, loading from node exports and group packs, routing with the narrowing rule, classifier fallback, optional node choice, graph view and link approvals on the screens. Removed documents, roles and nodes are retired in the graph, never deleted | `app/services/graph_store.py`, `app/services/mesh_graph.py`, `app/api/routers/mesh.py`, UI pages |
| 3 | Scope (top 12 documents round-robin by node rank, re-rank that demotes but never drops, and never leaves an empty answer), expand with policy filter, context builder with budget and omission note, answer, seven code checks, model policy with strict mode, model-call audit, answer and re-rank caches | `app/services/context/`, `app/services/neuralmesh.py`, `app/config/model_policy.json` |
| 4 (NeuralMesh part) | Six context tools under `/api/v1/context` and on the MCP gateway, talent pack import, purposes `learning` and `career_mobility` | `app/services/context_api.py`, `app/api/routers/context.py`, `app/mcp_gateway/server.py` |

## Built on 2026-11-07: the Context Graph Platform, First Cut

| Part | What is in place | Where |
|---|---|---|
| Graph rules | One rules file per domain (`config/graph/core.yaml`, `inspection.yaml`): node types, edge types with the node types each may join, groups, derived edges, ownership of namespaces by source. The routing code reads its groups from the rules | `services/ontology.py` |
| Graph record contract | One shape for a node and an edge (schema version 1.0), exported as JSON schema files that other applications test against | `contracts/graph.py`, `contracts/schemas/` |
| Intake | Six checks (shape, type, signature, reference, duplicate, ownership), sorted normalised file per source, upsert, retire by source, revision counter. Every loader goes through it | `services/graph_intake.py` |
| Adapters | Knowledge pack, node export, CSV pair, JSON Lines, and the Snap and Score ontology file (loaded as proposed entries) | `knowledge/adapters.py` |
| Graph checks | Six rules after every refresh, shown on Mesh Nodes | `services/graph_intake.py`, Mesh Nodes page |
| One writer | The API writes the store. The gateway and every API worker rebuild their copy when the store's revision moved | `services/mesh_runtime.py`, `GraphStore.revision` |
| Identity rules | `/graph/refresh` needs the `mesh_admin` role. A link is approved only for the reviewer's own company. PyJWT replaces python-jose | `api/auth.py`, `api/routers/mesh.py` |
| Generic context tools | `entity`, `related`, `similar`, `live`, plus `inspection_profile`, `inspection_history` and `record_inspection` for Snap and Score, on REST and on the gateway (12 tools) | `services/context_tools.py`, `api/routers/context.py`, `mcp_gateway/server.py` |
| Inspection layer | The Snap and Score draft ontology as proposed entries, one grading standard per company in the node packs, a standards link pack, and live cover status looked up at the node (`lookup` tool) and never stored | `neuralmesh_kb_pack/applications/snapscore/`, `mcp_nodes/live.py` |
| Ask with context | `ask` takes an inspection context (asset, conditions, grade) and routes to the governing standards' owners as well | `services/neuralmesh.py` route step |
| Similarity layer | A job that scores pairs of the same kind by shared connections and by text, writes SIMILAR_TO links as proposed with the reason and score, retires what it no longer produces | `services/similarity.py`, `make similarity` |
| Labelled question set | 96 questions written by the answer model from the document summaries, with the expected document. Hybrid search: recall at 10 of 1.00 and nDCG at 10 of 0.87. Keyword search alone: 0.91 and 0.80 | `evaluations/labelled_questions.py`, `neuralmesh_kb_pack/kb/labelled_questions.yaml` |
| Tracing | One span per step, node call and model call, exported only when `NEURALMESH_OTEL_ENDPOINT` is set | `observability/tracing.py` |
| Build | Starter-template parts removed (Temporal, Postgres, Redis, Qdrant, Key Vault, the example agents, two template pages). `requirements.lock` pins every package. A CI workflow runs the tests, the pack validation, the type check and the build | `requirements.lock`, `.github/workflows/ci.yml`, `docker-compose.yml` |
| Pages | Domains (the layers and their rules with live counts) and Applications (SkillForge and Snap and Score, what each loaded and calls). The graph explorer draws the inspection kinds | `ui/src/pages/DomainsPage.tsx`, `ApplicationsPage.tsx` |
| Node server | Split into `server_config`, `search`, `experts`, `live` and the wiring in `server.py`, with the same import names | `mcp_nodes/` |

## Code Review of 2026-11-07

A reviewer read the new modules and reported 22 findings. 19 are fixed and tested: each inspection load no longer retired the earlier ones (incremental loads do not retire), a node may write only its own company entry and only entities marked as its own, a cross-company judgement link is proposed until both owners approve it, a link ID stored under another source is refused unless both sources own the namespace, an unknown source may write nothing, the revision is read in the same transaction as the graph, the store uses WAL with a busy timeout and closes its connections, retire-source runs in one transaction, routing walks only approved links to live documents and experts, a proposed link at a blocked company is hidden, reserved property keys are refused, approvals without a company key no longer break the load, the side of a link is its owning company, a datapoint without a domain gets no link, the similarity reason is stable across runs, retired vocabulary is not embedded, the vocabulary index is read under the lock, the rules groups are read at use, one bad application file no longer stops the load, the live lookup validates its file and audits a denied caller, an inspection needs an owner and an inspector of that company, the ask context is a typed model, the ID pattern uses a full match, and spans cover the fan-out search and the export.

Three findings stay open as design points: the graph read tools (`entity`, `related`, `similar`, the Domains and Applications pages) show metadata to any signed-in group user, which is the stated rule for the central graph but should be narrowed for entities of never-leave datapoints. The proposed entries of an application ontology have no approval path yet beyond the group link review. The behavioural similarity signal is not built.

Not done, because it needs something outside this machine: corporate sign-in (Entra ID) with a token per node, a graph database (no size trigger reached), a Raychem node (Raychem is a placeholder company entry from the Snap and Score file), a re-ranker or multilingual embedding model trial (model downloads), and the behavioural similarity signal (needs consented usage data).

## Built on 2026-11-08: One Contract for Every Application

The plan is `RPG_NeuralMesh_Generic_Context_Delivery_Standard_Plan.md`. A live check of 2026-11-07 had found that every SkillForge call failed: the two sides had built different request and answer shapes from their own readings of the strategy plan, and each tested only against itself. NeuralMesh now publishes one contract that every application follows, and SkillForge follows it.

| Part | Built | Where |
|---|---|---|
| Contract, version 1.1 | One request envelope for every tool, one answer with six statuses, a problem object with fixed codes and the field names of RFC 9457, a published bundle with its SHA-256 hash and a lock file, served at `GET /api/v1/context/contract`. The publishing script refuses a changed contract under an unchanged version | `app/contracts/context.py`, `app/contracts/schemas/context_contract.json`, `app/scripts/write_context_contract.py` |
| Application registry | One file per application: service identity, the companies it may speak for, its role names (`mesh_admin` is never granted through a request), purposes, tools, the entity types it may read, and the packs it may send with what each may hold. The Applications page reads the same files | `app/config/applications/`, `app/services/applications.py` |
| Catalogue and dispatcher | 14 tools declared once (6 generic operations and 8 plugins), one dispatcher behind the REST route and the MCP gateway, and every answer checked against the contract models before it leaves | `app/services/context_catalogue.py`, `app/services/context_dispatch.py`, `app/api/routers/context.py`, `app/mcp_gateway/server.py` |
| Refusals that say what is needed | `invalid_input` with the fields and allowed values, `not_found` with up to three closest ids by name (never a document, and only types the application may read), `company_not_connected`, `needs_choice`, `not_released`, `node_unavailable`, `pack_refused`, and the HTTP errors `unauthenticated` (401), `not_allowed` (403), `unknown_tool` (404), `not_an_envelope` and `unsupported_version` (400), `service_unavailable` (503) | the same files |
| Reads kept apart | entity, related, similar and the suggestions show only the entity types on the application's read list, and a document or datapoint only when its datapoint allows the purpose of the call | `CallContext.visible` in `app/services/context_catalogue.py` |
| Import tool | Replaces the talent pack route. Each pack is checked against its registry rule (types, own namespace, no approvals, only the company's own T-01 datapoint), then by the validator. A pack equal to the kept one is unchanged. Kept packs are written atomically, the affected node talent packs are rebuilt, the nodes read their changed pack files without a restart, and the graph is refreshed from the node exports. A pack whose node did not answer stays unrecorded and loads at the next send. A failure restores the kept packs and the node packs, and the import finishes even when the caller stops waiting | `app/services/context_import.py`, `rebuild_talent_packs` in `app/knowledge/packgen.py`, `LiveNode` in `app/mcp_nodes/server.py` |
| Hermetic tests | The tests run on a copy of the node packs with pinned sample talent packs, set through `NEURALMESH_DATA_PACK` and `NEURALMESH_TALENT_IMPORT`, so a live import cannot change what a test expects | `app/tests/conftest.py`, `app/tests/fixtures/` |

**SkillForge's packs are loaded.** SkillForge, running on a copy of its dev data, sent 8 packs through the import tool. NeuralMesh loaded 5: the group skill list (45 skills, kept as `group.skills`) and the talent packs of CEAT, KEC, Zensar and Harrisons (10 roles). It refused 3, because Asvata, Raychem and RPG Life Sciences have no Mesh Node. Roles that answered "Unknown role" on 2026-11-07, such as `zensar:role/data-engineer` and `kec:role/project-engineer`, now answer with their required skills. The files the import changed were backed up before it, in the session scratchpad.

**Verified on 2026-11-08**, on Claude Sonnet 5.5 after the cross-check fixes: 146 tests, live wiring 27 of 27, browser 23 of 23, and SkillForge's live contract test 10 of 10 against the running mesh. An independent cross-check walked the SkillForge pages against the running mesh and reviewed both changes. Its findings that were fixed: an import could carry a datapoint or approvals and change what a node shares, the read tools were not kept apart by application, an import counted as loaded when a node did not answer, the version lock did not stop a change, a failed import could leave node packs changed, the import blocked other calls, an internal error could reach the caller as its own fault, identity errors had no problem body, and SkillForge's reader refused the empty fields of an expert record.

Graph checks after the import: no dangling link, no wrong link type, one company link per role, no live link on a retired entity. 23 entities have no link, most of them group skills that no role of a connected company requires yet, and 2 concepts have no document.

Open points of this build, fixed later the same day: see the next section.

## Fixed on 2026-11-08: the Open Points and the Screen Review

The four open points of the contract build and the 11 defects of the screen review of 2026-11-07 are fixed.

| Defect | Cause | Fix | Where |
|---|---|---|---|
| "Similar roles" was empty for every role | `role_context` asked that the shared skills be 60 percent of the skills of both roles together. None of the 10 imported roles reaches it with another role | Two roles are similar when they share at least two required skills and these are at least half of the required skills of the smaller role. Skills a person joined with an approved SAME_AS link count as one skill. Zensar's Data Engineer now lists Software Engineer (2 shared skills of Software Engineer's 3) and GenAI Engineer (2 shared skills of the Data Engineer's 4) | `similar_roles` in `app/services/context_api.py` |
| A written answer opened with a sentence marked as not in the evidence | The example in the answer prompt put the `[NOT IN EVIDENCE]` sentence first, and the model copied the order. SkillForge also sent the learner's own skills question, which company documents rarely answer | Prompt `mesh_answer_v3` puts the sentences the evidence supports first, and the withheld and not-in-evidence sentences after them. SkillForge asks the role's company how it does the work of the role and what its documents say about the role's skills | `app/config/prompts/mesh_answer_v3.txt`, `written_question` in SkillForge's `app/services/role_answers.py` |
| A wrong argument to the MCP gateway came back as the MCP library's error text, and every tool error began with "Error executing tool" | The library checked the arguments against the tool's signature before NeuralMesh saw them, and it wraps a raised error in its own text | A gateway tool takes the arguments as they come and the dispatcher checks them, so a wrong field is the contract's `invalid_input` refusal. A fault of the identity or the envelope is returned as a tool error whose text is the Problem as JSON and nothing else. The tool list still shows the contract's input schema | `app/mcp_gateway/server.py` |
| Two API processes could import at the same time | The import lock held within one process only | An OS lock on a file in the import folder (`.import.lock`) covers every process, and the wait for it runs in a thread | `_folder_lock` in `app/services/context_import.py` |

The screen review, fixed in `app/ui`:

1. Applications: the latest inspection reads "7 Nov 2026, 20:25" in the viewer's time zone, not an ISO timestamp, and no longer runs past its card.
2. Applications: the facts sit in three columns (two on a phone), and each card keeps its own height.
3. Phone width (390 px): no page scrolls sideways, against 6 of 8 pages before. A wide table on Domains scrolls inside its own box.
4. Dashboard on a phone: the company table keeps its three columns. On every width the health shows as a badge, with the word the Mesh Nodes page uses.
5. Text: 12 px is the smallest size, and 11 px is kept for uppercase labels only. 93 sizes were raised.
6. Phone menu: the tab of the open page is scrolled into view, and both edges of the menu fade to show that it scrolls.
7. Titles: every panel and card title is 15 px bold.
8. Fonts: one sans-serif stack and one monospace stack, set as tokens and in the Tailwind file. The page no longer loads Plus Jakarta Sans and JetBrains Mono from Google Fonts.
9. Colours: the status colours are tokens (`--mesh-ok`, `--mesh-warn`, `--mesh-bad`), the accent is `--mesh-accent`, and a decision has one name and one colour on the Dashboard and in the decision log ("Blocked by policy" in red on both).
10. Focus: every link, button and field reached with the keyboard shows a 2 px outline in the accent colour.
11. Spacing: page buttons and fields are 36 px tall, the page heading sits 20 px above the first panel on every page, and the Dashboard stacks its panels in two columns, so no panel is stretched to the height of its neighbour.

The style rules of the original template, which no page used, are removed, and React Router's two warnings in the console are gone.

An independent review of these fixes, by three reviewers who reproduced each finding, found the following, now fixed as well:
- The demo accounts on the sign-in page were cut with an ellipsis at 12 px. They are now one full-width column.
- The word "symmetric" in the link table of Domains was 10 px. It is now 12 px.
- An import whose every pack was refused created the import folder and its lock file. The checks that need nothing kept (the registry rule, the node, the content rules) now run before any lock, so such a call writes no file.
- A wait for the folder lock that was cancelled when the process stopped closed its file while the waiting thread still used it. The file is now closed when the thread returns. The import module also loads where `fcntl` does not exist, with the lock held within one process there.
- A retired skill still counted as required. It is now left out of the required skills and of the similar-roles rule.
- The answer check split a sentence after "e.g." or "i.e.", so a cited sentence with such a word could fail the citation rule and the answer would not be shown. The split no longer ends a sentence after such an abbreviation, and the Ask page splits an answer by the same rule, with the `[NOT IN EVIDENCE]` marker kept in its sentence.
- The decision log showed dates in the browser's US form and its Decision column was off-screen on a phone. The dates now read "8 Nov 2026, 10:17:51" and the Decision column comes second.
- On a phone, the action button of a page heading now sits below the heading text, and the footer line of the sign-in page has a contrast above 4.5 to 1.

**Verified on 2026-11-08** after these fixes and the fixes of the review, on Claude Sonnet 5.5 and answer prompt v3: 154 tests, live wiring 29 of 29 (with two new checks of the gateway's faults over MCP), browser 23 of 23, golden scenarios 10 of 10, and SkillForge's live contract test 10 of 10. The reviewer's own probe found no cut text, no text under 12 px apart from the uppercase labels and no text under 4.5 to 1 contrast on the pages it covers. The screen review's script measured all 8 pages at 1280, 1500, 1920 and 390 px: no page scrolls sideways, no text is below 12 px except the uppercase labels at 11 px, every panel title is 15 px bold, every page button is 36 px, and the console is empty. Live answers on the new prompt for Zensar's Data Engineer, CEAT's Quality Engineer and Harrisons' Agronomist all open with cited sentences.

Still open:
- Roles of different companies are not similar on today's data, because their skills have different names on the group's skill list, for example CEAT's "Manufacturing" and KEC's "Manufacturing & Quality". They become similar when Group HR joins the names in SkillForge, which gives them one skill id in the talent packs, or when a person approves a SAME_AS link between the two skills in NeuralMesh.
- 23 entities had no link, most of them skills that only roles of companies without a Mesh Node required. The three wave 2 nodes of the next section brought this to 6.

## Built on 2026-11-08: Three Wave 2 Nodes

Raychem RPG, RPG Life Sciences and Asvata are Mesh Nodes now, three of the wave 2 nodes of the strategy plan v2. RPG Ventures, the fourth, has no node yet, and it is the example of a company without a node in the tests and the checks.

| Node | Port | Level | Content (synthetic) |
|---|---|---|---|
| Raychem RPG (`raychem`) | 8105 | L1 | 12 documents in 6 datapoints: joint and termination installation, tests before energising, transformer and switchgear connections, field service and failure analysis, application notes for electric mobility, lessons from field failures, and a restricted partner and pricing file (title only) |
| RPG Life Sciences (`rpgls`) | 8106 | L1 | 12 documents in 6 datapoints: batch records, line clearance, solvent handling and near misses, testing and out-of-specification results, cleaning validation and stability, batch release and corrective actions, change control and dossiers, the promotion code and sample handling for medical representatives, and a restricted inspection response file |
| Asvata (`asvata`) | 8107 | L1 | 12 documents in 6 datapoints: carbon accounting and data analysis methods, compliance checklists and a deadline calendar, client service and engagement practice, lessons from engagements, and a restricted contract file |

- Each node is built like the four before it, from one hand-written knowledge file (`app/neuralmesh_kb_pack/kb/<node>.yaml`) of invented content marked synthetic, with four experts (one opted out) and one canary in its restricted file. 24 new concepts are in the group vocabulary, and `kb/annotations.yaml` names the purposes of each datapoint, the concepts and skills each document explains, and the skill of each expert. Three AI writer agents drafted the files in parallel, each file passed a content check, and each was read before it was added.
- Asvata has no description in either application, so its profile comes only from the two roles SkillForge holds for it (Analyst and Associate). Raychem's real data waits for the terms with TE Connectivity, its joint-venture partner (strategy plan v2), so its content names no partner, brand or product.
- The registry (`app/config/nodes.yaml`) is the one list of companies again: sign-up reads its companies from it (`GET /api/v1/auth/companies`), and each node's colour on the screens comes from it through `/api/v1/mesh/nodes`.
- `python kbgen.py` rebuilt every node. The four existing nodes came out unchanged: their 77 generated files and their 19 packs are identical to the backup, SkillForge's talent included. The node data, the imported packs, the vocabulary, the annotations, the registry and the graph store were backed up before the rebuild, in the session scratchpad.
- SkillForge sent its talent packs again and the three new ones loaded. The graph holds 17 roles, 7 of them new, and the new documents explain their required skills, for example Good Manufacturing Practice at level A in two RPG Life Sciences documents. The entities with no link fell from 23 to 6.
- In SkillForge, Ask AI on RPG Life Sciences' Quality Assurance Officer shows the requirements, a written part cited from RPG Life Sciences' documents, and Production Chemist as a similar role.

**Verified on 2026-11-08** with seven nodes, on Claude Sonnet 5.5: 160 tests (the per-node tests run for seven nodes, and the test copy of the group skill list holds the 17 skills the new documents explain), live wiring 29 of 29, browser 23 of 23 (7 cards for 7 registered nodes), golden scenarios 10 of 10 (S3 now also draws on Asvata and RPG Life Sciences), SkillForge's live contract test 10 of 10, and the screen measurements of 8 pages at 4 widths with no sideways scroll.

Still open:
- RPG Ventures has no Mesh Node.
- The golden scenarios and the labelled questions do not ask about the new nodes yet.
- The content of the three nodes is invented. Real documents need the owners of each company, and for Raychem the joint-venture terms.

## Built on 2026-11-08: Never-Leave Rule, Review of Application Entries, Example Questions

| Change | What it does | Where |
|---|---|---|
| Never-leave entities | An entity of a never-leave datapoint (the datapoint, or a document in it) is shown in the central graph only to people of its company and to mesh admins: in the graph explorer, the links list, the read tools (entity, related, similar) and the evidence list of an expert. Anyone else learns of such a file only when the owning node reports it as withheld in an answer, which the node decides per question and audits. The counts on the Domains and Applications pages stay whole, because they name no entity | `never_leave_owner` and `shown_to` in `app/services/mesh_graph.py`, `CallContext.visible` in `app/services/context_catalogue.py`, `app/api/routers/mesh.py` |
| Review of application entries | The 213 links Snap and Score proposed can be reviewed now. Each entry is approved by its sides: the company of each end that has a Mesh Node, and the group, which a mesh admin approves as curator, for an end of the application's own vocabulary. An entry is approved when every side approved it, and rejected when one side rejected it. `GET /api/v1/mesh/proposals` lists the entries by application and link type, `POST /api/v1/mesh/proposals/review` approves or rejects the reviewer's own sides for named entries or for a whole group, and Governance has a tab "Application entries". As for links between companies, the review is simulated for local demo accounts | `review_sides` and `review_links` in `app/services/graph_store.py`, `proposals` in `app/services/mesh_graph.py`, `app/ui/src/pages/GovernancePage.tsx` |
| Example questions for the new nodes | Golden scenarios S11 to S15 (one question for each new node, and two that ask for a restricted file) and 66 reworded questions (two for each of the 33 non-restricted documents of the three nodes), written by an AI agent and appended to the existing ones | `kb/golden.yaml`, `kb/labelled_questions.yaml` |
| Answer prompt v4 | Prompt v3 put the not-in-evidence and withheld sentences after the cited ones in every answer. A question that asks only for a restricted file then opened with loosely related content, and in one run the model wrote an uncited sentence about the evidence, so the check hid the answer. Version 4 opens with what answers the question: those two sentences come first when they are the main ask, and after the cited ones when only a part is missing | `app/config/prompts/mesh_answer_v4.txt` (v3 kept) |

- Six wordings of questions that ask only for a restricted file of CEAT or RPG Life Sciences were all answered on v4, each opening with the not-in-evidence and withheld sentences. A question with one missing part opened with the cited checks.
- Hybrid search finds the right document in the top 10 for all 162 labelled questions (recall 1.00), and keyword search alone for 0.94 of them.
- SkillForge's service token for NeuralMesh lasts 12 hours (`scripts/issue_service_token.py`). When it expired, SkillForge's calls were refused with `unauthenticated` until a new token was issued. A deployment needs tokens that renew, which belongs with the corporate sign-in.
- Two of the three open design points of the code review of 2026-11-07 are done: the never-leave narrowing and the review of application entries. The behavioural similarity signal is still not built.

**Verified on 2026-11-08** on Claude Sonnet 5.5 and prompt v4: 167 tests, live wiring 34 of 34 (with S11 to S15), browser 23 of 23, golden scenarios 15 of 15, SkillForge's live contract test 10 of 10, and the Governance tab at 1500 and 390 px for a CEAT reviewer and for the presenter: 8 groups, no sideways scroll, and actions only for the person's own sides.

## Fixed on 2026-11-08 (Evening): Findings of the Realistic Test

A test with real models (Claude for NeuralMesh, Azure gpt-4.1-mini for the SkillForge copy) by three testers found one serious problem and a set of smaller ones. These are the NeuralMesh changes. The SkillForge changes are in the copy `test-maker-skillforge-copy` and in its handoff.

| Finding | Change | Where |
|---|---|---|
| A skill join in SkillForge broke the talent import. Group HR joined "Professional Workplace Skills" into "Professional Workplace", SkillForge's skill list stopped defining the old id, two Raychem documents still explained it, and every send was refused with "Send it again later" | The pack format has a field `replaces` on an entity: the ids of entries joined into it. Every reference to a replaced id in any pack means the entity that replaces it. The validator resolves such references and errs on a replaced id that is still defined or claimed twice. The central graph drops a replaced entity and moves every link to it onto the entity that replaced it, and a skill lookup by the old id finds the kept skill. SkillForge's group pack lists `replaces` on a joined skill | `knowledge/validator.py` and its copy in `planning_docs/knowledge_pack_format`, both schemas, `to_networkx` in `services/graph_store.py`, `_current` in `services/context_api.py` |
| The import checked only the group packs and the kept talent packs, so a broken reference showed only at the rebuild | The import checks strictly what the rebuild will build: the talent packs of the affected nodes rebuilt with the incoming packs, every other node pack on disk and the group packs (`packgen.plan_talent_packs`, which writes nothing). A reference no pack defines is refused with its name and the packs that use it, blamed on the incoming pack that uses it, else on the incoming group pack, and the rest are checked again without it. A check that fails at the rebuild names its reason. "Send it again later" is kept for a failure that passes, such as a node that did not answer | `_validate` and `_apply` in `services/context_import.py`, `knowledge/packgen.py` |
| The Applications page said "8 packs received" while packs were refused | Each call of the import tool is recorded per application (table `import_sends` of the graph store). The page shows the packs kept, when one last loaded, and the latest send with loaded, unchanged and refused counts and the reason of each refusal | `record_send` in `services/graph_store.py`, the applications route in `api/routers/mesh.py`, `ui/src/pages/ApplicationsPage.tsx` |
| A question whose wording matched no company ended with "No node matched" | It goes to the asker's own company when that company has a Mesh Node, and the routing line says "No company matched the wording, so your own company was asked". For an asker whose company has no node, the company list opens for a choice | `route` in `services/neuralmesh.py`, `ui/src/pages/AskPage.tsx` |
| An answer that failed a check was hidden with "failed 1 check(s)" | The model writes the answer once more with each broken rule named. When the second answer still fails, the page gives the reason in words, for example that the answer did not show both sides of a conflict between two documents | `build_answer` in `services/neuralmesh.py`, `fix_line` and `plain_reason` in `services/context/check.py` |
| With companies chosen, an approved link still quoted a company that was not chosen | A link with an end outside the chosen companies is hidden | `expand` in `services/mesh_graph.py` |
| Governance said "Approved by" before anyone approved, and offered review buttons on other companies' requests | The group header reads "Needs approval from" while entries are proposed. A request is reviewed by its owning company or by a mesh admin, in the API and on the page, which shows "Waiting for <company>" to others | `ui/src/pages/GovernancePage.tsx`, `review_access_request` in `api/routers/mesh.py` |
| Small texts | "1 company", a citation without its chunk number, company names in Recent decisions, and company chips with a check mark when chosen and a hollow dot when not | `AskPage.tsx`, `DashboardPage.tsx`, `index.css` |

- After both changes the copy of SkillForge sent its packs: the skill list and Raychem's pack loaded, the other six were unchanged, and the routing line shows one skill, "Professional Workplace".

A second round followed three checks by agents: a NeuralMesh UI walk-through as first-time users, a SkillForge journey test with real models, and a goal check against the plans with a review of the first round's code.

| Finding | Change | Where |
|---|---|---|
| A role that required both the old and the kept skill got the requirement twice after a join | A link moved onto the replacing entity is left out when a live link of the same type joins the same ends. A chain of joins resolves to its end, and the names of a replaced entry stay names of the entry that took its place | `_replacements` and `to_networkx` in `services/graph_store.py` |
| Any `ValueError` at the rebuild, such as a file that did not parse, was answered as a permanent refusal | Only `PackCheckFailed`, the failed strict check of the packs, is permanent. Anything else says to send again | `knowledge/validator.py`, `knowledge/packgen.py`, `services/context_import.py` |
| The Applications page showed a refusal of the live check's test pack as SkillForge's latest send | The page keeps the latest result of each pack the registry allows the application to send, so a test pack with another id changes nothing. It shows the latest send and the packs refused and not loaded since, or "Every pack it sent is loaded." | table `import_pack_results` in `services/graph_store.py`, `api/routers/mesh.py`, `ApplicationsPage.tsx` |
| The capabilities of a node named its never-leave datapoints to every group user | A node lists a never-leave datapoint only to its own company and to mesh admins, and its profile, which every group user and the router read, leaves such datapoints and their concepts out | `capabilities_payload` and `node_profile` in `mcp_nodes/server_config.py` |
| An answer whose matching documents were all withheld for the purpose ended with "No evidence was released" | It says the matching documents are not shared for that purpose and to ask again with another purpose | `build_answer` in `services/neuralmesh.py` |
| The expert finder listed profiles that shared one word, or only "of", with the question | Words such as "of" and "the" never match, and a question of three or more words needs two matching words or a concept of the expert's evidence. An expert of the asker's own company is marked "your company" | `mcp_nodes/experts.py`, `ExpertFinderPage.tsx` |
| Codes and ids a first-time user cannot read | Citations show as the numbers of the evidence cards, a sentence the evidence does not hold starts with "Not in the evidence:", the ways of sharing show in words (Title only, Approved summary, Document passages, Live lookup), withheld reasons and rules show in plain words, access requests say who asked and who decides, node cards show their knowledge packs instead of a port, and each graph check that finds items says what to do | `ui/src/lib/format.ts`, `AskPage.tsx`, `GovernancePage.tsx`, `MeshNodesPage.tsx`, `graph_checks` in `services/graph_intake.py` |
| The decision log showed only a "Hash chained" badge | It explains the chain, and "Check the chains" recomputes the chain of every node's ledger and says whether it is intact | `GET /api/v1/mesh/governance/audit/verify` in `api/routers/mesh.py`, `GovernancePage.tsx` |
| With companies chosen, a link to a skill or concept would have been hidden | An end of shared vocabulary belongs to no company, so a choice never hides it | `expand` in `services/mesh_graph.py` |
| `make eval-recall` stopped at the new scenarios S11 to S15 | It leaves out scenarios without reworded questions and names them | `evaluations/reworded_recall.py` |

- By design and not changed: an answer to a person of another company can name a never-leave document as withheld (the owning node reports it per question and audits it), and an answer routed by the graph lists the approved links of its documents. Both are in the open points.
- Not changed: the synthetic text "qms.db" in a CEAT document, which needs a full rebuild of the knowledge packs.

A third round followed a workflow of eight agents: a code review of each app, a NeuralMesh UI walk-through and a SkillForge journey test, with a second agent checking every medium finding.

| Finding | Change | Where |
|---|---|---|
| A question that names one skill of an expert ("Who knows traceability best?") found nobody, because the Expert Finder page passed no concepts and filler words raised the bar | A word of an expert's listed skills counts 2, a word only of the job title 1, a word almost every title has ("lead", "manager") nothing, and a phrase of the title in the question 1. The page passes the concepts the mesh finds in the question, lists evidence by title, and leaves out a never-leave document of another company | `mcp_nodes/experts.py`, `search_experts` in `api/routers/mesh.py`, `ExpertFinderPage.tsx` |
| A moved link that duplicated a written link was dropped even when it was the approved one | An approved moved link replaces a written link of the same type that is still proposed | `to_networkx` in `services/graph_store.py` |
| The hint to try another purpose came also when other rules held documents back | The hint comes alone only when every withheld item is a purpose refusal, and names both kinds otherwise | `build_answer` in `services/neuralmesh.py` |
| A withheld item had two reasons on the Ask page, the model's "metadata-only" with an id in the answer and the plain one in the panel | The answer's withheld sentence shows the plain reason, without the id | `plainWithheld` in `ui/src/lib/format.ts` |
| Pages a first-time user could not read | The note under a node's capabilities says that titles of withheld documents can show, the header says documents stay at the node, the profile and the level read in words, the Application entries tab says what an entry is and names the kinds at both ends of each group, the ledger shows datapoint titles (never a never-leave title of another company), a link found by text extraction says so, "reused" says from what, and the routing line names its topics | `MeshNodesPage.tsx`, `GovernancePage.tsx`, `AskPage.tsx`, `governance_snapshot` and `application_proposals` in `api/routers/mesh.py` |
| The chain check failed as a whole when one node's configuration did not load | Each node is checked on its own, off the event loop | `verify_audit_chains` in `api/routers/mesh.py` |
| The published copy of the pack format still named FAISS and missed the purpose "inspection" | The published schema is the schema the app uses, and its example names the Chroma store | `planning_docs/knowledge_pack_format` |

- The two SkillForge instances on this machine both sent their talent packs hourly to the mesh as SkillForge, so the original's list (45 skills, no join) replaced the copy's list (44 skills, two joins) at 21:09. The original SkillForge API and UI, started for its contract test earlier in the session, were stopped, and the copy sent its packs again. A deployment has one SkillForge per mesh.

A fourth round followed a last check of four agents (a code review of both apps, a live pass as a first-time user, and a second agent on each medium finding).

| Finding | Change | Where |
|---|---|---|
| The Expert Finder answer filtered never-leave evidence in its flat list only, so the list of each node still carried the ids of never-leave documents of another company | Every expert passes the filter in both lists | `search_experts` in `api/routers/mesh.py` |
| A concept of a never-leave document raised an expert's score for a reader of another company | Such a concept counts only for the node's own company and mesh admins, and a phrase of a job title made only of generic words ("head of") counts nothing | `mcp_nodes/experts.py` |
| An approved link moved by a join removed a written link that a person had rejected | It replaces only a written link that is still proposed. A rejection keeps its decision | `to_networkx` in `services/graph_store.py` |
| Words a first-time user could not read | A withheld sentence reads "Withheld: <title>. <reason>." without nested brackets, the ids under an approved link moved into its tooltip, "Also found" reads "Found, not used in the answer", the ledger names its actions in words and marks a hidden datapoint "kept at <company>", the Dashboard shows levels in words and "Source records copied to the centre", the Domains page lists link kinds in words with a line on what each group means, and the Application entries tab says what its counts and buttons cover | `ui/src/lib/format.ts`, `AskPage.tsx`, `GovernancePage.tsx`, `DashboardPage.tsx`, `DomainsPage.tsx`, `governance_snapshot` in `api/routers/mesh.py` |

**Verified on 2026-11-08 (evening), on the final code:** 179 tests, live wiring 34 of 34, golden scenarios 15 of 15, browser 23 of 23, the UI build, reworded recall 12 of 18 (keyword search alone 7 of 18), SkillForge's live contract test 10 of 10 from the copy, and a probe of the live pages as kec.expert and the presenter (withheld sentences, links, ledger, Dashboard, Domains). Three rounds of agent checks (15 agents in all) found the defects listed in this section. The last live pass found no high or medium defect, and its code review found the expert-list leak above. Not verified: a failed answer check in the live app (it did not occur), approving an introduction and the name reveal, and the pages at 390 px other than Ask, Governance, Applications, Mesh Nodes, Dashboard and Domains.

## Checks Run on 2026-11-05

| Check | Result |
|---|---|
| Test suite (`make test`) | 115 passed on 2026-11-07, including the 44 tests that existed before |
| Golden scenarios through the running API with no node chosen (`python -m evaluations.golden_answers`) | 10 of 10 meet their expectations. S1 holds 4 of the 7 gold numbers of its cited datapoints, S3 1 of 2 |
| Live wiring check of the API, gateway and nodes (`make live-check`) | 24 of 24, including an expired token, 20 parallel queries with the audit chain intact, and the check step catching three stand-in misbehaviours |
| Reworded golden questions (`make eval-recall`), every required datapoint in the top 10 | Keyword search alone 7 of 18, hybrid search 12 of 18 |
| Browser check of the UI in Chromium (`evaluations/ui_render_check.mjs`) | 22 of 22 on the Ask page, Mesh Nodes with the graph explorer, Governance and the Dashboard. Screenshots in `app/.neuralmesh/screenshots` |
| Node outage (S7), live, with the KEC node stopped | Status partial, KEC marked unavailable, evidence from CEAT and Zensar |
| Verification run of 17 agents on the live stack | 12 verifier reports, 7 update-and-regenerate flows each restored and proven, 36 claims re-run by skeptics with 3 refuted. All three refutations are closed by the changes below |

The update-and-regenerate flows that were run and restored: a new document in one node, a new alias in the group vocabulary, a talent pack import with a new role, approval and rejection of a link between two subsidiaries, an access grant that releases a gated body and its revocation, a fifth node added from a registry entry and a pack and removed again, and a node outage with the stand-in's misbehaviours against the check step.

## The Answer Model During Verification

No model key exists on this machine and no local model runtime is installed, so the answer path ran against a stand-in server (`app/evaluations/standin_model_server.py`, policy `app/config/model_policy.dev-standin.json`). The stand-in is not a language model. It composes an answer from the evidence in the prompt by rule, marks a document relevant in the re-rank step when it shares a word stem with the question, and can be switched into eight misbehaviours. It proves that the policy, budget, audit, check, cache and screens work around a model. It proves nothing about the wording a real model would produce. The default policy file still names the group gateway and the Groq development model, and the stand-in policy is chosen only through `NEURALMESH_MODEL_POLICY`.

## Changes Made After the Verification Run

- Since 2026-11-06 the development answer model is Claude Sonnet 5.5 through the Anthropic SDK (policy entry `claude-dev`, key in `app/.env`). With it, 8 of the 9 golden questions that release evidence are answered and checked, and the ninth is evidence only because nothing was released. The prompt was `mesh_answer_v2` (one citation per sentence, exact forms for a withheld item and for a fact the evidence does not hold). Since 2026-11-08 it is `mesh_answer_v3`, which puts those two forms after the sentences the evidence supports. The answer check's sentence splitter no longer splits on the `[NOT IN EVIDENCE]` marker, and "reason" is an allowed word in a withheld sentence. The three prompts (answer, re-rank, classify) are versioned files in `config/prompts`, one registry names them, every model-call audit line carries the prompt version, and the response lists the seven steps with their durations. The flow has no LangGraph checkpointer by design: a question is one short run, and a checkpointer would persist evidence text outside the owning node.
- The vector index of each pack is an embedded Chroma store in place of the FAISS file and its chunk table. On all 30 golden and reworded questions over the 19 packs, Chroma returned the same documents in the same order as FAISS, with no score difference to four decimals. A rebuild embeds only new or changed chunks. Chroma rewrites its files when a store is opened, so the stores are generated by `python -m knowledge.packgen` and kept out of git, and `scripts/dev_stack.sh start` builds any that are missing.
- A company entry comes only from that company's node export. The group vocabulary pack adds it only before the node has exported, so "Harrisons" or "KEC" alone narrows a question again.
- A role has one ROLE_AT link to its company, written by the node export and the talent pack under one ID and retired with the last source that lists the role.
- Every record of the context tools and of `/mesh/query` follows the evidence record contract: expert details sit in the expert field, `explains_level` and `delivery` are contract fields, the `withheld` list holds evidence records, and `/mesh/query` states `schema_version` 1.0.
- Withheld metadata items carry the decision about their content (`BLOCKED_BY_POLICY` with the rule), not `ALLOWED`.
- The check step gained rule 3 for invented content attributed to a withheld item and rule 7 for more than 10 sentences. Both are caught live.
- A sentence of instruction-like text is removed from the evidence users and SkillForge receive, and the record stays flagged.
- When the re-rank rejects every document, the top three stay selected, and the answer reason tells the two cases apart.
- The keyword index uses Porter stemming, so "failures" finds "failure reports".
- Documents are selected round-robin by each node's own rank, so one node cannot crowd out another.
- Re-rank verdicts are cached, so an identical query makes no model call at all.
- A document removed from a node, a role removed from a talent pack and a node removed from the registry are retired in the graph, including the subsidiary entity and the structural relationships that touch them, and retired entities leave the graph view and the context tools.
- A stopword-only query is an empty query. The summarize citation uses the bare document ID. Role profiles are not offered as study material. The routing preview says when the classifier would take over.
- The Ask page, the Dashboard and the scope list read the node list from the API, the Governance buttons name the company, the links panel shows titles, and the omission note says when an item was replaced by a newer version.

## Where the Build Differs From the Plan

- **Meaning match threshold 0.45, not 0.6.** A whole question scores about 0.5 against the right concept and under 0.3 against an unrelated one, so 0.6 never matched.
- **Keyword index per node, vector index per pack.** The FTS5 index stays at `data_pack/<node>/index.db` as before, now with Porter stemming. Chunks have no overlap, so a keyword row and a vector row share one ID and fuse.
- **Skills belong to a `group.skills` pack.** The 7 skills moved out of the mesh vocabulary into `neuralmesh_kb_pack/talent_import/group.skills.pack.json`, which SkillForge's export replaces. The `ceat.talent` pack there is also a sample until SkillForge exports it.
- **18 reworded questions, not 20.** S4 is judged on experts, so it is left out of the recall measure. S11 to S15 have no reworded questions, so the measure covers S1 to S10 and names the scenarios it leaves out (on 2026-11-08: hybrid search 12 of 18, keyword search alone 7 of 18). The labelled questions cover the documents of the wave 2 nodes.
- **Cloud model and Confidential evidence.** The policy file keeps the plan's rule: no Confidential or Restricted record goes to a cloud model, in development too. With a Groq key only Internal bundles get a written answer.
- **Canary list at the centre.** In development the check step reads the canary strings of the synthetic packs. A real deployment has no canaries.
- **Seven check rules, not six.** Rule 7 limits the answer to 10 sentences, the limit the prompt states.
- **Similar roles by shared skills, not 60 percent.** The strategy plan v2 (`RPG_NeuralMesh_Knowledge_Mesh_Strategy_Plan_v2.md`, the SIMILAR_TO row) counts two roles as similar when their shared skills are 60 percent of the skills of both roles together. The build counts them as similar when they share at least two required skills that are at least half of the required skills of the smaller role, because no pair of the imported roles reached 60 percent.

## Not Done

- Phase 5: Entra ID, Neo4j, the link extraction job, the RPG Ventures node, and real data for the wave 2 nodes.
- The 10-second median answer time is not measured. Since 2026-11-06 the answers are written by Claude Sonnet 5.5, and no series of timed questions was run.
- Aggregate views (LIVE mode) as evidence of kind `aggregate` in a query. The numbers of the views reach answers through the approved summaries only.
- The 50 labelled CVs for the precision measure of journey B, and learning releases of journey C (a copy of another company's material into a topic until a date, after the owner's approval). SkillForge's talent packs (17 roles from a copy of its dev data) are loaded, and journeys A, B and C run in SkillForge, which reads material by reference.
- The Expert Finder card shows role, company, skills and evidence, not the pseudonymous expert ID. The scope presets of the top bar other than "All connected companies" are fixed lists.
- The embedding model is read from Chroma's cached ONNX copy on this machine. Another machine needs `NEURALMESH_EMBEDDING_MODEL_DIR`.

## Open Points for the Product Owner

- Should single words such as "latex" or "cold-chain" resolve to a concept, or should the vocabulary hold phrases only? Today a question with no matching phrase goes to the classifier and then to the user's own node choice.
- Should the aggregate views of O-05, E-02 and O-06 be returned as evidence by a query, as the golden file's `must_include_data` suggests?
- Should the Expert Finder show the expert ID next to the role?
- Should the name of an expert of the asker's own company show at once? Today every name needs an approved introduction, and the card marks a colleague with "your company".
- An answer routed by the graph lists the approved links of its documents, so it can name a document of a company that was not asked (both owners approved the link). Only a person's own choice of companies hides such links. Is that the intended reading of a link approval?

## Interface for Applications

- **The contract.** `POST /api/v1/context/<tool>` with one envelope (`schema_version`, `tool`, `purpose`, `caller`, `input`) and one answer (`status`, `records`, `answer`, `also_found`, `omitted`, `data`, `problem`, `trace_id`). The bundle at `GET /api/v1/context/contract` holds every schema and its hash. An application keeps a pinned copy and tests against it. SkillForge's copy is `app/contracts/neuralmesh_context_contract.json` in its repository.
- **The registry.** An application is one file in `app/config/applications/`. NeuralMesh checks every call against it.
- **Talent packs.** SkillForge sends them every hour through the import tool. NeuralMesh keeps the group pack as `group.skills`, loads a company pack through that company's node, and answers per pack: loaded, unchanged or refused with the reason.
- **Service token.** `python -m scripts.issue_service_token [application]` in development.

## How to Run the Stack

From `app/`: `bash scripts/dev_stack.sh start` starts the stand-in model, the seven registered nodes, the API with the stand-in policy, the gateway and the Vite UI. `make test`, `make live-check`, `python -m evaluations.golden_answers`, `make eval-recall` and `evaluations/ui_render_check.mjs` are the checks. `bash scripts/dev_stack.sh stop` stops everything.
