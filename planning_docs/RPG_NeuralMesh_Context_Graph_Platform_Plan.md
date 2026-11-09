# RPG NeuralMesh as the Group Context Graph

Date: 2026-11-06. A high-level, end-to-end plan. It describes the target, not the code built so far.

## Goal

NeuralMesh becomes the one context graph of the group. Any application (SkillForge for talent, Snap and Score for visual inspection, the next one) brings its own ontology and its own data, and gets back context in one shape: the entity it asked about, what is connected to it, what is similar to it elsewhere in the group, the evidence behind each answer, and what the owner of the data allows that user to see. The graph grows by adding domains, not by changing its core.

## Contents

1. Problems the platform must solve
2. The standards the platform maintains
3. The architecture, end to end
4. The steps
   - 4.1 Core ontology and domain ontologies
   - 4.2 Bringing an ontology in: the Snap and Score example
   - 4.3 Bringing data in: adapters, validation, normalised file
   - 4.4 The graph store and its layers
   - 4.5 Live lookups: what is never stored
   - 4.6 Similarity: "others like this"
   - 4.7 The context API: one set of tools for every application
   - 4.8 Policy, consent and approval
   - 4.9 Evidence, provenance and audit
   - 4.10 Governance of the ontologies
5. Roadmap
6. Sources

```
  applications        context API            context graph core                 data owners
  ───────────         ───────────            ──────────────────                 ───────────
  SkillForge ──┐                         ┌─ ontology registry (core + domains)
  Snap&Score ──┼──► tools: entity, ──────┤  graph store (metadata, links)   ──► subsidiary nodes
  next app ────┘    related, similar,    │  similarity service                   (documents, records,
                    ask, sources,        │  routing + context builder            live systems, policy)
                    experts, live        └─ policy, evidence, audit
```

## 1. Problems the Platform Must Solve

| Problem | Seen where | What the platform does about it |
|---|---|---|
| Each application invents its own vocabulary | SkillForge says skill, role, level. Snap and Score says asset, condition, grade scale, cover type | A small core ontology shared by all, and a domain ontology per application that extends it |
| Each application would build its own graph | A skills graph in SkillForge, an inspection ontology in Snap and Score | One graph, one store, one set of tools. A domain is a layer in the graph, not a new system |
| The same thing has different names across companies and apps | CEAT finished tyre, a tyre in a claims record, a tyre in a fleet | SAME_AS and SIMILAR_TO links, aliases, and one ID rule, so one thing resolves to one node |
| Some facts must never be stored centrally | The Snap and Score draft says insurance status is looked up at scan time and never stored | Live lookups through the owning node, with the graph holding only the pointer |
| Users want "what else is like this" | Similar skills to the one asked about, similar defects in another company, how others graded | A similarity service on graph structure and text, with its own evidence and rules |
| An answer must be explainable | Any application showing a result to a person | Every item is an evidence record with its source, its decision and its trace ID |
| Data owners must stay in control | Each subsidiary owns its documents and records | Policy per datapoint at the node, two-owner approval for cross-company links, consent for people |

```
  today: one app ──► one graph ──► one vocabulary          target: many apps ──► one context graph
                                                                       ▲              ▲
                                                               domain ontologies   core ontology
```

## 2. The Standards the Platform Maintains

These are the rules every domain and every data source follows. They are the product. The code can change under them.

| No. | Standard | One-line rule |
|---|---|---|
| S1 | Node shape | `id`, `type`, `label`, optional `aliases`, `description`, `owner`, `sensitivity`, `properties`, `external_refs` |
| S2 | Edge shape | `id`, `type`, `from`, `to`, `status` (proposed, approved, rejected, retired), `provenance`, optional `properties`, `confidence`, `approvals` |
| S3 | ID rule | `<namespace>:<local>`. The namespace is the owner (`ceat`, `concept`, `snapscore`). An ID never changes while the thing exists |
| S4 | Direction and symmetry | An edge runs `from` to `to`. A symmetric type (SAME_AS, RELATED_TO, SIMILAR_TO, CONFLICTS_WITH) is stored once |
| S5 | Ontology file | One file per domain: node types with required properties, edge types with the node types each may join, groups, derived edges, default statuses |
| S6 | Core ontology | The types every domain may use without declaring them: Organisation, Person role, Concept, Document, Datapoint, Event, Standard, Asset |
| S7 | Adapter rule | An adapter changes shape only. It never validates, filters or loads |
| S8 | Validation | Shape, type, signature, reference, duplicate, ownership. Any failure stops the load and names the record |
| S9 | Normalised file | Sorted records, one per line, written before loading. Two runs on the same input give the same file |
| S10 | Store rule | Upsert by ID. Retire, never delete. A source that stops sending a record retires it |
| S11 | Live lookup | A fact marked live is never stored. The graph holds the pointer (node, tool, key) and the lookup runs at request time with the user's identity |
| S12 | Exposure policy | Each datapoint states what may leave its node: metadata only, summary, text, or live. The node applies it to every item |
| S13 | Evidence record | Every item an application receives is an evidence record (schema version 1.0): source, decision, rule, text or title, citation, trace ID |
| S14 | Provenance | Every edge says how it was made (authored, imported, extracted, computed), by which role, when, from which evidence |
| S15 | Approval | A link between two owners needs both owners. A computed link is proposed until approved, or marked as computed and shown as such |
| S16 | Consent | Nothing about a person is stored or returned without that person's consent recorded at the owning node |
| S17 | Versioning | Ontology files and packs carry a version and a publish date. A change in a type is a new ontology version, and old data still validates against the version it was published under |
| S18 | Audit | One line per decision, per lookup and per model call, with the trace ID of the request |

```
  S1–S4 shape ──► S5–S6 meaning ──► S7–S9 intake ──► S10–S12 storage and exposure ──► S13–S18 trust
```

## 3. The Architecture, End to End

```
 ┌──────────────────────── applications ────────────────────────┐
 │ SkillForge (talent)   Snap and Score (inspection)   next app  │
 └──────────────┬───────────────────┬───────────────────┬────────┘
                │ context tools (MCP and REST), service identity + user identity
 ┌──────────────▼───────────────────▼───────────────────▼────────┐
 │                        context API                            │
 │  entity · related · similar · ask · sources · experts · live  │
 │  import: ontology, data pack, talent pack                     │
 ├───────────────────────────────────────────────────────────────┤
 │                     context graph core                        │
 │  ontology registry   graph store (layers per domain)          │
 │  resolve + route     similarity service   context builder     │
 │  policy gate         evidence records     audit               │
 └──────┬───────────────┬───────────────┬───────────────┬────────┘
        │ MCP, user token minted per node
 ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐ ┌──────▼──────┐
 │ CEAT node   │ │ KEC node    │ │ Harrisons   │ │ Raychem …   │   subsidiary nodes = data owners
 │ documents   │ │ documents   │ │ documents   │ │ documents   │   policy per datapoint
 │ records     │ │ records     │ │ records     │ │ records     │   search inside the node
 │ live systems│ │ live systems│ │ live systems│ │ live systems│   live lookups (insurance, stock, history)
 └─────────────┘ └─────────────┘ └─────────────┘ └─────────────┘
```

Three layers, three owners:

| Layer | Holds | Owned by | Leaves the layer as |
|---|---|---|---|
| Subsidiary node | Documents, chunks, vectors, records, live system connections, policy, consent, grants | The subsidiary | Evidence records, after policy |
| Context graph core | Metadata: nodes, edges, ontologies, similarity scores, pointers to live facts, audit | The mesh team | Context bundles made of evidence records |
| Application | Its own screens and its own transactional data | The application team | Requests with a service identity and the user's identity |

## 4. The Steps

### 4.1 Core Ontology and Domain Ontologies

The core is small on purpose. A domain adds what it needs and links to the core where it can.

| Core type | Meaning | Talent domain adds | Inspection domain adds |
|---|---|---|---|
| Organisation | A subsidiary or a unit | Employer of a role | Owner of an asset family |
| Asset | A thing that is owned, used or inspected | Tool or system a skill is used on | Asset family, asset, view |
| Concept | A named idea with aliases | Topic a skill is built from | Condition, condition family |
| Person role | A job, not a person | Role, required skill, level | Inspector, approver |
| Document | A text that can be cited | Study material, SOP | Standard, inspection report |
| Datapoint | A catalogue entry with an exposure policy | Role profiles, expert directory | Inspection records, reference images |
| Event | Something that happened on a date | Assessment, certificate | Inspection, claim |
| Standard | A rule a thing is measured against | Competency framework | Grade scale, cover type, standard |

Edge types of the core: PART_OF, BROADER, RELATED_TO, SAME_AS, SIMILAR_TO, MENTIONS, GOVERNED_BY, OWNED_BY, OCCURRED_ON, EVIDENCED_BY, CORROBORATES, CONFLICTS_WITH, SUPERSEDES, ADDRESSES_GAP. A domain declares its own on top (REQUIRES_SKILL, CHECKED_FOR, GRADED_ON, HAS_VIEW) with the node types each may join.

```
  core:      Organisation ── OWNED_BY ── Asset ── MENTIONS ── Concept ── BROADER ── Concept
  talent:    Role ── REQUIRES_SKILL ── Skill(Concept) ── EXPLAINS_SKILL ── Document
  inspection: Asset ── CHECKED_FOR ── Condition(Concept) ── BELONGS_TO ── Condition family
             Asset ── GRADED_ON ── Grade scale(Standard)     Asset ── HAS_EXPECTED_COVER ── Cover type(Standard)
```

**Key insight:** a condition in inspection and a skill in talent are both concepts with aliases. Because both sit on the core Concept type, "similar" and "same as" work across domains with no extra code.

### 4.2 Bringing an Ontology In: the Snap and Score Example

The draft `Ontology.json` of Snap and Score (version 0.1, assets and conditions still to be confirmed by each subsidiary) maps onto the standards without changing the file.

| In the file | Becomes | Standard |
|---|---|---|
| `condition_families`, `conditions` | Nodes of type Condition family and Condition (core Concept), edge BELONGS_TO | S1, S6 |
| `grade_scales`, `cover_types`, `review_status` | Nodes of type Grade scale, Cover type and Review status (core Standard), grades as properties | S1 |
| `subsidiaries` → `families` → `assets` | Organisation, Asset family, Asset nodes with edges HAS and OWNED_BY. `scan`, `views` as properties, each view also a node for HAS_VIEW | S1, S3 |
| `assets[].conditions`, `scale`, `cover` | Edges CHECKED_FOR, GRADED_ON, HAS_EXPECTED_COVER | S2 |
| `relations` | The edge types of the inspection ontology file, with their signatures, for example `["asset","checked_for","condition"]` becomes CHECKED_FOR: Asset to Condition | S5 |
| `mcp_server: "tbd"` | The node address of each subsidiary, filled from the mesh registry, not from the file | S11 |
| `neuralmesh_lookups` | Six tool names the application expects. They map to the generic tools of 4.7 | S11 |
| The note "insurance status is looked up at scan time and never stored" | The cover type is an expected value in the graph. The actual cover status is a live lookup at the owning node | S11 |

IDs: the file's `ceat.finished_tyre` becomes `ceat:asset/finished_tyre`, so the owner is in the namespace and the application's own key is kept in `external_refs` with scheme `SnapScore`.

```
  Ontology.json ──► inspection adapter ──► nodes (asset, condition, scale, cover, view)
                                       ──► edges (CHECKED_FOR, GRADED_ON, HAS_EXPECTED_COVER, HAS_VIEW, OWNED_BY)
                                       ──► ontology file inspection.yaml (from "relations")
                                       ──► live pointers (get_cover, get_history) kept as pointers, no values
```

**Key insight:** the file already separates what is stable (assets, conditions, scales) from what is live (cover status). The platform keeps that line as a standard, so a new application states it once in its ontology and the platform enforces it.

### 4.3 Bringing Data In: Adapters, Validation, Normalised File

Ontology and data arrive the same way. One adapter per format, one validator with the domain's ontology file, one sorted normalised file, one loader.

| Input | Adapter | Typical sender |
|---|---|---|
| Knowledge pack JSON | pack adapter | A subsidiary node export |
| Ontology JSON (as above) | ontology adapter | An application team |
| Talent pack | talent adapter | SkillForge |
| CSV nodes and edges | csv adapter | A business team with a spreadsheet |
| JSON Lines | jsonl adapter | A job or another mesh |
| Inspection records | event adapter | Snap and Score, as events with EVIDENCED_BY to images held at the node |

The six checks of S8 run with the ontology file of the domain. The ownership check stops an application from writing nodes in a subsidiary's namespace, which is the class of defect found in the mesh on 2026-11-05.

```
  file ──► adapter ──► records ──► validate (ontology file) ──► sort ──► normalised .jsonl ──► load ──► revision +1
                                        └── report: record ID, rule, nothing loaded
```

**Key insight:** the normalised file is the hand-over between any sender and the store. A sender can be checked and corrected before anything touches the graph, and a `diff` of two files is the change report.

### 4.4 The Graph Store and Its Layers

One store, several layers. A layer is the set of nodes and edges written under one ontology and one set of sources. Queries can run in one layer or across layers.

| Layer | Written by | Read by |
|---|---|---|
| Core | Group vocabulary, organisation registry | Every application |
| Talent | SkillForge talent packs, node exports of role profiles and experts | SkillForge, the Ask page |
| Inspection | Snap and Score ontology and inspection events, node exports of standards and reference image catalogues | Snap and Score |
| Knowledge | Node exports of documents and concepts, group links | Ask, SkillForge study material |
| Similarity | The similarity service (4.6) | Every application, read only |

Store engine: SQLite tables with a NetworkX view in memory now, with a revision number and an export. Neo4j, or another graph database, behind the same interface when a trigger holds: more than 1 million edges, paths of three or more steps on screens, or several writers at once.

```
  ┌─────────── one store ───────────┐
  │ core │ talent │ inspection │ knowledge │ similarity │
  └───────────────┬─────────────────┘
          store interface: upsert, retire, revision, view, export
          SQLite + NetworkX now ── Neo4j on a trigger
```

**Key insight:** layers share nodes. The CEAT organisation node, the "contamination" concept and the "incoming quality control" concept appear once and are linked from talent, inspection and knowledge alike. That is what makes cross-domain context possible.

### 4.5 Live Lookups: What Is Never Stored

Some facts are too changeable or too sensitive to copy. The graph stores a pointer, and the lookup runs when asked.

| Live fact | Pointer stored in the graph | Lookup at request time |
|---|---|---|
| Insurance cover status of an asset | Asset node, owning node, tool `get_cover`, key `asset id` | The owning node asks its system and returns an evidence record with decision and timestamp |
| Inspection history of an asset | Asset node, tool `get_history` | The node returns events it allows for that user and purpose |
| Stock or location | Datapoint with mode LIVE | Same |
| Expert names | Expert node with consent flag | Name only after an approved introduction |

Rules: the lookup runs with the user's identity, the node applies its policy, the result is an evidence record with `mode: LIVE` and the time of the lookup, and the result is cached for at most the time the owning node states.

```
  app asks cover of ceat:asset/finished_tyre ──► core finds the pointer ──► CEAT node: get_cover(asset) ──► policy ──► record (LIVE, 2026-11-06 10:42)
```

**Key insight:** the Snap and Score rule "looked up at scan time and never stored" is not a special case. It is the LIVE exposure mode the mesh already has for the expert directory, applied to a new kind of fact.

### 4.6 Similarity: "Others Like This"

The feature an application shows as "people with this skill also have", "similar defects in other companies" or "how others graded this".

| Kind of similarity | Computed from | Example |
|---|---|---|
| Structural | Shared neighbours in the graph (same concepts, same standards, same owners) | Two roles that require five of the same six skills |
| Textual | Vectors of label, aliases and description | "Latex pre-coagulation" near "cup lump mould" |
| Behavioural (optional, consented, aggregated) | What users of the same role asked for or opened, counted, never per person | "Inspectors of tower members also looked at zinc loss guidance" |
| Declared | SAME_AS and RELATED_TO written by people | Curated links in the group vocabulary |

Each computed similarity is stored as a SIMILAR_TO edge in the similarity layer, with `provenance.method: computed`, the score as `confidence`, the inputs as evidence, and status `proposed` or `computed` so it is never shown as a fact a person approved. A curator can approve it into RELATED_TO or reject it.

```
  nightly: for each node ──► structural score + textual score ──► top k ──► SIMILAR_TO (computed, score) ──► similarity layer
  request: similar(id) ──► read the layer ──► apply policy per end ──► records with the reason ("shares 5 of 6 skills")
```

**Key insight:** the reason is part of the record. A similar item without "why" cannot be checked, so every SIMILAR_TO edge carries the shared neighbours or the text score that produced it.

### 4.7 The Context API: One Set of Tools for Every Application

The six talent tools of today become seven generic tools. A domain adds no tool, it adds types.

| Tool | Input | Returns | Snap and Score lookup it covers |
|---|---|---|---|
| `entity` | id or label and domain | The node, its properties, its layer, its owner | `get_asset` |
| `related` | id, edge types or group, depth 1 or 2 | Neighbour nodes grouped by edge type | `get_inspection_profile` (asset with its views, conditions, scale, cover type, standards) |
| `similar` | id, kinds of similarity, k | SIMILAR_TO neighbours with reasons | Similar defects or assets elsewhere |
| `ask` | question, purpose, user | Routed answer with evidence records, withheld items, checks | Free questions |
| `sources` | topic or id, purpose, user, level | Documents and media the nodes release, by reference | `search_standards`, `get_reference_images` |
| `experts` | topic or id | Consented experts without names | Who knows this condition |
| `live` | id, fact name, user | The live lookup through the owning node | `get_cover`, `get_history` |
| `import` | ontology, pack, talent pack, events | Validation report, revision | New domain or new data |

Every tool is available over REST and as an MCP tool on the gateway. Every call carries the application's service identity and the end user's identity, and every returned item is an evidence record.

```
  SkillForge: related(role) ──► required skills ──► similar(skill) ──► sources(skill, learning) ──► experts(skill)
  Snap&Score: entity(asset) ──► related(asset) profile ──► live(asset, cover) ──► sources(condition, standards) ──► similar(condition)
```

**Key insight:** `role_context` of today is `related(role)` with the talent ontology. `get_inspection_profile` of the draft is `related(asset)` with the inspection ontology. One tool, two domains.

### 4.8 Policy, Consent and Approval

| Control | Where it sits | Rule |
|---|---|---|
| Exposure policy | Each datapoint at the node | Metadata, summary, text or live. Purpose list. Ceiling. Never-leave flag |
| Identity | Every request | Service identity of the application, identity of the end user, both checked. Later: corporate sign-in and a token issued per node in the user's name |
| Cross-company link | The graph core | Proposed until the owner of each end approves. Computed links stay marked computed |
| Consent | The node | A person appears only with recorded consent, names only after an approved introduction |
| Grants | The node | A gated body or a live system is released only under a grant with an expiry |
| Admin actions | The core | Graph refresh, ontology import and layer removal need the mesh admin role |

**Key insight:** the application never holds the policy. It asks, and the owner's node decides, so a new application inherits every rule on day one.

### 4.9 Evidence, Provenance and Audit

| Item | Carries |
|---|---|
| Evidence record | `schema_version`, `evidence_id`, `kind`, `node`, `datapoint`, `document`, `title`, `mode`, `decision`, `rule_id`, `text` or `citation`, `concepts`, `score`, `relationship`, `expert`, `explains_level`, `delivery` |
| Edge provenance | `method` (authored, imported, extracted, computed), `by_role`, `created_at`, `evidence` |
| Audit line | Trace ID, user, application, tool, node, decision, rule, model call if any, time |
| Context bundle | The records used, the records found but not used, the records withheld and why, the checks that ran, the trace ID |

**Key insight:** an application can show "why am I seeing this" for every item, from the bundle alone, without asking the mesh again.

### 4.10 Governance of the Ontologies

| Question | Answer |
|---|---|
| Who owns the core ontology | The mesh team. A change is a new version with a note on what moved |
| Who owns a domain ontology | The application team, checked by the mesh team for conflicts with the core and other domains |
| What happens to data when a type changes | Old data keeps the version it was published under. A migration adapter rewrites it to the new version in one run |
| How a conflict between domains is settled | Prefer a core type. If two domains need the same name for different things, the domain prefix stays (`talent:level`, `inspection:grade`) |
| How the items to be confirmed in a draft are handled | They enter as `status: proposed` nodes and edges, and each subsidiary approves its own. The Snap and Score draft states that assets, conditions and cover types are still to be confirmed |

**Key insight:** a draft ontology can be loaded on the day it arrives, because proposed is a status, not a block.

## 5. Roadmap

| Phase | Steps | Done when |
|---|---|---|
| A. Standards in code | S1 to S10 as models, the ontology file format, the validator, the normalised file, the mesh's current graph loaded through them with unchanged counts | The existing packs load with no change. Every current edge signature is checked by the validator |
| B. Core and talent ontology | `core.yaml` and `talent.yaml` replace the constants in the code. The six talent tools run as `related`, `similar`, `sources`, `experts`, `ask` | SkillForge's calls return the same records as today |
| C. Inspection domain | `inspection.yaml` and the ontology adapter load the Snap and Score draft as proposed. `entity`, `related`, `live` serve its six lookups. One subsidiary node answers `get_cover` and `get_history` as live facts | Snap and Score runs a scan flow against the mesh with no stored cover status |
| D. Similarity layer | Structural and textual similarity, nightly job, SIMILAR_TO with reasons, `similar` tool | "Similar skills" in SkillForge and "similar conditions elsewhere" in Snap and Score, each with its reason |
| E. Scale and identity | Corporate sign-in with a token per node, a graph database behind the same interface when a trigger holds, more nodes (Raychem and the next wave) | Two or more applications and five or more nodes run on one graph |
| F. Behavioural similarity | Consented, aggregated usage signals as a similarity input | Shown only where an owner opted in, always marked as computed |

Order: A, then B and C in parallel, then D, then E and F.

## 6. Sources

- The draft `Ontology.json` of Snap and Score, version 0.1, received 2026-11-06. Assets, conditions and cover types in it are marked as still to be confirmed by each subsidiary. Nothing in it has been verified here.
- `planning_docs/RPG_NeuralMesh_Knowledge_Mesh_Strategy_Plan_v2.md`: the two-layer rule, exposure modes, the evidence record, the triggers for a graph database.
- `planning_docs/RPG_NeuralMesh_Generic_Graph_Input_Standard_Plan.md`: standards S1 to S10 in detail.
- `app/contracts/evidence.py`: the evidence record contract, schema version 1.0.
- Model Context Protocol, the tool protocol the nodes and the gateway speak: https://modelcontextprotocol.io/
- Neo4j `MERGE`, upsert by key when the graph database is introduced: https://neo4j.com/docs/cypher-manual/current/clauses/merge/
