# RPG NeuralMesh: Implementation Status of the Knowledge Mesh Plan v2

Branch `dev_raja`, 2026-11-05. Nothing is committed.

## What Is Built, by Phase

| Phase | Built | Where |
|---|---|---|
| 0 | One node registry read by the API, orchestrator, nodes and pack builder. A node starts from its registry entry with `python -m mcp_nodes <id>`, no module file. Node profiles from listed metadata. A development stack script (start, stop, status, restart a node, restart the API). Placeholders removed from `api/main.py` and the Makefile | `app/config/nodes.yaml`, `app/shared/registry.py`, `app/mcp_nodes/__main__.py`, `app/scripts/dev_stack.sh`, `app/Makefile` |
| 1 | 19 packs from the YAML, validated with the group packs. A FAISS index per pack over the text the node may release. Keyword search with Porter stemming, vector search and the routed concepts merged by reciprocal rank fusion. Purpose checked per datapoint. Every returned item is an evidence record. Canary check over the chunk tables. Injection sentences removed from the text users receive, with the record flagged | `app/knowledge/`, `app/mcp_nodes/knowledge_view.py`, `app/contracts/evidence.py`, `app/neuralmesh_kb_pack/kbgen.py` |
| 2 | `export_graph` tool, central graph store with link reviews, loading from node exports and group packs, routing with the narrowing rule, classifier fallback, optional node choice, graph view and link approvals on the screens. Removed documents, roles and nodes are retired in the graph, never deleted | `app/services/graph_store.py`, `app/services/mesh_graph.py`, `app/api/routers/mesh.py`, UI pages |
| 3 | Scope (top 12 documents round-robin by node rank, re-rank that demotes but never drops, and never leaves an empty answer), expand with policy filter, context builder with budget and omission note, answer, seven code checks, model policy with strict mode, model-call audit, answer and re-rank caches | `app/services/context/`, `app/services/neuralmesh.py`, `app/config/model_policy.json` |
| 4 (NeuralMesh part) | Six context tools under `/api/v1/context` and on the MCP gateway, talent pack import, purposes `learning` and `career_mobility` | `app/services/context_api.py`, `app/api/routers/context.py`, `app/mcp_gateway/server.py` |

## Checks Run on 2026-11-05

| Check | Result |
|---|---|
| Test suite (`make test`) | 89 passed, including the 44 tests that existed before |
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
- **18 reworded questions, not 20.** S4 is judged on experts, so it is left out of the recall measure.
- **Cloud model and Confidential evidence.** The policy file keeps the plan's rule: no Confidential or Restricted record goes to a cloud model, in development too. With a Groq key only Internal bundles get a written answer.
- **Canary list at the centre.** In development the check step reads the canary strings of the synthetic packs. A real deployment has no canaries.
- **Seven check rules, not six.** Rule 7 limits the answer to 10 sentences, the limit the prompt states.

## Not Done

- Phase 5: Entra ID, Neo4j, the link extraction job, wave 2 nodes.
- A written answer from a real model, and the 10-second median answer time. With the stand-in a query takes 0.05 to 0.2 seconds, which says nothing about a model's share.
- Aggregate views (LIVE mode) as evidence of kind `aggregate` in a query. The numbers of the views reach answers through the approved summaries only.
- The real SkillForge export of 17 roles and 57 requirements, journeys A, B and C in SkillForge, and the 50 labelled CVs.
- The Expert Finder card shows role, company, skills and evidence, not the pseudonymous expert ID. The scope presets of the top bar other than "All connected companies" are fixed lists.
- The embedding model is read from Chroma's cached ONNX copy on this machine. Another machine needs `NEURALMESH_EMBEDDING_MODEL_DIR`.

## Open Points for the Product Owner

- Should single words such as "latex" or "cold-chain" resolve to a concept, or should the vocabulary hold phrases only? Today a question with no matching phrase goes to the classifier and then to the user's own node choice.
- Should the aggregate views of O-05, E-02 and O-06 be returned as evidence by a query, as the golden file's `must_include_data` suggests?
- Should the Expert Finder show the expert ID next to the role?

## Interface for SkillForge

- **Talent export.** One `group.skills` pack (skills with aliases, `PREREQUISITE_OF`) and one `<company>.talent` pack per company (roles in the company namespace with aliases, T-01 role profiles, `REQUIRES_SKILL` with level and importance). POST to `/api/v1/context/talent-packs` with a service token holding `talent_exporter`. An unknown skill ID or a pack carrying experts is refused. A role that a later export no longer lists is retired and `role_context` returns 404 for it.
- **Records.** Every tool returns evidence records with `schema_version` 1.0, including `stale`, `superseded_by` and `suspicious`. `learning_sources` drops superseded, stale and role-profile documents and lists the reason, and returns documents the node did not release under `not_released`.
- **Contact details.** The mesh strips email addresses and phone numbers from a typed question as well.
- **Mentors.** `find_mentors` exists on the mesh and returns no names. Whether SkillForge uses it in its first release does not change the mesh.
- **Service token.** `python -m scripts.issue_service_token` in development.

## How to Run the Stack

From `app/`: `bash scripts/dev_stack.sh start` starts the stand-in model, the four nodes, the API with the stand-in policy, the gateway and the Vite UI. `make test`, `make live-check`, `python -m evaluations.golden_answers`, `make eval-recall` and `evaluations/ui_render_check.mjs` are the checks. `bash scripts/dev_stack.sh stop` stops everything.
