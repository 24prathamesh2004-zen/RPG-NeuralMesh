# RPG NeuralMesh: Named Context Graphs, Search over the Inputs and the Shared Inputs Node

Date: 2026-11-10.

## Where It Stands

Built on 2026-11-10, the same day, all five steps: the search box over the uploaded inputs, named context graphs that a later input is added to, the drop of a whole context graph, the shared inputs node "Others" as the default destination, and the page and form changes. Checked with 208 tests (8 new), the live wiring check 37 of 37, the golden answers 15 of 15, a browser run of 23 checks at 1,500 pixels wide, and a timing run of 25 inputs. A review of the change by three agents found 12 points, 10 of which were fixed the same day (the pack download now carries only what the item releases, a drop reports a pack whose rebuild failed and a second drop repairs it, a failed upload leaves nothing in the pack, and seven page states). The state is recorded in `RPG_NeuralMesh_Implementation_Status.md`.

## Goal

A mesh admin groups the uploaded inputs into named context graphs. The first input opens a graph with a name, every later input is added to that graph or opens another one, and a graph can be dropped as a whole. An input that belongs to no one company goes to the shared inputs node, called "Others" on the page, which is the default choice and which every connected company reads. The list of inputs can be searched by any word written on an input, so a list of 100 inputs stays usable.

## Contents

1. What exists today and what is missing
2. The five steps
   - 2.1 Search over the uploaded inputs
   - 2.2 Named context graphs: a new one or an existing one
   - 2.3 Dropping a context graph
   - 2.4 The shared inputs node "Others"
   - 2.5 What Kind and Title are for
3. 100 inputs: how they are processed and shown
4. Roadmap
5. Sources

```
  mesh admin                          API (one machine in development)                nodes and the central graph
  ──────────                          ─────────────────────────────────               ───────────────────────────
  Add input
    Company: Others (default)   ──►   POST /mesh/uploads
    or one of the 7 companies           graph_name "Bale storage review"  ──► a new graph id g-3f9a2c1d
    Context graph: new + name           graph_id g-3f9a2c1d               ──► the same graph
    or an existing graph                  │
    Kind, Title, Tags, File               ▼
                                        contributions/<doc>.json   with context_graph {id, name}
                                          │
                                          ▼
                                        rebuild of the item's pack ──► node reads it ──► export_graph ──► central graph
                                                                                                 Document, MENTIONS
  Uploaded inputs
    search box   ──►  the graphs whose name, or one of whose inputs, holds the words
    graph row    ──►  GET /mesh/uploads/graphs/{id}: the inputs of the graph, their items, companies and
                      concepts, each once, and the links among them
    Drop graph   ──►  DELETE /mesh/uploads/graphs/{id}: every input marked removed, one rebuild per pack
```

## 1. What Exists Today and What Is Missing

| Part | Before this plan (built on 2026-11-09) | Gap |
|---|---|---|
| One upload | A file becomes one document of one company's catalogue item. The list shows every upload newest first, and the graph panel shows the document with the entities one link away | Each upload stands alone. Two uploads on one topic are two separate parts of the graph, with no name that joins them and no view of what they share |
| Finding an upload | The list, newest first | No search. With 100 uploads the list is 100 rows to scroll |
| Where an upload can go | One of the seven company nodes, under one of its catalogue items | A file that belongs to no one company (a group policy, a market note, a supplier's data sheet) has no place |
| Removing | One upload at a time, with the record kept and marked removed | Nothing removes a topic of several uploads at once |
| Kind and Title | Kind is one of the 12 kinds of the pack format and is stored with the document. Title is the title of the document and, left empty, the file name | The page does not say what Kind changes, and whether Title names the graph |

## 2. The Five Steps

### 2.1 Search over the Uploaded Inputs

A search box above the list. The words typed are matched against every word written on an input: title, document id, file name, company, catalogue item, kind, tags, the first sentences, the name of its context graph, and the word "removed" for a removed input. A graph stays in the list when its name holds every word typed, or when one of its inputs does. In the second case the matching inputs are shown under the graph row, each with its company, so the person sees which input matched.

| Part | Where | What it does |
|---|---|---|
| Search box | Uploaded inputs tab, above the list | Filters as the person types. Every word typed must appear. An empty box shows every graph |
| The words of an input | `words()` in `ui/src/pages/ContextGraphPage.tsx` | Title, id, file name, company, item, kind, tags, first sentences, graph name, "removed" |
| Matching inputs under a graph | The graph row | Every matching input of the graph, with its company |
| No match | The list | "No input matches <the words>" |

The search runs in the browser over the list the page already loaded: `GET /mesh/uploads` returns every record without the body text, and 28 records were 32 KB in the timing run. No request is made while typing.

```
  [ plant 2                          ]
  ┌───────────────────────────────────────┐
  │ Group storage review                  │   the name does not hold the words,
  │ 2 inputs · CEAT, Others               │   one input does
  │ Latest 10 Nov 2026, 13:16             │
  │ ▌Bale storage check at the Plant 2    │   ◄── the matching input, with its company
  │ ▌raw material store · CEAT            │
  └───────────────────────────────────────┘
```

Key insight: this search is over the upload records, including removed ones, by anything written on them. The tab "Search the graph" is a different search: it finds entities of the central graph (concepts, documents, items) by name.

### 2.2 Named Context Graphs: a New One or an Existing One

A context graph is a named set of uploaded inputs. Its part of the central graph is the union of the parts its inputs made: the documents, their catalogue items and companies, every concept any of them mentions, each once, and the links among all of these. Two inputs that mention the same concept meet at that concept.

The Add input form has the choice "Context graph": "New context graph" with a name, or one of the graphs that has inputs. The name is required for a new graph, has at most 80 characters, and must not be the name of a graph that has inputs (the same letters in any case are the same name). Adding to an existing graph locks the name field to the graph's name and says how many inputs it adds to.

Storage: each upload record carries `context_graph` with `id` and `name`. The id is `g-` and 8 hex digits, made when the graph is opened. An upload kept before this change (the Kochi note of 2026-11-09) is its own graph, named after its title, with the document id as the graph id. An upload sent through the API without a graph goes into the graph named after its title, opened when there is none.

| Part | Where | What it does |
|---|---|---|
| Form fields `graph_name` or `graph_id` | `POST /mesh/uploads` | `_graph_for` in `services/uploads.py` resolves the graph: an existing one by id, a new one by name, or the graph named after the title |
| `graphs` in the list | `GET /mesh/uploads` | id, name, inputs, removed, nodes, companies, latest upload, newest first |
| The union view | `GET /mesh/uploads/graphs/{id}` | `context_graph_view`: every input the person may see, the entities one link away, the links among them. With `format` a download as JSON, GraphML, CSV, or a knowledge pack with every document and its text |
| The page | Uploaded inputs tab | Left: the graphs. Right: the graph with its inputs, the chosen input's record, the download, and "What these inputs are linked to" with "2 inputs · 16 entities · 28 links" |

```
  Group storage review (2 inputs)

  Bale storage check (CEAT, E-03) ──MENTIONS──► Raw material storage ◄──MENTIONS── Group storage rule (Others, G-01)
         │                                      Material ageing      ◄──MENTIONS──────────┘
         ├──MENTIONS──► Lot acceptance, Lot traceability, Time-to-use limit and 5 more concepts
         └──IN_DATAPOINT──► E-03 ──OWNED_BY──► CEAT                 G-01 ──OWNED_BY──► Others
```

Key insight: a context graph is a grouping of records, not a second graph. The central graph stays one graph, and the never-leave rule is applied to every document of the union exactly as to a single document: a document of a never-leave item is in the union for its own company and the mesh admins only.

### 2.3 Dropping a Context Graph

"Drop graph" on the graph's panel. A confirmation lists every input that leaves, with its company. Then every input of the graph is marked removed, with who and when, each pack that held one is rebuilt once, the nodes read their packs, and the central graph is refreshed, so the documents and their links leave it. The records stay, and the graph row stays with "0 inputs · 2 removed". The name of a dropped graph is free for a new graph. "Remove this input" still removes one input of a graph.

| Part | Where | What it does |
|---|---|---|
| `DELETE /mesh/uploads/graphs/{id}` | API, mesh admins only | `drop_graph`: mark every record, one rebuild per pack, then the graph refresh. 404 when no input is in the graph |
| The confirmation | The page | The name of the graph, the count, the title and company of each input, and "The upload records stay, marked removed" |

```
  Drop graph "Group storage review"
     │
     ├── ceat:E-03-U002   status removed, by the mesh admin, at 13:16   ──┐
     ├── others:G-01-U001 status removed, by the mesh admin, at 13:16   ──┤
     │                                                                    ▼
     ├── rebuild ceat.engineering, rebuild others.general (one each)
     └── refresh the central graph: the two documents and their links are retired
```

Key insight: dropping writes nothing new into a node. It takes documents out of packs that are then rebuilt, the path the single remove already used, so the node, the index and the graph end in the same state as if the inputs had been removed one by one.

### 2.4 The Shared Inputs Node "Others"

A file that belongs to no one company still needs a node, because the Ask page, the graph export and the sharing policy all work through nodes. The eighth node is `others`, display "Others", port 8108, marked `shared: true` in `config/nodes.yaml`. It has one catalogue item, G-01 "Shared inputs of the group", whose full text leaves to every connected company, no built-in documents and no experts. Its domain is "general", the ninth domain of the pack format, and G is the ninth catalogue letter.

| Place | A company node | The shared node |
|---|---|---|
| Sign-up and `/auth/companies` | Listed | Left out: nobody belongs to "Others" |
| Add input, Company | In the list | First in the list and chosen by default. Under the label: "Inputs that belong to no one company. Every connected company reads them" |
| The sharing rule in words | "Summary leaves CEAT", "Full text leaves KEC" | "Shared with every connected company" |
| The list of inputs for a person who is not a mesh admin | The own company's uploads | The own company's and the shared node's |
| A question that names a company | "What does CEAT do about ..." routes to CEAT | The word "others" in a question never routes to the node: `resolve` skips a company entry marked shared |
| Mesh Nodes page | "Subsidiary operated" | "Shared inputs, read by every connected company" |
| Ask page | A company's documents | The shared documents are searched and cited like any other, with "Others" as the company |

```
  config/nodes.yaml  (id others, display Others, port 8108, shared: true)
        │
        ├── shared/registry.py        company_nodes() leaves it out ──► sign-up list, /auth/companies
        ├── knowledge/adapters.py     org:others carries shared: true ──► mesh_graph.resolve never names it
        ├── api/routers/mesh.py       /mesh/nodes: shared true, owner words
        └── services/uploads.py       listed to every company, sharing words "Shared with every connected company"
```

Key insight: one flag in the registry, read by the sign-up list, the resolver, the nodes endpoint and the upload service, is the whole difference between a company node and the shared node. Everything else, the packs, the policy, the index, the export and the ledger, is the same code.

### 2.5 What Kind and Title Are For

Kind is one of the 12 kinds of the pack format: procedure, root cause analysis, playbook, post-mortem, standard, report, policy, wiki page, aggregate figures, note, study material, role profile. It is stored with the document, shown on the input's row and in the central graph, and the search box matches it, so "policy" finds the policies. It does not change how the text is read, indexed or shared: the catalogue item decides that. Its planned use is a template of fields per kind, step 1 of the plan of 2026-11-09, not built, so that two root cause analyses carry the same fields.

Title is the title of the document: the name the input has in the list, in the graph and in the citations of the Ask page. Left empty, it is the file name. It is not the name of the context graph. That name is the field "Name of the graph", added with this plan.

## 3. 100 Inputs: How They Are Processed and Shown

Measured on 2026-11-10 on the development stack (one machine, the stand-in model), 25 inputs of about 500 characters each into one graph of the shared node, sent through the API one after the other:

| Step | Time | What it depends on |
|---|---|---|
| One upload: read the file, link the concepts, rebuild the pack, write the index rows and the vectors, the node reads the pack, the graph is refreshed | 0.38 s median, 0.45 s at most, the same for the 1st and the 25th | The size of the file and of the pack's domain. The vector store adds only the new chunks, so the time does not grow with the number of earlier inputs |
| The list, `GET /mesh/uploads`, 28 inputs in 3 graphs | 0.01 s, 32 KB | One read of the record files. 100 inputs are about 115 KB at the same size per record |
| The union view of 25 inputs | under 0.01 s, 27 entities, 26 links | The inputs and what they link to |
| Dropping the 25 inputs | 0.41 s | One rebuild per pack |

Through the page, one upload took 0.8 s from the click to the new graph shown, the API time plus the reload of the list.

How the page copes with many inputs: the list shows graphs, not inputs, so 100 inputs in 10 graphs are 10 rows, and the search narrows the rows by any word. The graph drawing opens every entity at once up to 80 entities, and above that it opens from the companies and items, one double-click per entity, the way the mesh graph on the Mesh Nodes page does. A context graph of 100 inputs holds at most 100 documents plus the concepts they mention (61 in the group vocabulary today) plus their items and companies.

What this plan does not build: a server-side page or search for thousands of records (the list is read whole), a limit on the inputs of one graph, renaming a graph, and moving an input from one graph to another.

## 4. Roadmap

| Order | Work | Checks |
|---|---|---|
| 1 | The registry flag, the sign-up list, the nodes endpoint, the resolver, the `others` node (knowledge file, domain "general", letter G in the pack schema) and its two packs | Tests: a node list of eight, a sign-up list of seven, "others" in a question names no company, 37 subsidiary packs validate together |
| 2 | Records with `context_graph`, `_graph_for`, `graphs_of`, the union view, the exports with several documents, `drop_graph` | Tests: open and add, taken name, unknown id, drop with the records kept and one rebuild per pack, the dropped name free again |
| 3 | Routes: the form fields, `GET` and `DELETE /uploads/graphs/{id}` | Tests through the API, 404 and 403 paths |
| 4 | The page: search box, graph rows, graph panel with its inputs, Drop graph, Add input with Others first, the graph choice and name | Browser check at 1,500 pixels: default Others, new graph, add to it, search, Ask, drop (23 checks) |
| 5 | The status document, the pages document, the check guide and this plan | Counts and screenshots retaken |

## 5. Sources

- `RPG_NeuralMesh_Knowledge_Contribution_and_Graph_Search_Plan.md`: the upload path this plan extends.
- `RPG_NeuralMesh_Implementation_Status.md`: what was built on 2026-11-09 and 2026-11-10.
- `app/services/uploads.py`, `app/api/routers/mesh.py`, `app/shared/registry.py`, `app/services/mesh_graph.py`, `app/knowledge/adapters.py`, `app/ui/src/pages/ContextGraphPage.tsx`: the code of the five steps.
- `app/tests/test_uploads.py`: the tests of the five steps.
