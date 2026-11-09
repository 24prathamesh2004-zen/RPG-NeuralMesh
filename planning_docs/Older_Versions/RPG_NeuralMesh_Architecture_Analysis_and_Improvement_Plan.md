# RPG NeuralMesh: Architecture Analysis and Improvement Plan

Date of the analysis: 2026-11-05. Code state: commit `e313d01` on branch `dev_raja`.

## Goal

Keep the mesh easy to run, change and check as it grows from the four synthetic pilot nodes to real subsidiaries, and raise the quality of what it returns. Each step below names a problem found in the code or in the checks, the change that removes its cause, and the check that proves the change.

## Contents

1. Vector Search: What Is Used Now and What Was Planned
2. The Architecture as Built
3. Problems Found
4. Improvement Steps
   - 4.1 Reproducible build without the unused template parts
   - 4.2 One graph for every process
   - 4.3 Security of identity and graph changes
   - 4.4 Retrieval quality
   - 4.5 Vector storage at scale
   - 4.6 Graph store at scale
   - 4.7 Graph quality checks after every refresh
   - 4.8 Tracing with the OpenTelemetry conventions for AI
   - 4.9 Code structure and contract tests with SkillForge
   - 4.10 Suggested links between documents
5. Roadmap
6. Sources

```
                      improvement order
  4.1 build ──► 4.2 one graph ──► 4.3 security ──► 4.4 retrieval ──► 4.7 graph checks
                                                         │
                         4.5 vector store ◄── triggers ──┴──► 4.6 graph store
  4.8 tracing and 4.9 code structure run beside the others, 4.10 comes last
```

## 1. Vector Search: What Is Used Now and What Was Planned

Vector search is in use, but no vector database server is.

- **Inside each node:** one FAISS index file for each knowledge pack (`build/vectors.faiss`) and a SQLite chunk table beside it (`build/chunks.db`). FAISS is Meta's open-source library for searching vectors. The node runs keyword search (SQLite FTS5) and vector search on the same question and merges the two lists by reciprocal rank fusion, which scores each document 1 divided by (60 plus its rank) in each list and adds the scores. Code: `app/knowledge/vector_index.py` and `app/mcp_nodes/knowledge_view.py`.
- **In the central mesh:** the names, aliases and descriptions of the 44 concepts and skills are embedded once and held as a NumPy array in memory (`app/services/mesh_graph.py`). A question that matches no name is compared with this array, and a score of 0.45 or more counts. The strategy plan named a small FAISS index for this. A plain array gives the same result for 44 entries.
- **Size today:** 46 chunks in 19 packs, so every search is exact and takes well under a millisecond.
- **What was planned:** the strategy plan keeps FAISS files while a pack holds fewer than 50,000 chunks, switches to the HNSW index type above that, and keeps a store interface (`VectorIndex.build` and `VectorIndex.search`) so that a large node can move to Qdrant or pgvector without changes elsewhere. The Qdrant settings and the `qdrant-client` package in `requirements.txt` come from the accelerator template and are not used.

So a vector database is not needed at the pilot size. Section 4.5 states when one is needed and which one fits.

## 2. The Architecture as Built

```
  SkillForge ──► MCP gateway :8100 ─┐            Ask page, Mesh Nodes, Governance (React :5173)
                                     │                         │
                                     ▼                         ▼
                      ┌──────────── mesh API :8000 (FastAPI) ────────────┐
                      │ resolve ► route ► fan_out ► scope ► expand ►       │
                      │ build_answer ► assemble   (LangGraph)              │
                      │ mesh graph: SQLite tables + NetworkX in memory     │
                      │ context builder, 7 code checks, model policy       │
                      └───────┬───────────┬───────────┬───────────┬───────┘
                              │ MCP       │ MCP       │ MCP       │ MCP
                           CEAT :8101  KEC :8102  Zensar :8103  Harrisons :8104
                           each node: policy, FTS5 + FAISS, grants, audit
```

| Layer | Built with | Holds | Owner of the data |
|---|---|---|---|
| Knowledge packs | JSON packs checked against a schema, built by `knowledge/packgen.py` | Documents, chunks, concepts, skills, experts of one company | The company's node |
| Node search | SQLite FTS5, FAISS exact search, reciprocal rank fusion | Text that may leave the node in its exposure mode | The company's node |
| Mesh graph | Two SQLite tables, NetworkX in memory | Metadata only: IDs, titles, owners, concepts, skills, roles, approved links | The mesh team, filled from node exports and group packs |
| Query flow | LangGraph, 7 steps | One question at a time | None, nothing is stored except the caches |
| Context layer | Builder with a 12,000-character budget, 7 code checks, model policy, answer and re-rank caches | Evidence records of one question | None |
| Context API | FastAPI routes and an MCP gateway with 6 tools | Evidence records for SkillForge | The owning node decides on each record |
| Screens | React, vis-network graph explorer | Nothing | None |

What holds up well and should stay:

- Text and vectors never leave the node, and the central graph holds only metadata. This rule removes the largest privacy risk, and every later step keeps it.
- One record shape (the evidence record contract, schema version 1.0) at every boundary, now checked by a test on every context tool.
- Removed items are retired, never deleted, so an audit can always show what the graph held.
- Code makes the decisions that can be tested (policy, routing, the 7 checks), and a model only writes the answer from the selected evidence.

## 3. Problems Found

Each point was found by reading the code at commit `e313d01` or by the checks run on 2026-11-05.

| Area | Finding | Effect | Priority | Step |
|---|---|---|---|---|
| One graph for every process | The MCP gateway runs as its own process with its own copy of the graph in memory, refreshed only when the gateway starts. The API and the gateway both write to the same SQLite file when they start | A talent import or a graph refresh through the API is not seen by SkillForge's tools on the gateway until the gateway restarts | High | 4.2 |
| Graph changes | Any signed-in user can call `/graph/refresh`. Any demo account can approve either company's side of a link | The rule that both owners approve a link is simulated, not enforced by identity | High | 4.3 |
| Identity | Tokens are signed with one shared secret (HS256) through `python-jose`, whose last release was in 2021 | A leaked secret signs tokens for every company. The library gets no security fixes | High before real data | 4.3 |
| Build | No package in `requirements.txt` has a version pin, no lock file, no CI pipeline | A rebuild next month can install different versions of LangGraph, FastAPI or FAISS and change behaviour without any code change | High | 4.1 |
| Template parts | Temporal, Postgres, Redis, Qdrant and Azure settings, the `agents/`, `workflows/`, `workers/`, `db/` and `ingestion/` folders, the example router and placeholders such as `__BACKEND_PORT__` in the Dockerfile | The deployment files do not describe the running system, and new readers cannot tell which parts are live | Medium | 4.1 |
| Retrieval | Reworded golden questions: every required datapoint in the top 10 for 12 of 18 with hybrid search (7 of 18 with keyword search alone) | 6 reworded questions miss a required datapoint | Medium | 4.4 |
| Vector index | `VectorIndex.search` reads the FAISS file from disk on every search | No effect at 46 chunks. At 50,000 chunks a pack index is about 77 MB and would be read again for each question | Low now | 4.5 |
| Graph data | The concept "ESG water and energy" and the domain "mesh" have no links. The concept "supplier quality" is mentioned by no document | These entities can never route a question | Low | 4.7 |
| Code size | `mcp_nodes/server.py` holds 869 lines: policy calls, search, summarize, experts, export and the MCP wiring | A change to one tool means reading all of them | Low | 4.9 |

How each step is worked through:

```
  finding ──► change that removes the cause ──► test that fails before and passes after
                                                    │
                                                    ▼
                    full suite + golden 10 of 10 + live check + browser check ──► status document
```

## 4. Improvement Steps

### 4.1 Reproducible Build Without the Unused Template Parts

Pin every package and remove what the mesh does not run, so that the same commit always builds the same system.

| Change | Detail |
|---|---|
| Lock file | Generate `requirements.lock` with exact versions and hashes (`uv pip compile` or `pip-compile`) from the versions that passed on 2026-11-05: langgraph 1.2.19, langchain-core 1.7.5, fastapi 0.162.0, mcp 1.30.0, faiss-cpu 1.15.1, networkx 3.7, onnxruntime 1.31.1, pydantic 2.14.2. `package-lock.json` already does this for the UI |
| CI pipeline | On every push: the test suite, `tsc --noEmit`, the UI build, the pack validator and the canary check. The golden and live checks need the running stack and stay manual until a test environment exists |
| Remove template parts | Temporal, Redis, Postgres, Qdrant and Azure settings and packages, the folders `agents/`, `workflows/`, `workers/`, `ingestion/`, `db/`, the example router and the Alembic setup, after checking that nothing of the mesh imports them. They are used today only by the example router and by each other |
| Deployment files | Replace the placeholders in `Dockerfile` and `docker-compose.yml` with the real services: four nodes, the API, the gateway and the UI |

```
  requirements.txt (ranges) ──► lock file (exact + hashes) ──► CI installs only from the lock
```

**Key insight:** LangGraph moved from 1.0 to 1.2 within seven months, with new streaming and error-handling options. Without a lock file the mesh changes when its libraries change, not when its code changes.

### 4.2 One Graph for Every Process

The graph has one writer and every reader sees its changes.

| Change | Detail |
|---|---|
| One writer | Only the API writes the graph (node exports, group packs, talent imports, link reviews). The gateway stops refreshing from the nodes at start |
| Readers follow a revision | The store keeps a revision number that each write increases. Before a query, a reader compares the stored revision with the one it loaded and rebuilds its NetworkX copy when they differ. A rebuild of the 161 entities and 327 relationships stored today takes milliseconds |
| Test | Import a talent pack through the API, then call `role_context` through the gateway and get the new role without a restart |

```
  API (writer) ──► SQLite: entities, relationships, revision = 42
                                         ▲
  gateway (reader): loaded 41 ──► reload ┘   then answers from revision 42
```

**Key insight:** the strategy plan names "more than one service writing to the graph" as a trigger for Neo4j. Today two services write only because the gateway refreshes at start. One writer removes that trigger, and the revision check makes several API workers safe as well.

### 4.3 Security of Identity and Graph Changes

The identity of the caller decides what changes the graph and what a node releases.

| Change | Detail |
|---|---|
| Graph refresh | `/graph/refresh` needs the mesh admin role |
| Link approval | The approving company is taken from the caller's token, not from the request, so a CEAT owner can approve only the CEAT side |
| Token library | Replace `python-jose` with PyJWT. PyJWT requires the `aud` (audience) claim where python-jose did not, so every token gets an audience: the API, the gateway or one node |
| Corporate sign-in | Microsoft Entra ID (Microsoft's corporate sign-in) in place of the shared secret, as phase 5 of the plan states. The orchestrator gets a new token for each node with the on-behalf-of flow (OAuth 2.0 token exchange, RFC 8693), which keeps the user as the subject. The MCP specification does not allow a server to pass on the token it received |
| MCP version | The current MCP specification is the version of 2026-07-28. It removes the session handshake and aligns authorization with OAuth 2.1 and OpenID Connect. The package pin `mcp<2` stays until the Python SDK of that version is checked against the four nodes and the gateway |

```
  user ──► Entra ID ──► token for the API
           API ──► on-behalf-of exchange ──► token for the CEAT node (subject = user, actor = mesh)
```

**Key insight:** the node already decides on every record with the caller's company and purpose. The weak point is how the caller is proven, so this step changes the proof and leaves the policy as it is.

### 4.4 Retrieval Quality

Measure retrieval on labelled questions first, then change one thing at a time.

| Change | Detail |
|---|---|
| Labelled set | Grow the 18 reworded questions to about 200 questions, each with the documents it must find, built from the synthetic packs. Measure recall at 10 (the share of required documents in the top 10) and nDCG at 10 (normalised discounted cumulative gain, which also rewards a required document placed higher) |
| Aliases first | Add the missing aliases and tags that the 6 failing reworded questions need, then measure again. This needs no new component |
| Re-ranker at the node | A cross-encoder scores the question and each candidate passage together, after hybrid search. The open model bge-reranker-v2-m3 (about 570 million parameters, runs on a processor) re-orders the top 30 candidates to a top 10. Kept only when recall at 10 rises on the labelled set |
| Embedding model | Compare all-MiniLM-L6-v2 with BGE-M3 (100 or more languages, 8,192 tokens of context, MIT licence) and multilingual-e5-small on the labelled set, including Hindi and Malayalam questions. One model is pinned for the whole group |

```
  question ──► FTS5 top 30 ┐
                           ├─► rank fusion ──► re-ranker ──► top 10 ──► policy ──► records
  question ──► FAISS top 30┘
```

**Key insight:** a re-ranker or a new model is a cost on every query. The labelled set turns "seems better" into a number, so a component stays only when the number rises.

### 4.5 Vector Storage at Scale

Keep FAISS files at each node and move a node to a vector database only when a trigger holds.

| Trigger for a node | Why |
|---|---|
| More than 50,000 chunks in one pack | Exact search slows and an approximate index (HNSW) is needed |
| Documents change more than once a day | A FAISS flat file is rebuilt as a whole, while a database updates one document's vectors |
| Search must filter by datapoint, mode or date inside the index | FAISS stores no metadata of its own, so filtering happens after the search |

| Option | Fit for a node | Point to check |
|---|---|---|
| FAISS files (now) | No server, the index lives beside the pack | Keep the index open between searches instead of reading the file on each search |
| sqlite-vec | Vectors in the SQLite file the node already uses, writes one row at a time | Exact search only, check speed above 100,000 chunks |
| pgvector | A node that already runs Postgres. Since version 0.8.0, filtered HNSW search keeps scanning until enough rows pass the filter (`hnsw.iterative_scan`, off by default) | Needs Postgres at the node |
| Qdrant | Large nodes, filter fields in the index. The documentation recommends one collection with a tenant field, and version 1.16 added moving a large tenant to its own shard | One more server to run. Each node runs its own, so no collection ever holds two companies |

```
  node with < 50,000 chunks:   pack ──► FAISS file (open once, kept in memory)
  node above a trigger:        pack ──► VectorIndex interface ──► sqlite-vec, pgvector or Qdrant
```

**Key insight:** the privacy rule decides the shape. Vectors of one company stay in that company's node, so the mesh never needs one shared vector database, and each node chooses its store by its own size.

### 4.6 Graph Store at Scale

SQLite with NetworkX stays until a trigger of the strategy plan holds.

| Trigger | State on 2026-11-05 |
|---|---|
| More than 1 million relationships | 327 stored, retired ones included |
| Paths of three or more steps on the screens | The tree view shows two steps, built in the browser |
| More than one service writing to the graph | Two today, one after step 4.2 |

| Option | Fit | Point to check |
|---|---|---|
| Neo4j | The most used graph database, Cypher queries, the graph view of cobol_intel uses it | Community Edition is GPLv3, Enterprise and Aura are commercial, which matters for commercialisation |
| FalkorDB | Graph database aimed at GraphRAG, built on Redis | The large speed figures come from its own benchmarks. Check the licence |
| Apache AGE | Graph queries inside Postgres | Little evidence of use at this kind of workload |
| Kùzu | Not an option | Repository archived in October 2025 |

**Key insight:** the store interface (`GraphStore`) is what makes the later move cheap. Every graph read and write goes through it already, so the move changes one class and its tests.

### 4.7 Graph Quality Checks After Every Refresh

The checks of the 2026-11-05 review become code that runs after each refresh and is shown on the Mesh Nodes page.

| Check | Rule | Result on 2026-11-05 |
|---|---|---|
| Dangling link | Both ends of every live link are live entities | 0 |
| Type signature | Each link type joins the entity types it allows, for example MENTIONS joins a document to a concept | All 17 types hold |
| Isolated entity | Every live entity has at least one live link | 2: the domain "mesh" and the concept "ESG water and energy" |
| Concept without a document | Every concept is mentioned by at least one document | 1: "supplier quality" |
| One company link per role | Each live role has exactly one live ROLE_AT link | 3 roles, 3 links |
| Live link on a retired entity | No approved link touches a retired entity | 0 |

```
  refresh ──► graph checks ──► counts on Mesh Nodes ──► a failed rule shows the entity IDs
```

**Key insight:** the two defects fixed on 2026-11-05 (company aliases replaced by the group pack, a second role link never retired) were found by reading the data, not by a test. A rule that runs after every refresh finds the next one on the day it appears.

### 4.8 Tracing With the OpenTelemetry Conventions for AI

The OpenTelemetry semantic conventions for generative AI define span names for agents, tools and model calls (for example `invoke_agent` and `execute_tool`), and separate conventions for MCP clients and servers. Both were still marked "Development" in May 2026, and in 2026 they moved to their own repository.

| Change | Detail |
|---|---|
| Spans | One span for each LangGraph step, each node call and each model call, with the trace ID the mesh already writes to the audit |
| Version | Pin the convention version in the code, because names can change between releases |
| Content | Question text and answers are not recorded in spans. Recording them is opt-in in the conventions, and the audit already holds what is needed |

**Key insight:** the audit answers "who saw what". Traces answer "which step was slow or failed", and the shared trace ID links the two.

### 4.9 Code Structure and Contract Tests With SkillForge

| Change | Detail |
|---|---|
| Split the node server | `mcp_nodes/server.py` (869 lines) into one module for each tool (search, summarize, experts, export, access) and one for the MCP wiring. The public functions stay, so the tests do not change |
| Contract tests both ways | The JSON schema of the evidence record is exported from `contracts/evidence.py`. The mesh test checks every tool output against it, and SkillForge's tests check their parser against the same file |
| Status document | The status document stays the single record of checks, with the date and the commit of each run |

**Key insight:** SkillForge reads the mesh only through the contract, so a schema file that both sides test against catches a change before either side ships it.

### 4.10 Suggested Links Between Documents

Phase 5 of the plan adds a job that suggests links between documents of different companies (CORROBORATES, CONFLICTS_WITH, ADDRESSES_GAP, SUPERSEDES).

| Choice | Reason |
|---|---|
| Suggestions only | A suggested link is stored as proposed and needs the owner of each side to approve it, as links are approved today |
| One document at a time | Tools of the LightRAG kind extract entities and relations as each document arrives, while the Microsoft GraphRAG tool re-runs its community clustering over the whole set when documents are added. The mesh needs the first behaviour, because packs are republished one at a time |
| Metadata as input | The job reads titles, concepts and approved summaries, never restricted text, so it runs centrally without breaking the privacy rule |

**Key insight:** the approval step already exists. A suggestion job adds candidates to the same review queue, so the graph never holds a link that no owner approved.

## 5. Roadmap

| Order | Step | Effort | Done when |
|---|---|---|---|
| 1 | 4.1 Lock file, CI, template parts removed | 2 days | A clean checkout installs from the lock and CI passes |
| 2 | 4.2 One writer, readers follow the revision | 1 day | The talent import is seen through the gateway without a restart |
| 3 | 4.3 Refresh role, approval by token, PyJWT | 2 days | A KEC owner cannot approve the CEAT side, a user without the admin role gets 403 on refresh |
| 4 | 4.7 Graph checks after every refresh | 1 day | The six rules run on refresh and show on Mesh Nodes |
| 5 | 4.4 Labelled set, aliases, re-ranker trial, model comparison | 2 weeks | Recall at 10 measured on about 200 questions, each change kept only when it rises |
| 6 | 4.9 Node server split, shared contract schema | 3 days | Both repositories test against one schema file |
| 7 | 4.8 Tracing | 2 days | One trace shows every step of a question |
| 8 | 4.3 Entra ID and on-behalf-of tokens | With phase 5 | No shared secret signs any token |
| 9 | 4.5 and 4.6 Vector and graph store moves | When a trigger holds | The trigger is reached and the move passes the full suite |
| 10 | 4.10 Link suggestion job | With phase 5 | Suggestions appear as proposed links for both owners |

The efforts are estimates for one developer who knows the code. They are not measured.

## 6. Sources

Read from the code and the checks:

- `app/knowledge/vector_index.py`, `app/mcp_nodes/knowledge_view.py`, `app/services/mesh_graph.py`, `app/services/graph_store.py`, `app/services/mesh_runtime.py`, `app/mcp_gateway/server.py`, `app/api/auth.py`, `app/requirements.txt`, `app/Dockerfile`, `app/docker-compose.yml`
- `planning_docs/RPG_NeuralMesh_Knowledge_Mesh_Strategy_Plan_v2.md` (sections 3.4 and 3.5) and `planning_docs/RPG_NeuralMesh_Implementation_Status.md`

Public sources, read on 2026-11-05 (several are vendor or practitioner pages, as marked):

- Qdrant 1.19 release: https://qdrant.tech/blog/qdrant-1.19.x/
- Qdrant multitenancy guide: https://qdrant.tech/documentation/examples/multitenancy/
- pgvector 0.8.0 iterative index scans: https://docs.pgedge.com/pgvector/v0-8-0/iterative-index-scans/ and https://aws.amazon.com/blogs/database/supercharging-vector-search-performance-and-relevance-with-pgvector-0-8-0-on-amazon-aurora-postgresql
- sqlite-vec and FAISS in Llama Stack (project documentation): https://ogx-ai.github.io/docs/providers/vector_io/inline_sqlite-vec
- Embedding models for RAG in 2026 (vendor blogs): https://www.zilliz.com/blog/choose-embedding-model-rag-2026 and https://blog.premai.io/best-embedding-models-for-rag-2026-ranked-by-mteb-score-cost-and-self-hosting
- Re-rankers for RAG (practitioner pages): https://wz-it.com/en/knowledge/ki/hybrid-search-reranking/ and https://www.markaicode.com/bge-reranker-cross-encoder-reranking-rag/
- MCP specification of 2026-07-28 (secondary summaries, the official page is modelcontextprotocol.io): https://workos.com/blog/mcp-2026-spec-agent-authentication and https://dev.to/rabinarayanpatra/why-mcp-2026-07-28-spec-drops-sessions-and-goes-stateless-1gd
- On-behalf-of tokens for MCP servers with Entra ID: https://zuplo.com/learn/mcp/authentication/azure-managed-identity and https://learn.microsoft.com/en-us/answers/questions/5766622/example-for-on-behalf-of-flow-in-azure-ai-foundry
- python-jose and PyJWT: https://github.com/tiangolo/fastapi/pull/9587 and https://github-redirect.dependabot.com/python-social-auth/social-core/pull/819
- LangGraph releases: https://releasebot.io/updates/langchain-ai/langgraph and https://dev.to/x4nent/langgraph-12-deep-dive-per-node-timeouts-error-handlers-graceful-shutdown-deltachannel--2mp2
- Graph databases for GraphRAG (vendor pages): https://www.puppygraph.com/blog/falkordb-vs-neo4j and https://arcadedb.com/blog/open-source-knowledge-graph-graphrag-databases-compared/
- LightRAG and GraphRAG updates (secondary): https://www.ai-bites.net/lightrag-simple-and-efficient-rival-to-graphrag/ and https://aitoolsatlas.ai/compare/graphrag-vs-lightrag
- OpenTelemetry conventions for generative AI (vendor blog): https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
- Retrieval metrics: https://blog.premai.io/rag-evaluation-metrics-frameworks-testing-2026 and https://www.kunalganglani.com/blog/rag-evaluation-metrics-retrieval-quality.md
