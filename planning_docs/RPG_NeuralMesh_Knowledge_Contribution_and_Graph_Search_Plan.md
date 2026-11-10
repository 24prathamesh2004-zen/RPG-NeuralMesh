# RPG NeuralMesh: Knowledge Contribution and Graph Search

Date: 2026-11-09.

## Where It Stands

Built on 2026-11-09, the same day: steps 2, 4 and 5 for a mesh admin who uploads a file (text, Markdown, CSV, JSON, PDF or Word), with the document accepted at once, the graph part of each upload shown and downloadable as JSON, GraphML, CSV or a knowledge pack, and the Context graph page with the tabs Uploaded inputs, Add input and Search the graph. Not built: step 1 (templates of fields per kind, the kind is chosen from the 12 of the pack schema), step 3 (the review by the item's owner, and uploads by a person who is not a mesh admin). The state is recorded in `RPG_NeuralMesh_Implementation_Status.md`.

## Goal

A person of a company adds a piece of knowledge from the NeuralMesh screens, in the shape of a template the company keeps, and it reaches the company's own Mesh Node, its search index and the central context graph by the same path the built-in packs use. Any signed-in person can search the context graph by a word or phrase and see the entities, their links, the company that owns each one and the sharing rule that applies, and then ask a question about what they found. Nothing written by a person leaves the company before the owner of its catalogue item has accepted it.

## Contents

1. What exists today and what is missing
2. The five steps
   - 2.1 Templates: the shape of one kind of input
   - 2.2 The contribution: from a filled template to a document on the company's node
   - 2.3 Review by the catalogue item's owner before the group sees it
   - 2.4 Into the index and the graph by the existing path
   - 2.5 Graph search for people
3. Roadmap
4. Sources

```
  person of CEAT                  CEAT node (inside CEAT)                     central mesh
  ─────────────                   ───────────────────────                     ────────────
  picks a template  ──►  Add knowledge page  ──►  add_document tool  ──►  contributions/<id>.json   (pending)
  fills its fields        (shows the sharing        (CEAT identity only)          │
  picks the item           rule of the item)                                      ▼
                                                                    owner of the item accepts ──► ceat.contributed pack
                                                                                                   rebuilt: index rows,
                                                                                                   vectors, pack.json
                                                                                                          │
                                                                            node export  ◄────────────────┘
                                                                                 │
                                                                                 ▼
                                                               central graph: Document, MENTIONS, EXPLAINS
                                                                                 │
  any signed-in person  ──►  Search the graph page  ──►  /mesh/graph/search  ◄───┘
                             entity, links, owner, rule, "Ask about this"
```

## 1. What Exists Today and What Is Missing

Today every document in the mesh was written into a YAML file by the development team and built into packs by `kbgen.py`. The data is invented and marked synthetic. No document was collected from the web. The document `RPG_NeuralMesh_Data_Prerequisites_and_Public_Sources.md` lists public reports of the group companies that could seed the first real catalogues, found by web search on 2026-11-06, but none was downloaded or loaded.

| Part | Today | Gap |
|---|---|---|
| Where knowledge comes from | `kb/<node>.yaml` written by hand, built by `kbgen.py` into `data_pack/<node>/packs/<domain>/pack.json`, `index.db` (keyword index) and `packs/<domain>/build` (vectors). Applications send packs through the `import` tool with a service identity | A person has no way to add a document. The import tool is for applications and their registry rule, not for people |
| The shape of a document | The pack schema fixes the fields: id, catalogue item, title, kind (one of 12: sop, rca, playbook, post_mortem, standard, report, policy, wiki, aggregate, note, study_material, role_profile), version, tags, summary, body, concepts, skills | A kind is one word. Nothing says what an RCA must contain (the problem, the cause, the fix, the date it was checked), so two people write two different RCAs |
| What the group may see | Each catalogue item carries a ceiling (title only, summary, full text, live) and purposes. The node applies it on every search | Works, and a contribution must land under an existing item so that the same rule applies. There is no step where the item's owner sees a new document before it is shared |
| Rebuilds | `rebuild_talent_packs` rebuilds one pack from kept imports, writes it beside the old file and renames it, and the node reads the new file without a restart | Only the talent pack is rebuilt this way. A contribution needs the same for its own pack, and also the keyword rows and the vectors, which the talent rebuild skips |
| Search of the graph | The Ask page resolves a question to concepts and routes it to companies. The Domains page shows counts by type. The `entity`, `related` and `similar` tools exist for applications | A person cannot type a phrase and see the entities, who owns them and what links them. The three tools have no screen |
| Review | Governance reviews access requests, links between companies and application entries | No review of a person's contribution |

## 2. The Five Steps

### 2.1 Templates: The Shape of One Kind of Input

A template is a named list of fields for one document kind. The group keeps one default template for each of the 12 kinds, and a company may add its own templates and change the group defaults for itself. The person who adds knowledge picks a template, and the fields become the sections of the document body in the order of the template. The kind of the document is the kind of the template.

| Field of a template | Example (CEAT, "Root cause analysis") | Rule |
|---|---|---|
| id | `ceat:template/rca-plant` | Own namespace, letters, digits, dots, dashes |
| name | Root cause analysis (plant) | Shown in the picker |
| kind | rca | One of the 12 kinds of the pack schema |
| scope | ceat (or group) | A company's template is seen by that company only. Group defaults are seen by all |
| fields | Problem seen, Root cause, Fix applied, Checked on, Still open | Each has a name, a one-line hint, required yes or no, and whether it goes into the summary |
| summary_from | Problem seen, Root cause | The summary the group may see under a summary-only item is built from these fields only, so the person knows what leaves the company |
| created_by_role, created_at | Plant maintenance, 2026-11-09 | Provenance, as for graph records |

Templates are stored in the central store (a table `input_templates` beside the graph tables in `mesh_graph.db`) because they hold no company knowledge, only the shape of it. Routes: `GET /mesh/templates` (group defaults and the caller's company's), `POST /mesh/templates` (a person of the company adds or edits one for their company), `DELETE /mesh/templates/{id}` (retires it, never deletes, so a document that names it still resolves).

```
  template "Root cause analysis (plant)"        document body written from it
  ┌──────────────────────────────────┐          ┌───────────────────────────────────┐
  │ Problem seen        required  S  │          │ ## Problem seen                   │
  │ Root cause          required  S  │   ───►   │ Belt slip on mixer 3 ...          │
  │ Fix applied         required     │          │ ## Root cause                     │
  │ Checked on          required     │          │ Worn tension roller ...           │
  │ Still open                       │          │ ## Fix applied ...                │
  └──────────────────────────────────┘          └───────────────────────────────────┘
   S = goes into the summary the group may see
```

Key insight: the template decides what the group sees under a summary-only item. The summary is built from the marked fields and nothing else, so the person sees before sending exactly which sentences can leave the company.

### 2.2 The Contribution: From a Filled Template to a Document on the Company's Node

The "Add knowledge" page shows the templates, the catalogue items of the person's own company with each item's sharing rule in plain words ("Title only leaves CEAT", "Summary leaves CEAT", "Full text leaves CEAT", "Never leaves CEAT"), and the fields of the chosen template. It shows a preview of what the group will see under the chosen item. On send, the API calls a new node tool `add_document` on the person's own node with the person's identity. A person of KEC cannot add to CEAT, and the node checks that too.

| Step | Where | What happens |
|---|---|---|
| Fill | UI `/contribute` | Template, item, fields, tags, optional version (default the month). Required fields block the send |
| Send | `POST /mesh/contributions` | The API checks the person's company, the template and the item, then calls `add_document` on that company's node |
| Keep | Node `add_document` | Writes `data_pack/<node>/contributions/<id>.json` with the document, its template id, the author's role (never the name), `status: pending`, and the body as sections. The id is `<node>:<item code>-C<number>` |
| Answer | API | The document id and "pending review by <owner role>" |

Images and files are not taken. The body is text in the fields. A document kept under a never-leave item is indexed for the company's own searches only, as today.

```
  POST /mesh/contributions {template, datapoint, fields, tags}
       │ person's company = node?  template seen by the company?  item of the company?
       ▼
  node.add_document (person identity)  ──►  contributions/E-03-C0007.json  {status: pending, by_role, template, sections}
```

Key insight: the contribution goes through the node with the person's own identity, as a search does. The central service never writes company knowledge itself and never holds the text.

### 2.3 Review by the Catalogue Item's Owner Before the Group Sees It

A pending document is searchable by the person's own company at once (the node includes pending documents in searches from its own company). It reaches the pack, the export and the group only after a reviewer of the same company accepts it. In this development build the reviewer is any signed-in person of the same company, which is the rule the Governance page already uses for access requests. In a real deployment the reviewer is the holder of the item's owner role, which needs role accounts that do not exist yet.

| Step | Where | What happens |
|---|---|---|
| List | `GET /mesh/contributions?status=pending` | The pending documents of the caller's company, with template, item, author role and the preview the group would see |
| Decide | `POST /mesh/contributions/{id}/review` {accept or reject, note} | The API calls `review_document` on the node. Accept sets `status: accepted` and triggers the rebuild of 2.4. Reject sets `status: rejected` with the note, and the author sees it on the page |
| Audit | Node decision ledger | Accept and reject are entries like access decisions, so the chain covers them |
| Screen | Governance, new tab "Contributions" | Count of pending, each with Accept and Reject |

Key insight: the review is by the company that owns the item, never by the group. The centre only carries the decision to the node and refreshes afterwards.

### 2.4 Into the Index and the Graph by the Existing Path

Accepted contributions of a node are built into one pack per node, `<node>.contributed`, the way kept talent imports are built into `<node>.talent`. The rebuild writes the pack beside the old file and renames it, adds the document's chunks to `index.db` under the item's exposure mode, adds the vectors to `packs/contributed/build`, and the node reads the changed files without a restart. The API then refreshes the graph from the node export, and the Document appears in the central graph with its MENTIONS and EXPLAINS links to the concepts and skills the author picked.

| Part | Today | Change |
|---|---|---|
| `knowledge/packgen.py` | `rebuild_talent_packs(nodes)` | `rebuild_contributed_packs(nodes)`: reads `contributions/*.json` with `status: accepted`, builds the pack, runs the validator with every other pack (as `plan_talent_packs` does), writes nothing when a check fails |
| `index.db` | Written once by `kbgen.py` | The rebuild deletes the rows of the contributed pack's documents and inserts them again. The exposure mode comes from the item. Chunks of 600 characters, as the built packs |
| Vectors | `VectorIndex.build` adds, changes and deletes by row key | Called for `packs/contributed/build` with the contributed rows only |
| `kbgen.py` | Rebuilds every pack from YAML | Leaves `contributions/` and the contributed pack alone, so a rebuild of the synthetic packs does not remove what people wrote |
| Export | `export_graph_node` reads every pack | No change. The contributed pack is a pack |
| Concepts and skills | Picked by the author from the group vocabulary (search as you type) | The author may also name a concept that does not exist yet. It is kept as a tag, not a link, until a curator adds the concept |

```
  contributions/*.json (accepted)  ──►  packgen.rebuild_contributed_packs(node)
                                              │ validate with all packs
                                              ├─► packs/contributed/pack.json   (atomic replace)
                                              ├─► index.db rows of the pack     (delete, insert)
                                              └─► packs/contributed/build       (vectors)
                                   node reloads  ──►  export  ──►  central graph refresh
```

Key insight: a contribution is a pack like any other once accepted. Nothing in search, routing, the ceilings or the graph needs a new rule for it, and a failed check leaves the old pack in place.

### 2.5 Graph Search for People

A "Search the graph" page takes a word or phrase and shows the matching entities: concepts and skills by label and alias, documents by title and tag, roles, catalogue items, assets and companies. Each result shows its type, its owning company, the sharing rule of its item (for documents and items), and its links grouped by type, one hop. From a result the person can open the neighbours or jump to Ask with the entity's label as the question and its company in scope. Entities of never-leave items of another company are left out, as the Domains and graph views already do.

| Part | Where | What it does |
|---|---|---|
| `GET /mesh/graph/search?q=` | API | Whole-phrase match on labels, aliases, titles and tags over the in-memory graph, then the vocabulary vector match of `resolve` for concepts and skills when nothing matched by words. At most 50 results, filtered by `shown_to` |
| `GET /mesh/graph/entity/{id}` | API | The entity and its neighbours by link type, one or two hops, through the same code as the `related` tool, filtered by `shown_to` |
| Page `/graph` | UI | Search box, result list with type and company chips, a detail panel with the links, "Ask about this" |
| Sharing rule words | UI `lib/format.ts` | The same plain words as the Add knowledge page |

```
  "natural rubber storage"
       │
       ▼
  Concept  Natural rubber storage        CEAT, KEC          ── 4 documents, 2 skills
  Document Warehouse storage practices   CEAT · E-03 · Summary leaves CEAT
  Document Time-to-use limits            CEAT · E-03 · Summary leaves CEAT
  Skill    Materials handling            group vocabulary   ── required by 3 roles
       │ open
       ▼
  Document Warehouse storage practices
    MENTIONS  Natural rubber storage, FIFO issue
    EXPLAINS  Materials handling
    CORROBORATED BY  Time-to-use limits
    [Ask about this]
```

Key insight: the search shows the graph the Ask page already uses, so a person can see why a question was routed to a company before asking it, and what a new contribution linked to.

## 3. Roadmap

| Order | Work | Checks |
|---|---|---|
| 1 | Templates: table, routes, group defaults for the 12 kinds, UI picker and editor | Tests for scope (a KEC person does not see a CEAT template), retire not delete |
| 2 | `add_document` node tool, `POST /mesh/contributions`, Add knowledge page with preview of what leaves the company | Tests: wrong company refused, required fields, never-leave item indexed for own company only, preview equals the summary built |
| 3 | Review: `review_document` tool, list and review routes, Governance tab, decision ledger entries | Tests: pending seen by own company only, accept triggers rebuild, reject keeps the note, chain verifies |
| 4 | `rebuild_contributed_packs`, index rows, vectors, `kbgen.py` leaves contributions alone, graph refresh | Tests: validator failure leaves the old pack, node reloads, export carries the document, graph has MENTIONS and EXPLAINS. Live check: add, accept, ask a question that cites the new document |
| 5 | Graph search routes and page | Tests: never-leave filtering, phrase and vector match, "Ask about this" carries company scope. Browser check of the page at about 1500 px |
| 6 | Pages and status document and the Pages and Status HTML updated | The two new pages in the Pages tab and in the implemented list |

What this plan does not do: files or images, a real owner-role account per catalogue item, a contribution to another company's item, and editing a built-in synthetic document. A person who wants a new catalogue item asks the item's owner, because an item is a sharing decision of the company.

## 4. Sources

- `RPG_NeuralMesh_Knowledge_Mesh_Strategy_Plan_v2.md`: the pack format, the ceilings and the node export.
- `RPG_NeuralMesh_Generic_Graph_Input_Standard_Plan.md`: the graph standard, the type registry and the intake.
- `RPG_NeuralMesh_Data_Prerequisites_and_Public_Sources.md`: what has to be collected before real knowledge, and the public documents found by web search on 2026-11-06.
- `RPG_NeuralMesh_Implementation_Status.md`: the import tool, the talent pack rebuild and the node reload, which this plan reuses.
- `app/knowledge/knowledge-pack.schema.json`: the document fields and the 12 kinds.
- `app/knowledge/packgen.py`, `app/mcp_nodes/server.py`, `app/mcp_nodes/server_config.py`, `app/services/mesh_graph.py`: the code the steps extend.
