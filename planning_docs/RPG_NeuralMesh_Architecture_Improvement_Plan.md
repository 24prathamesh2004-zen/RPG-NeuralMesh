# RPG NeuralMesh: Architecture Improvement Plan

Date: 2026-11-05.

## What Stays as It Is

- Text and vectors stay inside each company's node. The central graph holds metadata only.
- Every boundary uses one record shape, the evidence record contract (schema version 1.0).
- Code decides policy, routing and the 7 answer checks. A model only writes the answer from the selected evidence.
- Removed items are retired, never deleted.

## Done on 2026-11-05

| Change | What it improves | Proof |
|---|---|---|
| Vector store: embedded Chroma in each pack in place of the FAISS file and its chunk table | Each chunk is stored with its fields, and a rebuild embeds only new or changed chunks | Same documents in the same order as FAISS for all 30 test questions over the 19 packs |
| A company entry comes only from that company's node export | "Harrisons" or "KEC" alone narrows a question to that company | Live routing check |
| One link from each role to its company | A role dropped from a talent pack loses its link | Test and live graph count: 3 roles, 3 links |
| Every record of the context tools and of `/mesh/query` follows the contract | SkillForge can parse every reply with one schema | Contract test on every tool |

Checks after these changes: 90 tests passed, golden questions 10 of 10, live wiring check 24 of 24, browser check 22 of 22, reworded questions 12 of 18.

## Next Steps

| No. | Step | What it improves | Effort |
|---|---|---|---|
| 1 | Pin every package version in a lock file and run the tests, the type check and the UI build on every push | The same commit always builds the same system | 1 day |
| 2 | Remove the unused template parts: Temporal, Postgres, Redis, Qdrant and Azure settings, the example folders and the placeholders in the Dockerfile | The deployment files describe the system that runs | 1 day |
| 3 | Only the API writes the graph, and the MCP gateway reloads its copy when the stored graph changes | SkillForge sees a talent import or a refresh without a gateway restart | 1 day |
| 4 | Graph refresh needs the admin role, and link approval takes the company from the user's token | Only a company's own owner can approve its side of a link | 1 day |
| 5 | Replace the token library `python-jose` (no release since 2021) with PyJWT, and give each token one audience: the API, the gateway or one node | Security fixes reach the mesh, and a token works only for the service it was issued to | 1 day |
| 6 | Run six graph checks after every refresh (dangling link, link type, isolated entity, concept without a document, one company link per role, live link on a retired entity) and show the result on Mesh Nodes | A data fault shows on the day it appears | 1 day |
| 7 | Grow the 18 reworded test questions to about 200 with their expected documents, and add the aliases the 6 failing questions need | Search quality is a measured number, and the 12 of 18 rises | 1 week |
| 8 | Try a re-ranker (bge-reranker-v2-m3) on the top 30 results and a multilingual embedding model (BGE-M3), and keep each only if it raises the score of step 7 | Better top 10 results, also for Hindi and Malayalam questions | 1 week |
| 9 | Split the node server (869 lines) into one file per tool, and share one contract schema file with SkillForge for both test suites | A change to one tool touches one file, and a contract change fails a test on both sides | 3 days |
| 10 | Add an OpenTelemetry trace with one span per query step, node call and model call, linked to the audit by its trace ID | A slow or failed step shows in the trace | 2 days |
| 11 | Microsoft Entra ID sign-in, and a new token for each node issued in the user's name (the on-behalf-of flow) | No shared secret signs any token | With phase 5 |
| 12 | Move a node to pgvector or a Chroma server, or the graph to Neo4j, only when a size limit is reached: 50,000 chunks in a pack, or 1 million relationships | Each move happens only when the size needs it | When a limit is reached |
| 13 | A job that suggests links between documents of different companies, stored as proposed links for both owners to approve | More cross-company links, with no link that an owner did not approve | With phase 5 |

The efforts are estimates for one developer who knows the code.

## Order

```
  1 lock file + CI ──► 2 template parts ──► 3 one graph writer ──► 4 + 5 security ──► 6 graph checks
                                                                                         │
            7 test questions ──► 8 re-ranker and model ──► 9 code split ──► 10 tracing ◄──┘
                                                   later: 11 Entra ID, 12 size moves, 13 link suggestions
```

## Sources

- pgvector filtered search: https://docs.pgedge.com/pgvector/v0-8-0/iterative-index-scans/
- Re-ranking after hybrid search: https://wz-it.com/en/knowledge/ki/hybrid-search-reranking/
- python-jose and PyJWT: https://github.com/tiangolo/fastapi/pull/9587
- On-behalf-of tokens for MCP servers: https://zuplo.com/learn/mcp/authentication/azure-managed-identity
- OpenTelemetry conventions for AI: https://greptime.com/blogs/2026-05-09-opentelemetry-genai-semantic-conventions
