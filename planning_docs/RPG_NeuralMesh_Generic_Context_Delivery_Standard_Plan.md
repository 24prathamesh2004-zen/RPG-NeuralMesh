# RPG NeuralMesh: Generic Context Delivery Standard

Date: 2026-11-07.

## Goal

One contract through which every application asks NeuralMesh for context and sends it data: one request, one answer, and a refusal that says what is needed. NeuralMesh publishes the contract, each application keeps a pinned copy of it, and one live test proves that both sides speak it. A new application connects by registering, not by changing NeuralMesh's code.

The graph side is already generic: the input standard turns any source into checked nodes and links. This plan makes the delivery side generic too.

What the standard does not do:
- NeuralMesh holds no data that belongs to an application alone, such as SkillForge's people records or Snap and Score's images.
- No AI model changes a request, a purpose, a company or a role. Section 3 says where AI does fit.

## Contents

1. The problem
2. The steps
   - 2.1 The application registry: who may ask, for whom and for what
   - 2.2 One request for every tool
   - 2.3 One answer for every tool
   - 2.4 Refusals that say what is needed
   - 2.5 The tool catalogue: generic operations and named plugins
   - 2.6 Data from applications: the import tool
   - 2.7 Publishing the contract: schemas, version and hash
   - 2.8 Contract tests on both sides
   - 2.9 The SkillForge side
   - 2.10 The MCP gateway on the same contract
3. Where AI agents fit
4. Roadmap
5. Sources
6. Glossary

Diagrams: the delivery flow end to end (section 1), the registry check (2.1), the request (2.2), the answer (2.3), the refusal decision tree (2.4), generic operations and plugins (2.5), the import path (2.6), the published bundle (2.7), the three contract tests (2.8), SkillForge's calls (2.9), one dispatcher for REST and MCP (2.10), where AI sits (3), the order of work (4).

## 1. The Problem

NeuralMesh and SkillForge were built in the same weeks by two working sessions, each from its own reading of the knowledge mesh strategy plan. That plan listed the tools and said that every tool returns evidence records, but it never wrote the request, the answer or a refusal down as a schema. SkillForge built one request envelope and one answer shape, and marked two answer fields as "to be agreed with the mesh side before the first real run". NeuralMesh built one request shape and one answer shape per tool. Each side tested against itself, so both test suites passed while every live call failed.

| Pain point | Impact |
|---|---|
| No published schema for a request, an answer or a refusal | Each side guessed, and the guesses differ in every tool |
| Each side tests against its own fake or its own shapes | A test suite passes while live use fails |
| Every failure reaches the page as "RPG NeuralMesh did not answer" | The person cannot act, and a format fault looks like an outage |
| An unknown id answers "Unknown role" with no hint | Nothing tells the page or the person what NeuralMesh does hold |
| SkillForge's talent packs never reach NeuralMesh | NeuralMesh answers role questions from its three sample roles |
| A service token may name any connected company and the mesh_admin role in a request | An application can speak for people it does not serve |
| The tool list and the Applications page are written in code for two applications | A third application needs code in several places |

Examples from the live check of 2026-11-07:
- SkillForge called 6 tools through its own client and got 6 errors back. NeuralMesh answered 422 (body not readable) to 5 of them and 405 (wrong HTTP method) to the vocabulary export.
- In the same hour, the 53 tests of SkillForge's mesh client and the 12 tests of NeuralMesh's context routes passed.
- SkillForge's talent export held 8 packs with 45 skills. NeuralMesh refused it because the group pack is named `group.skillforge-skills` and NeuralMesh accepted only `group.skills`.
- Called in NeuralMesh's own shape, the look-ups answered in 0.002 to 0.14 seconds and a written answer in 7.5 seconds, inside SkillForge's limits of 3 and 20 seconds. The data and the speed were never the problem.

```
  application                     NeuralMesh                                                  owning node
  ───────────                     ──────────                                                  ───────────
  build request ──► POST /api/v1/context/<tool>
                     ├─ token valid? ───────────────────────────── no ──► 401
                     ├─ registered application? ────────────────── no ──► 403 not_allowed
                     ├─ readable envelope, version 1.x? ────────── no ──► 400 not_an_envelope or unsupported_version
                     ├─ tool in the catalogue? ─────────────────── no ──► 404 unknown_tool
                     ├─ tool, company and purpose allowed? ─────── no ──► 403 not_allowed
                     ├─ input valid for the tool? ──────────────── no ──► 200 refused, invalid_input
                     ├─ caller's company has a Mesh Node? ──────── no ──► 200 refused, company_not_connected
                     ▼
                   tool runs ─ id unknown? ─────────────────────── yes ─► 200 refused, not_found
                             ─ needs a company? ────────────────── yes ─► 200 needs_input, needs_choice
                             ─ documents ──► fetched with the end user's identity ──────────► node policy decides
                     ▼
                   one answer: status, records, answer, data, problem
  page shows the data, or the line its problem code calls for
```

| Case | NeuralMesh answers | The page shows |
|---|---|---|
| A role NeuralMesh holds | `ok`, the required skills and similar roles in `data` | The roles |
| A role NeuralMesh does not hold | `refused`, `not_found`, up to three closest roles and whether any role of that company is loaded | "RPG NeuralMesh does not know this role yet" and the closest roles |
| A person of a company without a Mesh Node | `refused`, `company_not_connected` | "Your company is not connected to RPG NeuralMesh yet" |
| A question that matches no company | `needs_input`, `needs_choice`, the connected companies | The companies the person can name |
| The owners released nothing for this purpose | `blocked`, `not_released`, the rules that decided | "Not released for learning by the owning companies" |
| A wrong input field | `refused`, `invalid_input`, the field and its allowed values | The application's own answer, with the fault logged |
| A wrong envelope or version | HTTP 400 with the problem | The application's own answer, with the fault logged |
| A company node is down | `partial`, `node_unavailable`, the companies that did not answer | What arrived, and which company did not answer |
| NeuralMesh is down | No answer | "RPG NeuralMesh did not answer this time" |

**Key insight:** the fix is not more generic graph code. It is one written contract that NeuralMesh owns and that both sides test against.

## 2. The Steps

### 2.1 The Application Registry: Who May Ask, for Whom and for What

Each application gets one registry file in `app/config/applications/`. It names the service identity that signs the application's calls, the companies the application may speak for, how its role names map to NeuralMesh roles, the purposes it may use, the tools it may call and the packs it may send. NeuralMesh reads the files at start. The Applications page reads the same files, so a new application appears there without code.

| Field | SkillForge | Snap and Score |
|---|---|---|
| Identity (the token subject) | `svc:skillforge` | `svc:snapscore` |
| Companies it may speak for | ceat, kec, zensar, harrisons, raychem, rpgls, asvata, ventures | ceat, harrisons, kec, raychem |
| Roles | user, admin, lead, content_author, reviewer, proctor and auditor all become `group_user` | Every role becomes `group_user` |
| Purposes | learning, career_mobility, problem_solving | inspection, problem_solving |
| Tools | role_context, skill_context, ask, learning_sources, find_mentors, vocabulary_export, entity, related, similar, import | entity, related, similar, live, ask, inspection_profile, inspection_history, record_inspection |
| Entity types it may read | Subsidiary, Domain, Concept, Skill, Role, Document, Datapoint, Expert | Subsidiary, Domain, Concept, Asset, AssetFamily, Condition, ConditionFamily, CoverType, GradeScale, Inspection, ReviewStatus, View, Document, Datapoint |
| Packs it may send | `group.skillforge-skills` into source `talent:group.skills`, and `<company>.talent` into source `talent:<company>.talent` | None. Its ontology file is loaded from its application folder |

Four rules hold for every application:
- The role `mesh_admin` is never granted through a request. It belongs to a person who signs in to NeuralMesh itself.
- The read tools (entity, related, similar) and the suggestions of a refusal show only entity types on the application's read list. A document or a datapoint is shown only when its datapoint allows the purpose of the call, and an entity of a never-leave datapoint only to a person of the company that holds it. So Snap and Score never reads SkillForge's roles, and no application reads a document title its owner has not opened for that purpose.
- A company, a purpose or a tool outside the application's lists is refused with HTTP 403 and the lists the identity may use.
- A company on the list that has no Mesh Node is not a permission fault. The call gets the answer `refused` with `company_not_connected`, so the page can say so.

```
  token ──► subject svc:skillforge ──► registry file skillforge.yaml
                                         │
              caller.subsidiary  ──► in companies?   ── no ──► 403 not_allowed (lists the companies)
              caller.roles       ──► mapped to group_user, mesh_admin never
              purpose            ──► in purposes?    ── no ──► 403 not_allowed (lists the purposes)
              tool               ──► in tools?       ── no ──► 403 not_allowed (lists the tools)
```

**Key insight:** the registry turns "who may ask for whom" from a claim in a request into a rule NeuralMesh checks on every call.

### 2.2 One Request for Every Tool

Every tool takes the same envelope at `POST /api/v1/context/<tool>`. The tool named in the path must equal the tool named in the body. A call made for no person, such as the vocabulary export or a pack import, names the caller subsidiary `group` with the role `service` and no user reference, and only tools marked for service calls accept it.

| Field | Meaning | Example |
|---|---|---|
| `schema_version` | The contract version the caller speaks. The major number must be 1. The current version is 1.1 | `"1.1"` |
| `tool` | The tool, as in the path | `"role_context"` |
| `purpose` | Why the data is used, checked by every node's policy | `"learning"` |
| `caller.subsidiary` | The end user's company, or `group` for a service call | `"zensar"` |
| `caller.roles` | The end user's roles in the application, mapped by the registry | `["user"]` |
| `caller.user_ref` | An opaque reference to the person, kept in the audit, never a name | `"skillforge:4"` |
| `input` | The tool's own fields, listed in the published schema of that tool | `{"role": "ceat:role/quality-engineer"}` |

| Tool | Input fields |
|---|---|
| role_context | `role`, or `title` and `company` |
| skill_context | `skill`, `level` (L, M or A, optional) |
| learning_sources | `skill`, `level` |
| find_mentors | `skill` |
| ask | `question`, `nodes` (optional list of companies to ask), `context` (optional asset, conditions and grade) |
| vocabulary_export | none |
| entity | `id` |
| related | `id`, `edge_types`, `group`, `depth` (1 or 2) |
| similar | `id`, `k` (1 to 20) |
| live | `id`, `fact` |
| inspection_profile, inspection_history | `asset` |
| record_inspection | `inspection_id`, `asset`, `grade`, `conditions`, `review_status`, `defect_area_pct`, `inspected_at`, `image_ref` |
| import | `packs` (1 to 20 knowledge packs) |

```
  {"schema_version": "1.1", "tool": "role_context", "purpose": "learning",
   "caller": {"subsidiary": "zensar", "roles": ["user"], "user_ref": "skillforge:4"},
   "input":  {"role": "ceat:role/quality-engineer"}}
```

**Key insight:** this is the envelope SkillForge already sends. NeuralMesh adopts it, so SkillForge's request code stays as it is.

### 2.3 One Answer for Every Tool

Every tool answers HTTP 200 with the same fields. Evidence records always go in `records`, so a page shows citations the same way for every tool. A written answer goes in `answer` with the result of NeuralMesh's own sentence check. Everything else the tool returns goes in `data`, described for each tool in the published schema.

| Field | Meaning |
|---|---|
| `schema_version` | The version of the contract NeuralMesh speaks, `"1.1"` |
| `tool` | The tool that answered |
| `status` | One of the six statuses below |
| `records` | Evidence records: one fact a node allowed to leave, with its citation, mode, decision and rule |
| `answer` | `{"text", "check"}`. `check` is `passed` only when every sentence is supported by the records |
| `also_found` | Companies that hold more on the question but were not asked |
| `omitted` | How many further items were left out to keep the answer short |
| `data` | The tool's structured result, for example `required_skills` and `similar_roles` for role_context |
| `problem` | Present when the status is not `ok`. Section 2.4 |
| `trace_id` | The id of the call in NeuralMesh's audit and traces |

| Status | Meaning | The caller |
|---|---|---|
| `ok` | Served in full | Shows the data |
| `partial` | Served, but at least one company did not answer | Shows the data and names the missing companies |
| `no_evidence` | Nothing found | Says nothing was found |
| `blocked` | The owners' sharing rules released nothing for this purpose | Says it is not released |
| `needs_input` | The person has to choose or add something | Shows the choices |
| `refused` | The request cannot be served as asked | Shows the line of the problem code |

| Tool | records | data |
|---|---|---|
| role_context | none | role, label, subsidiary, required_skills (each with concepts, documents, consented_experts), similar_roles (id, label, subsidiary, shared_skill_share) |
| skill_context | released evidence | skill, label, description, aliases, broader, related, concepts, roles_requiring, documents_total, not_released |
| learning_sources | released study documents by reference | skill, level, not_released, dropped |
| find_mentors | expert records without names | skill, note |
| ask | the evidence of the answer | answer_status, citations, checks, routing, withheld, relationships |
| vocabulary_export | none | pack, entities, relationships, embedding_model |
| entity, related, similar, live, inspection tools | none | the result of the operation |
| import | none | packs (each loaded, unchanged or refused), roles, requirements, revision |

```
  {"schema_version": "1.1", "tool": "role_context", "status": "ok",
   "records": [], "answer": null, "also_found": [], "omitted": 0,
   "data": {"role": "ceat:role/quality-engineer", "required_skills": [...], "similar_roles": [...]},
   "problem": null, "trace_id": "6f0c..."}
```

**Key insight:** one answer shape means one reader in every application, and the per-tool part is described, not guessed.

### 2.4 Refusals That Say What Is Needed

A refusal is an answer. Its `problem` object uses the field names of RFC 9457 (the internet standard for machine-readable error details of an HTTP API) and adds fields that say what is needed. An error of the identity or the envelope uses an HTTP error status with the same object as the body. An error a caller corrects with a value, such as an unknown id, is a normal answer with a status, as the MCP specification asks for input errors so that a calling agent can correct itself.

| Field | Meaning |
|---|---|
| `type` | A fixed name of the problem kind, `urn:rpg-neuralmesh:problem:<code>` |
| `code` | The short code a page switches on |
| `title` | One line for a log |
| `detail` | What happened in this call, for a log |
| `fields` | For `invalid_input`: each wrong field, what is wrong and the allowed values |
| `choices` | For `needs_choice`: the ids and names to choose from |
| `suggestions` | For `not_found`: up to three closest known ids with their names and match score |
| `loaded` | For `not_found`: whether NeuralMesh holds any entity of that kind for that company |
| `status` | For an HTTP error only: the HTTP status |

| Code | HTTP | Answer status | When | What it carries |
|---|---|---|---|---|
| `unauthenticated` | 401 | none | The service token is missing, invalid or expired | Nothing. The application renews its token |
| `unsupported_version` | 400 | none | The major version is not 1 | The supported versions |
| `not_an_envelope` | 400 | none | The body is not a request envelope | The envelope fields that are wrong |
| `tool_mismatch` | 400 | none | The path and the body name different tools | Both names |
| `unknown_tool` | 404 | none | The catalogue has no such tool | The tools this identity may call |
| `not_allowed` | 403 | none | The identity may not use this tool, company, role or purpose | What the identity may use |
| `service_unavailable` | 503 | none | A model, a node or the store failed, or an answer did not match the contract | Nothing. The caller falls back and tries later |
| `invalid_input` | 200 | `refused` | An input field is missing or wrong | The fields and allowed values |
| `not_found` | 200 | `refused` | The id is not in the graph | Suggestions and `loaded` |
| `company_not_connected` | 200 | `refused` | The caller's company, or a company the question names, has no Mesh Node | The field that names it and the connected companies |
| `needs_choice` | 200 | `needs_input` | A question matches no company | The connected companies |
| `not_released` | 200 | `blocked` | Every item was withheld by the owners' rules | The rules that decided |
| `node_unavailable` | 200 | `partial` | At least one company did not answer | The companies that did not answer |
| `pack_refused` | 200 | `partial` or `refused` | An imported pack was not loaded | Each pack with its reason |

Rules for suggestions:
- Only live entities of the kind the tool expects, such as a role for role_context or a skill for learning_sources.
- Never a document, a datapoint or an expert, so a suggestion cannot reveal what an owner has not released.
- At most three, each with a name similarity of at least 0.5 on a scale from 0 to 1. A weak match gives no suggestion.
- No model call. The score is computed by code from the names and aliases.

Rule for retries: a page or a calling agent repeats a call at most once, and only after the person changed something, such as naming a company. The same refusal twice ends the attempt.

```
  request ──► identity or envelope wrong? ── yes ──► HTTP 400, 403 or 404 + problem   (fix the code)
                │ no
                ▼
              input wrong? ───────────────── yes ──► refused, invalid_input            (fix the code, page shows own data)
                │ no
                ▼
              company not connected? ─────── yes ──► refused, company_not_connected    (page says so)
                │ no
                ▼
              id unknown? ────────────────── yes ──► refused, not_found + suggestions  (page offers the closest)
                │ no
                ▼
              needs a choice? ────────────── yes ──► needs_input, needs_choice         (person chooses, one retry)
                │ no
                ▼
              all withheld? ──────────────── yes ──► blocked, not_released             (page says not released)
                │ no
                ▼
              ok or partial
```

**Key insight:** every refusal carries enough for the page to say the next step, so "did not answer" is left for real outages.

### 2.5 The Tool Catalogue: Generic Operations and Named Plugins

Each tool is declared once in a catalogue in code: its name, whether a person or a service calls it, its purposes, its input schema, its data schema and its handler. A handler is either a generic operation, which works on any domain through the graph rules, or a named plugin for a tool with its own rules. Plugins use the same request, answer, refusal and schema checks as the generic operations. The published schemas are generated from the catalogue, so the code and the contract cannot differ.

| Tool | Kind | Called for | Purposes |
|---|---|---|---|
| entity, related, similar | Generic operation on the graph rules | A person or a service | Any purpose of the application |
| live | Generic operation, asked of the owning node | A person | inspection |
| ask | Generic operation: the mesh query flow | A person | Any purpose of the application |
| import | Generic operation through the intake, served by the API only | A service | Any purpose of the application |
| role_context | Plugin: counts documents and experts per skill and computes similar roles by shared skills (at least two, and at least half of the required skills of the smaller role, with skills joined by an approved SAME_AS link counted as one) | A person or a service | Any purpose of the application |
| skill_context | Plugin: fetches up to five released summaries with the person's identity | A person | Any purpose of the application |
| learning_sources | Plugin: drops superseded, stale and role profile documents and orders own company first | A person | learning |
| find_mentors | Plugin: consented experts without names | A person or a service | Any purpose of the application |
| vocabulary_export | Plugin: the group vocabulary as one pack | A service | career_mobility |
| inspection_profile, inspection_history | Plugins of the inspection domain | A person or a service | Any purpose of the application |
| record_inspection | Plugin of the inspection domain | A person | inspection |

A tool called for a person needs the person's reference and a company with a Mesh Node, because the owners' nodes decide with that person's identity. A tool that reads only the central graph also accepts a person of a company without a node.

```
                     ┌──────────── catalogue (one entry per tool) ────────────┐
  envelope ──► dispatcher ──► input schema ──► handler ──► answer ──► data schema check in tests
                                               │
                         ┌─────────────────────┴──────────────────────┐
                 generic operation                              named plugin
          entity related similar live ask import      role_context learning_sources inspection_profile ...
                 (graph rules decide)                   (own rules, same contract)
```

**Key insight:** "generic" means one contract and one dispatcher for every tool, not that every rule fits in a configuration file. A new application that needs only the generic operations adds a registry file and no code.

### 2.6 Data From Applications: The Import Tool

The import tool replaces the separate talent pack route. An application sends its packs through the same envelope. NeuralMesh checks each pack against the registry (is this pack id allowed for this application, and does its company have a Mesh Node) and then through the intake against the graph rules. The answer lists every pack as loaded, unchanged or refused with its reason. A pack whose content hash equals the one already loaded changes nothing, so an application may send the same packs again safely.

Each import rule in the registry also says what a pack may hold: for SkillForge's group pack only Skill entities and PREREQUISITE_OF links, and for a company talent pack only Role entities in that company's own namespace, REQUIRES_SKILL links that start at those roles, the company's own role profile datapoint (catalogue id T-01, with purposes the application serves) and role profile documents. A pack never carries approvals, experts or another datapoint, so an application cannot change what a node shares or approve a link on an owner's behalf.

| Pack | Rule | Result |
|---|---|---|
| `group.skillforge-skills` | Allowed for SkillForge, mapped to source `talent:group.skills` | Loaded, replaces the sample skills |
| `ceat.talent` and every pack of a company with a Mesh Node | Allowed, company connected | Loaded into `talent:<company>.talent` |
| A pack of a company without a Mesh Node | Allowed for SkillForge, company not connected | Refused with `company_not_connected` |
| A pack id outside the registry | Not allowed | Refused with `pack_refused` |
| A pack that breaks a graph rule | Intake error | Refused with the intake errors |
| A pack that holds more than its rule allows | Registry content rule | Refused with each item it may not hold |
| A pack whose company node does not answer the refresh | Node down | Kept but not recorded, refused with `node_unavailable`, and loaded at the next refresh or send |

SkillForge sends its packs from a job, 30 seconds after the API starts and then every hour. NeuralMesh holds the truth: it compares each pack with the one it keeps and loads only the packs that changed, so a NeuralMesh that lost its copy gets it back within one round. Each pack a company node holds is rebuilt into that node's talent pack, and the node reads its changed pack file without a restart.

```
  SkillForge job (every hour) ──► build packs ──► import envelope
                                                      ▼
                     registry: pack id allowed, company connected? ── no ──► refused, with the reason
                                                      ▼
                     same content as the kept pack? ───────────────── yes ─► unchanged
                                                      ▼
                     validator ──► keep the pack ──► rebuild the node's talent pack ──► node reloads the file
                                                      ▼
                     graph refreshed from the node exports ──► answer per pack: loaded, unchanged or refused
```

**Key insight:** data comes in through the same contract as questions, so an application never writes NeuralMesh's files and every refusal says which pack and why.

### 2.7 Publishing the Contract: Schemas, Version and Hash

NeuralMesh generates one bundle from the contract models and the catalogue: the contract version, the request schema, the answer schema, the problem codes, and the input and data schema of every tool, written in JSON Schema (the standard way to describe the shape of a JSON document). The bundle carries the SHA-256 hash (a fingerprint that changes when any byte of the content changes) of its own content. It is kept at `app/contracts/schemas/context_contract.json` with a lock file of version and hash, and it is served at `GET /api/v1/context/contract` to any registered application.

| Change | Kind | What happens |
|---|---|---|
| An optional input field, a data field, a tool or a problem code is added | Minor, 1.x | Readers ignore what they do not know and log an unknown problem code by its title |
| A field, a status or a tool is removed or renamed, or a meaning changes | Major, 2.0 | NeuralMesh serves 1.x and 2.0 side by side for one release. An unsupported major answers 400 `unsupported_version` with the supported versions |
| The six statuses | Fixed within a major version | A new status needs a major version |
| The bundle changes but the version does not | Refused by NeuralMesh's own test | The lock file holds the version and hash |

```
  contract models ─┐
                   ├──► generate ──► context_contract.json {version, sha256, request, answer, codes, tools{input, data}}
  tool catalogue ──┘                     │                                │
                                         ▼                                ▼
                               GET /api/v1/context/contract       pinned copy in each application
                                         └────────── same sha256? ────────┘
```

**Key insight:** the hash makes drift visible. If the running mesh and an application's pinned copy differ, a test says so before a page does.

### 2.8 Contract Tests on Both Sides

Three tests keep the two sides together. The first runs in NeuralMesh, the second in each application, and the third across both against a running mesh.

| Test | Where | What it proves |
|---|---|---|
| Bundle test | NeuralMesh | The bundle file equals what the code generates, the lock changes only with the version, and every tool's answers on the sample graph validate against the bundle |
| Pinned bundle test | Each application | Every request the application builds validates against its pinned copy, and its fake mesh refuses to serve an answer that does not validate, so a test cannot use a shape NeuralMesh never sends |
| Live contract test | Each application, against a running NeuralMesh | The running mesh has the same hash as the pinned copy, and the real client gets a valid answer from every tool it uses. It runs when the live URL and token are set and is skipped otherwise |
| Pinned sample data | NeuralMesh | NeuralMesh's own tests run on a copy of the node packs with pinned sample talent packs, so a live import cannot change what a test expects |
| Version guard | NeuralMesh | The script that publishes the bundle refuses a changed contract under an unchanged version, and the test fails when the code and the published file differ |

```
  NeuralMesh repo                         SkillForge repo
  ───────────────                         ───────────────
  code ──► bundle ══ equal? ══ file       pinned bundle ──► requests valid?   (test 2)
            │        (test 1)                   │       ──► fake answers valid?
            └──────── GET /contract ◄───────────┴──── live client, hash equal, every tool valid (test 3)
```

**Key insight:** the second test is the one that was missing. SkillForge's fake answered whatever a test wrote, so it agreed with SkillForge's guess instead of with NeuralMesh.

### 2.9 The SkillForge Side

SkillForge's request already follows the contract, so its changes are on the reading side, on two pages and in its tests. What leaves SkillForge stays as it is: ids, a level, the cleaned question, the purpose, the caller's company and role, and an opaque user reference.

| Area | Change |
|---|---|
| Answer reader | Accepts the six statuses and the problem object |
| Client | Reads the problem body of an HTTP 400, 403 or 404, and reports a contract fault apart from an outage |
| Role question | Asks the role's company (`nodes`) how it does the work of the role and what its documents say about the role's skills, a question built by code from the role, so the block "How CEAT does it" is answered from CEAT's documents. Shows the line of each problem code |
| Study material | Shows the line of each problem code |
| Talent packs | A job sends them every hour through the import tool, and NeuralMesh loads only the packs that changed |
| Tests | The pinned bundle, a fake mesh that validates every answer it serves, and the live contract test |
| Project notes | The Mesh row of the project instructions and the handoff record the change |

```
  Ask AI role question ──► role_context {role} ─────────┐
                       ──► ask {question, nodes:[ceat]} ─┤──► NeuralMesh ──► answer or refusal ──► page line
  growth path step ────► learning_sources {skill, level}┤
  CV vocabulary job ───► vocabulary_export {} ──────────┤
  talent pack job ─────► import {packs} ────────────────┘
```

**Key insight:** SkillForge keeps its request code and its fallbacks. It gains words for each refusal and a test that ties its fake to the real contract.

### 2.10 The MCP Gateway on the Same Contract

The MCP gateway (the Model Context Protocol server that AI clients such as a Claude session connect to) lists one tool per catalogue tool, except the import tool, which the API serves alone because the API is the one process that rebuilds packs and refreshes the graph. Its arguments are the envelope without the tool name, so `purpose`, `caller` and `input`, and its result is the same answer. A refusal comes back as a normal result with its status. An error of the identity or the envelope comes back as an MCP tool error with the problem as its text and nothing else, which is how the MCP specification asks a server to report errors a caller can correct. The gateway passes the arguments to the dispatcher as they come, so a wrong field gets the contract's refusal, not the MCP library's own error text, and the tool list still shows the contract's input schema.

```
  SkillForge  ──► REST POST /api/v1/context/<tool> ──┐
                                                      ├──► one dispatcher ──► catalogue ──► same answer, same refusal
  Claude      ──► MCP tools/call <tool>  ─────────────┘
```

**Key insight:** one dispatcher means an AI client and SkillForge get the same answers and the same refusals.

## 3. Where AI Agents Fit

A format fault, an unknown tool or a wrong field is a fixed fault with a fixed cause. An AI model that rewrites such requests at run time would hide the fault instead of removing it, could map a role to the wrong one without anyone seeing, and would add a model call of seconds to look-ups that take a fraction of a second. It must never touch the purpose, the company or the roles, because they decide what may be shared. AI belongs where meaning has to be read, with code checking what it proposes and a person confirming.

| Need | Who handles it | Why |
|---|---|---|
| A wrong field, version or tool | Code: a refusal with the fields and allowed values | The cause is fixed once in the calling code |
| An unknown id | Code: up to three closest ids by name | Cheap, repeatable and never a document |
| A missing company choice | The page or the calling agent asks the person | The person decides |
| A free-text phrase such as a CV line | AI proposes a skill, code checks it against the group vocabulary, the person confirms. SkillForge's CV Skill Mapper already works this way | Meaning has to be read |
| A written answer | Claude inside NeuralMesh, after the sharing rules, from released evidence only | As today |
| Purpose, company or roles | Never a model | They decide what may be shared |

```
  request ──► code checks (identity, envelope, input, policy) ──► tool ──► released evidence ──► Claude writes ──► code checks every sentence
                     ▲                                                                                   │
                     └── never a model                                              answer.check = passed or failed
```

**Key insight:** AI reads meaning and code enforces rules. Repairing a request is a rule problem.

## 4. Roadmap

| Step | Work | Done when |
|---|---|---|
| A | Contract models, application registry, tool catalogue, bundle and lock in NeuralMesh | The bundle test passes |
| B | Dispatcher, refusals and suggestions, one route, import tool, MCP gateway, Applications page from the registry | Every tool answers in the contract on the sample graph, and every refusal of section 2.4 has a test |
| C | SkillForge: answer reader, client, two pages, sender job, pinned bundle, validating fake, live test | SkillForge's tests pass against the pinned bundle |
| D | Live cross-check: SkillForge on a copy of its dev data against the running NeuralMesh | Every journey shows NeuralMesh content or the line of its problem code, and the talent packs are loaded |
| E | The next application registers and calls the generic operations | No NeuralMesh code changes |

```
  A contract ──► B dispatcher and tools ──► C SkillForge reads and tests ──► D live cross-check ──► E next application
  (NeuralMesh)   (NeuralMesh)                (SkillForge)                    (both)                  (registry only)
```

## 5. Sources

- Model Context Protocol specification, versioning page and tools page of version 2026-07-28, read on 2026-11-07: https://modelcontextprotocol.io/specification/versioning and https://modelcontextprotocol.io/specification/2026-07-28/server/tools. Input validation errors belong in the tool result so a model can self-correct (added in version 2025-11-25). The gateway's MCP library 1.30.0 speaks protocol version 2025-11-25.
- RFC 9457, Problem Details for HTTP APIs, July 2023: https://www.rfc-editor.org/rfc/rfc9457.html
- RFC 9413, Maintaining Robust Protocols, June 2023: https://www.rfc-editor.org/rfc/rfc9413.html. Silently tolerating faulty input lets a flaw become a standard.
- Pact, consumer-driven contract testing: https://docs.pact.io/
- Martin Fowler, Tolerant Reader, 9 May 2011: https://martinfowler.com/bliki/TolerantReader.html
- OWASP Top 10 for LLM Applications 2025, LLM05 Improper Output Handling and LLM06 Excessive Agency: https://genai.owasp.org/llmrisk/llm052025-improper-output-handling/ and https://genai.owasp.org/llmrisk/llm062025-excessive-agency/
- Anthropic, Writing effective tools for AI agents, 11 September 2025: https://www.anthropic.com/engineering/writing-tools-for-agents. Error responses should give specific, actionable guidance.
- RPG NeuralMesh, the knowledge mesh strategy plan, section 5.2 (the six tools and one evidence shape), and the context graph platform plan, section 4.7 (one set of tools for every application), in this folder.
- RPG SkillForge, the NeuralMesh context plan, section 3 (the request and answer SkillForge built), in `Docs - rpg skillforge/03_RPG_SkillForge_NeuralMesh_Context`.

## 6. Glossary

| Term | Meaning |
|---|---|
| Application registry | One file per application in `app/config/applications/` that says who the application is and what it may do |
| Bundle | The published contract: one JSON file with every schema of the contract and its hash |
| Catalogue | The list of tools in NeuralMesh's code, one entry per tool with its schemas and handler |
| Contract fault | A request NeuralMesh cannot read, caused by the calling code, not by an outage |
| Envelope | The one request shape: version, tool, purpose, caller and input |
| Evidence record | One fact a node allowed to leave, with its citation, mode, decision and rule |
| Generic operation | A tool that works on any domain through the graph rules, such as related or similar |
| JSON Schema | The standard way to describe the shape of a JSON document |
| Mesh Node | The server of one company that keeps its documents and applies its sharing rules |
| MCP | Model Context Protocol, the open protocol through which AI clients call tools |
| Pinned copy | An application's own copy of the bundle, checked against the running mesh by its hash |
| Plugin | A tool with its own rules that still uses the one request, answer and refusal |
| Problem | The object that says why a call was refused and what is needed |
| RFC 9457 | The internet standard for machine-readable error details of an HTTP API |
| SHA-256 hash | A fingerprint of a file that changes when any byte changes |
