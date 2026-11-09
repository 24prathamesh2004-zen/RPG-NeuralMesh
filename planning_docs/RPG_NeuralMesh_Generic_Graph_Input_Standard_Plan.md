# RPG NeuralMesh: Generic Graph Input Standard

Date: 2026-11-06.

## Goal

One method that takes graph input from anyone, in a file format of their choice, checks it against one standard, sorts it, loads it into a persistent graph, and can be run again when the input changes. The same method builds graphs for different purposes (the knowledge mesh, a skills graph, a system dependency graph) by swapping one file: the type registry of that purpose.

## Contents

1. What exists today and what is missing
2. The six steps
   - 2.1 The graph standard: one shape for a node and an edge
   - 2.2 The type registry: what a purpose allows
   - 2.3 Adapters: from any input format to the standard
   - 2.4 Validate and sort
   - 2.5 Load into a persistent store, NetworkX now, Neo4j later
   - 2.6 Run again: change, retire, export
3. Roadmap
4. Sources

```
  input files ──► adapter ──► standard records ──► validate ──► sort ──► load ──► store ──► export
  (JSON, CSV,     (one per    (node, edge,        (against the  (stable  (upsert,  (SQLite +   (JSON,
   XML, GraphML)   format)     provenance)         registry)     order)   retire)   NetworkX)   GraphML, Cypher)
                                   ▲
                       type registry of the purpose
```

## 1. What Exists Today and What Is Missing

| Part | Today | Gap |
|---|---|---|
| Input format | One JSON pack format, checked by `knowledge/knowledge-pack.schema.json` | JSON only. CSV, XML or GraphML input has to be converted by hand |
| Node types | Fixed list in the schema: Subsidiary, Domain, Concept, Skill, Role, Asset, plus Document, Datapoint, Expert | A new purpose needs a schema change |
| Edge types | Fixed list of 15 types in the schema, and the groups hop, judgement and structure are hard-coded in `services/mesh_graph.py` | A new edge type needs a code change in two places |
| Edge signature | Which node types an edge may join is checked nowhere. The review of 2026-11-05 checked it by hand | A wrong edge (for example MENTIONS from a role) loads without an error |
| Store | `GraphStore`: two SQLite tables, NetworkX in memory, upsert by ID, retire never delete | Works. Needs a revision number and an export |
| Loading | `load_group_pack` and `load_node_export` in `mesh_graph.py` know the pack fields | The loader and the input format are one piece of code |

```
  problem: format, types and loader are one piece
     ┌──────────────┐
     │ pack schema  │──types──┐
     └──────────────┘         ▼
     ┌──────────────┐    ┌─────────┐    ┌───────┐
     │ mesh_graph.py│───►│ loader  │───►│ store │
     └──────────────┘    └─────────┘    └───────┘
  fix: split into standard + registry + adapters + one loader
```

## 2. The Six Steps

### 2.1 The Graph Standard: One Shape for a Node and an Edge

Every input, whatever its file format, becomes records of these two shapes before anything else happens.

| Record | Required fields | Optional fields |
|---|---|---|
| Node | `id`, `type`, `label` | `aliases`, `description`, `owner`, `sensitivity`, `properties` (free fields), `external_refs` |
| Edge | `id`, `type`, `from`, `to`, `status` (proposed, approved, rejected, retired), `provenance` (`method`: authored, imported or extracted, `by_role`, `created_at`) | `properties`, `confidence` (0 to 1), `approvals` |

Rules that hold for every purpose:
- IDs are `<namespace>:<local>`, for example `ceat:E-03-01` or `concept:latex-pre-coagulation`. The namespace says who owns the record.
- Direction is `from` to `to`. A symmetric edge is stored once.
- An edge ID is stable across runs, so a second load of the same input changes nothing.
- A record carries its source (`source`, for example `pack:group.links` or `csv:skills-2026-11`), so a later load can retire what that source no longer sends.

```
  node  {id, type, label, aliases[], properties{}}
  edge  {id, type, from ──► to, status, confidence, provenance{method, by_role, created_at}, approvals[]}
```

**Key insight:** the standard holds nothing about a purpose. Everything that differs between the knowledge mesh and a skills graph sits in the registry of step 2.2.

### 2.2 The Type Registry: What a Purpose Allows

One YAML file per purpose. It replaces the fixed lists in the schema and the hard-coded groups in `mesh_graph.py`.

| Section | Content | Example from the mesh |
|---|---|---|
| `node_types` | Name, required properties, which field is the owner | Document needs `datapoint`. Datapoint needs `subsidiary` and `code` |
| `edge_types` | Name, allowed `from` types, allowed `to` types, symmetric yes or no, group | MENTIONS: Document to Concept, not symmetric, group structure |
| `groups` | Named sets of edge types that the code walks | hop: RELATED_TO, BROADER, SAME_AS. judgement: CORROBORATES, CONFLICTS_WITH, ADDRESSES_GAP, SUPERSEDES |
| `derived_edges` | Edges the loader adds from node fields | OWNED_BY from Datapoint.subsidiary to the Subsidiary. ROLE_AT from Role.subsidiary |
| `statuses` | Which status a new edge gets by source | A node export gives approved. A link between two companies gives proposed |

```
  registry: mesh.yaml                registry: skills.yaml
  ├ node_types: Document, Concept…   ├ node_types: Skill, Role, Person, Course
  ├ edge_types: MENTIONS (Doc→Con)   ├ edge_types: REQUIRES_SKILL (Role→Skill)
  ├ groups: hop, judgement           ├ groups: prerequisite
  └ derived: OWNED_BY, ROLE_AT       └ derived: WORKS_AT
```

**Key insight:** the 17 edge types and their signatures that the review of 2026-11-05 checked by hand become data that the validator checks on every load.

### 2.3 Adapters: From Any Input Format to the Standard

One small adapter per input format. Each turns its format into standard records and nothing else.

| Format | Adapter reads | Maps to |
|---|---|---|
| Knowledge pack JSON (today) | `entities`, `relationships`, `documents`, `datapoints`, `experts` | Nodes and edges, the derived edges come from the registry |
| Node export (today) | The `export_graph` tool output | Same, with source `node:<id>` |
| CSV, two files | `nodes.csv` (id, type, label, aliases, properties as JSON) and `edges.csv` (id, type, from, to, status, confidence, note) | Nodes and edges |
| XML | One `<node>` and `<edge>` element each, attributes as fields | Nodes and edges |
| GraphML | The exchange format of Gephi, yEd and NetworkX | Nodes and edges, with `key` elements as properties |
| JSON Lines | One record per line, `kind: node` or `kind: edge` | Nodes and edges, suits large files and streaming |

```
  pack.json ──► pack adapter ──┐
  nodes.csv + edges.csv ──────►├──► list[Node], list[Edge]
  graph.xml / graph.graphml ──►┘
```

**Key insight:** an adapter never validates and never loads. It only changes shape, so a new format is one file of about 50 lines and one test.

### 2.4 Validate and Sort

The validator runs on standard records with the registry of the purpose. The sorter makes the order deterministic, so two runs on the same input give the same file and the same store.

| Check | Rule | Error example |
|---|---|---|
| Shape | Required fields present, ID pattern, status and method from the allowed lists | `edge rel:x has no provenance` |
| Type | Node type and edge type exist in the registry | `edge type CITES is not in mesh.yaml` |
| Signature | `from` and `to` node types match the edge type | `MENTIONS from Role ceat:role/qe is not allowed, Document expected` |
| Reference | Every `from` and `to` names a node in this load or in the store | `edge rel:y points to concept:unknown` |
| Duplicate | One ID once. A symmetric edge once | `SAME_AS a→b and b→a both given` |
| Ownership | A record's namespace matches the source that sends it | `pack:group.vocabulary may not write org:ceat` (the defect fixed on 2026-11-05) |

Sort order: nodes by type then ID, edges by type, `from`, `to`, then ID. The sorted records are written to one normalised file (`graph.normalised.jsonl`) that is the input of the loader and the artefact to diff between runs.

```
  records ──► shape ──► type ──► signature ──► reference ──► duplicate ──► ownership ──► sort ──► normalised file
                 any failure: a report with the record ID and the rule, nothing is loaded
```

**Key insight:** the normalised file is the contract between the input side and the store side. The loader needs to know only this one file.

### 2.5 Load Into a Persistent Store, NetworkX Now, Neo4j Later

The loader reads the normalised file and writes through the store interface. `GraphStore` already does upsert by ID and retire by source, so it gains a revision number and an export, and a Neo4j class with the same methods comes later.

| Method | SQLite + NetworkX (now) | Neo4j (later, same interface) |
|---|---|---|
| `upsert_nodes`, `upsert_edges` | `INSERT … ON CONFLICT UPDATE` | `MERGE` on the ID |
| `retire_missing(source, keep_ids)` | `UPDATE status='retired'` | `SET status='retired'` |
| `revision()` | A counter table, raised by every write | A property on one anchor node |
| `view()` | NetworkX graph from the tables | Cypher query to NetworkX for the walkers |
| `export(format)` | JSON, GraphML, JSON Lines | The same, from a query |

Rules of the loader, as today: retire, never delete. A node keeps its owner's record. A source that stops sending a record retires that record and its edges.

```
  normalised file ──► loader ──► GraphStore interface ──► SQLite tables ──► NetworkX view (in memory)
                                        └──────────────► Neo4j (same calls, when a trigger holds)
```

**Key insight:** the walkers (resolve, route, expand) read NetworkX and do not care which store filled it. The move to Neo4j changes one class.

### 2.6 Run Again: Change, Retire, Export

The method is a loop. A change in the input runs the same steps and the store shows what changed.

| Event | What runs | Result |
|---|---|---|
| A new file from a source | Adapter, validate, sort, load | New records added, changed records updated, revision raised |
| A record missing from a source | Same run | The record and its edges are retired, not deleted |
| A new edge type for a purpose | Add it to the registry, run again | The validator accepts it, the walkers see its group |
| A new purpose | New registry file, same adapters, same loader | A second graph in its own store file |
| Export for another tool | `export(graphml)` or `export(jsonl)` | A file that Gephi, yEd or another mesh can load with the same adapters |

```
  change ──► run ──► diff of normalised files ──► what was added, changed, retired ──► next change
```

**Key insight:** because the normalised file is sorted and stable, `diff` between two runs is the change report, with no extra code.

## 3. Roadmap

| Order | Step | Effort | Done when |
|---|---|---|---|
| 1 | Standard records as Pydantic models in `contracts/graph.py` (node, edge, provenance) | 1 day | The existing packs load into the models without a change to the packs |
| 2 | Registry `config/graph/mesh.yaml` with the current node and edge types, signatures and groups, read by `mesh_graph.py` in place of its constants | 1 day | The 90 tests pass with the constants removed |
| 3 | Validator with the six checks of 2.4 and the sorter, writing the normalised file | 2 days | The review findings of 2026-11-05 are reproduced as validator errors on the old data |
| 4 | Pack adapter and node-export adapter, so the existing loaders call adapter, validator, loader | 2 days | Same graph counts as today: 161 entities, 327 relationships |
| 5 | CSV and JSON Lines adapters with one test file each | 1 day | A graph built from CSV equals the same graph built from a pack |
| 6 | `revision()` and `export()` on `GraphStore`, GraphML and JSON Lines export | 1 day | An exported file re-imports to an equal graph |
| 7 | XML and GraphML adapters | 1 day | Round trip export then import gives an equal graph |
| 8 | A second registry (for example `skills.yaml` for SkillForge's skills graph) loaded into its own store file | 1 day | Two graphs run from one code base |
| 9 | Neo4j store class with the same interface, behind a setting | When a trigger of the strategy plan holds | The suite passes against both stores |

Efforts are estimates for one developer who knows the code.

## 4. Sources

- `app/knowledge/knowledge-pack.schema.json`, `app/services/graph_store.py`, `app/services/mesh_graph.py`, `app/neuralmesh_kb_pack/group/group.links.pack.json`
- `planning_docs/RPG_NeuralMesh_Knowledge_Mesh_Strategy_Plan_v2.md`, section 3.5 (graph store and the triggers for Neo4j)
- GraphML, the exchange format read by NetworkX, Gephi and yEd: http://graphml.graphdrawing.org/
- NetworkX readers and writers (GraphML, JSON graph formats): https://networkx.org/documentation/stable/reference/readwrite/index.html
- Neo4j `MERGE` for upsert by key: https://neo4j.com/docs/cypher-manual/current/clauses/merge/
