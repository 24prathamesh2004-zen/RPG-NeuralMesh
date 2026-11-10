# RPG NeuralMesh: Architecture Design Review

Date: 2026-11-10. State reviewed: the code after the uploaded inputs, graph search and aggregate views of 2026-11-09 and 2026-11-10, 197 tests passing. The review reads the code as it would run with seven company nodes on separate networks, which is the deployment the strategy plan describes. Nothing in this review was tested on separate machines: the points under "Risks" are read from the code and name the file and function each one lives in.

The improvement plan of 2026-11-05 (`RPG_NeuralMesh_Architecture_Improvement_Plan.md`) listed 13 steps. Of those, these are done: the lock file (`requirements.lock`), PyJWT in place of python-jose, graph refresh behind the admin role, the six graph checks after every refresh (`services/graph_intake.py`), the node server split into one file per tool (`mcp_nodes/search.py`, `experts.py`, `live.py`, `aggregate.py`, 231 lines left in `server.py`) and a trace span per query step and node call (`observability/tracing.py`). This review does not repeat those. It adds the points that the uploads of 2026-11-09 and the separate-network deployment raise.

## 1. How a Question Flows

1. The Ask page (`ui/src/pages/AskPage.tsx`) calls `POST /api/v1/mesh/query` (`api/routers/mesh.py`), which runs `services/mesh_query.run_query`.
2. `run_query` runs the LangGraph flow of `services/neuralmesh.py`: `resolve` (concepts and companies named in the question, from the central graph), `route` (the companies to ask, by graph, by name or by the classifier model), `fan_out` (one `search` call per node), `scope` (re-rank and selection), `expand` (aggregate views of the released datapoints, then approved links and the summaries they point to), `build_answer` (the context builder, the answer model, the 7 checks) and `assemble`.
3. For each node the API mints a one-hour node token in the user's name (`PocNodeTokenProvider.token_for_node`) and calls the node's MCP tool over HTTP (`MCPNodeTransport`).
4. The node (`mcp_nodes/server.py`, one process per company) authorises the caller (`policy.authorize_caller`), ranks its own index (`knowledge_view.hybrid_rank`: FTS5 rows of `index.db` fused with Chroma vectors), decides each item against its policy file (`policy.evaluate_access`), writes the decision to its own hash-chained audit (`access_store.py`) and returns evidence records (`contracts/evidence.py`).
5. The orchestrator asks the node for the grouped views of released datapoints (`aggregate` tool, `mcp_nodes/aggregate.py`), and for the approved summaries that approved links point to (`summarize` tool).
6. The context builder (`services/context/builder.py`) fits the records into a fixed budget in a fixed order (question, routing, links, aggregate facts, summaries, chunks, withheld items). The answer model writes the answer, and `services/context/check.py` checks every sentence by code. A failed check gives one retry with the broken rule named, and a second failure shows the reason instead of the answer.
7. The central graph (`services/mesh_graph.py` on `services/graph_store.py`, SQLite with a NetworkX copy in memory) holds metadata only: entities and links from node exports (`export_graph` tool), group packs, application files and approvals. Text and vectors never leave a node.
8. Applications use one contract (`services/context_catalogue.py`, `services/context_api.py`, dispatched by `services/context_dispatch.py`) through the REST router (`api/routers/context.py`) or the MCP gateway (`mcp_gateway/server.py`).

## 2. What Is Right and Should Stay

- Policy is decided at the node, in `mcp_nodes/policy.py`, and every decision is written to the node's own audit chain in `mcp_nodes/access_store.py`. The centre cannot widen access by itself.
- A pack is replaced only after validation against all other packs, by a write to a temporary file and `os.replace` (`knowledge/packgen.rebuild_domain_pack`). A failed check changes nothing.
- The node opens `index.db` read-only (`mcp_nodes/knowledge_view.py`). A node never writes to its own index while it serves.
- A node that is down keeps its last export in the central graph, and a query marks it `NODE_UNAVAILABLE` and answers from the others (`MeshRuntime.refresh_from_nodes`, golden scenario S7).
- One evidence record shape at every boundary (`contracts/evidence.py`), and a cache key that holds the evidence ids, versions and modes (`services/context/cache.bundle_key`), so a changed document or a withdrawn grant changes the key and no stale answer is served.
- The graph is rebuilt into a new object and swapped in one assignment (`MeshGraph.rebuild`, `self.graph = graph`), so a query never reads a half-built graph.
- Aggregate views leave a node only at group level: the view carries an `n_*` column, every row under the minimum group size is dropped at the node (`mcp_nodes/aggregate.read_view`), and only a view the policy file names can be read.

## 3. Risks, Ranked by How Soon They Bite in a Seven-Network Deployment

| Rank | Risk | Where | What breaks | Design change |
|---|---|---|---|---|
| 1 | The API process writes an upload into the node's folder and rebuilds the node's pack, index and vectors itself | `services/uploads.add_upload`, `knowledge/packgen.rebuild_domain_pack`, `services/context_import.py` for talent packs | On separate networks the API has no path to the node folder. A shared mount would let the centre write what the node serves, which breaks the rule that the node owns its data. The API also needs the embedding model and the full knowledge base to rebuild one pack | Add a node tool `ingest_document(text, kind, title, tags, datapoint)` that validates and rebuilds inside the node. The API calls it, then calls `export_graph`. The talent import takes the same path |
| 2 | The index and the vectors are not swapped with the pack | `knowledge/packgen.write_index_rows` deletes and inserts into the live `index.db`, `VectorIndex.build` rewrites the Chroma folder | A node can serve a new `pack.json` with old FTS rows, or the reverse, for the seconds between the writes. The reload stamp (`LiveNode._read_stamp`) covers the pack, node, policy and experts files, not `index.db` or the Chroma folder | Build pack, index and vectors into a new version folder and switch with one rename. The node reloads that folder as one unit |
| 3 | The reload stamp is file times, and a failed reload is silent to the operator | `mcp_nodes/server.LiveNode._read_stamp`, `_reload_if_changed` | File times are unreliable on network file systems. A failed load keeps the old config and logs a warning, so a node can serve an old policy after an edit with nothing on a screen | Stamp a content hash of a manifest file, publish the loaded hash in `health`, and show on Mesh Nodes when a node's loaded hash differs from the expected one |
| 4 | The central graph has no export age | `MeshRuntime.refresh_from_nodes`, `MeshGraph.load_node_export`, `GraphStore` | A node that is down keeps its last export. Documents it has since retired stay findable at the centre until it answers again. Nothing shows how old an export is | Store `exported_at` and a content hash per node in `GraphStore`, show the age on Mesh Nodes and in graph answers, and hide a node's entities after a set age (for example 7 days) |
| 5 | The never-leave rule has two copies | Node side `policy.evaluate_access`. Centre side `MeshGraph.shown_to` and `never_leave_owner`, used in `services/graph_search.py`, `api/routers/mesh.py` and `services/context_tools.py` | The centre reads the `never_leave` flag of the exported datapoint, the node reads its policy file. After a policy change at the node and before the next export, the centre shows or hides the wrong entity | Let the node stamp each exported entity with its visibility at export time, and make `shown_to` read that field only |
| 6 | One shared HS256 secret signs the API session and every node token | `PocNodeTokenProvider` in `services/neuralmesh.py`, `mcp_nodes/auth.py` | Any node that holds the secret can mint a token for any other node. Separate company networks cannot share one secret | Asymmetric keys: the API signs with a private key, each node holds the public key and checks its own audience. The key id goes into the registry entry (`config/nodes.yaml`) |
| 7 | Caches and the runtime live in one process | `services/context/cache.py` (`ANSWER_CACHE`, `RERANK_CACHE`), `api/routers/mesh._DOMAINS_CACHE`, `lru_cache` on the runtime | With more than one API worker, or the gateway beside the API, each process holds its own caches and its own graph copy. Hit rates fall and two processes can hold two graph revisions for a moment | Keep one API worker until the load needs more. When it does, move the two caches into a table of `GraphStore` with a time to live, keyed as today |
| 8 | A stable expert id leaves the node in every result | `mcp_nodes/experts.find_experts_node` returns `expert_id` | An application can follow one person across questions and companies by the id, even without the name. In a small node, role plus skills plus company can point at one person | Return an id derived per caller and purpose (HMAC of the expert id), and let the node map it back at `request_intro` |
| 9 | No format version on packs and exports | `knowledge/validator.py`, `knowledge/packgen.py`, `services/graph_intake.py` | A node on an older pack format and a centre expecting a newer one fail validation as a whole, and because `rebuild_domain_pack` validates the new pack against every other pack, one old pack blocks every upload | Add `format_version` to every pack and export, accept the current and the previous version, and run a converter at node start |
| 10 | The default thread pool carries the runtime, the embedder and Chroma | `asyncio.to_thread(runtime)` in `api/routers/mesh.py`, `api/routers/context.py` and `mcp_gateway/server.py`, `asyncio.to_thread(self.mesh.rebuild)` | Embedding and vector calls compete with request handling for the same pool, so one slow rebuild delays every request's `runtime()` call | Give embedding and rebuild their own executor of one or two threads |

## 4. Module Boundaries

Clean, checked by import lines:

- `services/` imports nothing from `mcp_nodes/`. The only imports of `mcp_nodes` outside the package and the evaluations are in `api/routers/mesh.py` and `mcp_gateway/server.py`.
- `mcp_nodes/` imports `knowledge.embedder` and `knowledge.vector_index` only, never `services` or `api`.
- `knowledge/packgen.py` imports only `knowledge.*` and `shared.registry`.

Leaking:

- `api/routers/mesh.py` imports `AccessStore`, `load_node_config` and `verify_audit` from `mcp_nodes`. The centre opens node config and audit files directly, which works only on one machine. This is the same fault as risk 1.
- `mcp_gateway/server.py` imports `JwtTokenVerifier` from `mcp_nodes.auth`, so the gateway and the nodes cannot use different key schemes (risk 6).
- `knowledge/adapters.py` imports `services.ontology`, while `services/mesh_graph.py` imports `knowledge.adapters`. The lower layer imports the upper one. `ontology` belongs below `knowledge`.
- `services/uploads.py` imports `knowledge.packgen` and `knowledge.validator`, and `services/context_import.py` does the same with lazy imports. These are the calls that move behind the node tool of risk 1.
- `services/uploads.py` imports the private helper `_phrase_in` from `services.mesh_graph`.
- `evaluations/labelled_questions.py` and `evaluations/reworded_recall.py` call `search_node` and `load_node_config` directly, with no token and no transport, and `evaluations/golden_answers.py` imports the check and answer modules. The recall measures test the ranking code, not the path a request takes. `golden_answers.py` and `answer_time.py` go through the running API and do test that path.
- `mcp_nodes/server.py` is both the launcher and the public surface of the package (the re-exports of `search_node`, `summarize_node`, `find_experts_node`, `lookup_node`, `aggregate_node`), and it imports the private `_PACK_ROOT` from `server_config`.

## 5. Recommendations in Priority Order

1. Move upload writing and the talent import behind a node tool (`mcp_nodes/server.py`, `services/uploads.py`, `services/context_import.py`). This one change decides whether seven nodes on separate networks can take uploads at all.
2. Build pack, index and vectors into one version folder and switch it with one rename (`knowledge/packgen.py`, `mcp_nodes/knowledge_view.py`, `LiveNode`). A node must never serve a new pack with an old index.
3. Store the export time and a content hash per node, show the age, and hide a node's entities after a set age (`services/mesh_runtime.py`, `services/graph_store.py`, Mesh Nodes page). A down node otherwise keeps showing what it may have withdrawn.
4. Stamp visibility on exported entities at the node and make `shown_to` read it (`mcp_nodes/server_config.export_graph_node`, `services/mesh_graph.py`). One copy of the never-leave rule.
5. Per-node asymmetric keys for node tokens, with the key id in the registry (`services/neuralmesh.py`, `mcp_nodes/auth.py`, `config/nodes.yaml`). One shared secret means one node can act as any other.
6. A content-hash manifest per node, published in `health` and compared on Mesh Nodes (`mcp_nodes/server.py`, `api/routers/mesh.py`). A silent failed reload becomes a visible one.
7. `format_version` on packs and exports with a converter at node start (`knowledge/validator.py`, `services/graph_intake.py`). One old pack must not block the whole mesh.
8. Per-caller derived expert ids (`mcp_nodes/experts.py`). A stable id lets an application follow one person.
9. A separate executor for embedding and graph rebuild (`services/mesh_graph.py`, `knowledge/embedder.py`). Request handling stops waiting behind a rebuild.
10. Remove the leaking imports: node files opened from the API, `knowledge.adapters` importing `services.ontology`, the private `_phrase_in` import, and the evaluations that bypass the transport. The recall measures should call the node through the same transport as a request.

## 6. What Was Checked and What Was Not

Checked: the import lines by grep, the code paths named above by reading, the graph swap in `MeshGraph.rebuild`, and that `bundle_key` holds evidence ids, versions and modes. Not checked: any behaviour on separate machines or network file systems, the behaviour with more than one API worker, and the timing of the index write against a node read. The risks are design readings, not reproduced faults.
