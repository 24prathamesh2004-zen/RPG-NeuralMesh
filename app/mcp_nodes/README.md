# Subsidiary MCP nodes

Each subsidiary has a separate process, MCP server instance, port, policy file,
and knowledge-pack directory. Start a node from the `app` directory:

```powershell
..\venv\Scripts\python.exe -m mcp_nodes.ceat
..\venv\Scripts\python.exe -m mcp_nodes.kec
..\venv\Scripts\python.exe -m mcp_nodes.zensar
..\venv\Scripts\python.exe -m mcp_nodes.harrisons
```

The configured ports are CEAT `8101`, KEC `8102`, Zensar `8103`, and Harrisons
`8104`. Each process exposes the same tools, `health`, `describe_capabilities`,
`search`, `summarize`, `find_experts`, and `request_access`, using Streamable
HTTP at `/mcp`.

## POC Accounts

The API provides SQLite-backed sign-up and sign-in. A user selects their
subsidiary, and may explicitly opt into an expert profile with role and skills.
The POC API issues a short-lived local JWT; the orchestrator mints a separate
one-hour token for each selected node audience. All local processes use the
same `APP_SECRET_KEY` from `app/.env`. This shared-secret flow is for synthetic
POC data only, not a production identity design.

Copy `app/.env.example` to `app/.env`, set a local `APP_SECRET_KEY` and the
Groq API key, then start the backend from the `app` directory. Accounts are
stored in `app/.neuralmesh/accounts.db`; node grants and audit remain in
separate per-node files. The browser offers sign-up/sign-in at `/auth`. Expert
opt-in is explicit; names are not included in the profile response to other
users.

The current PEP gates capability metadata by caller role and purpose and
enforces datapoint exposure ceilings, never-leave rules, approval flags, and
configured blackout windows. Search is local to the subsidiary's read-only
FTS5 index, returns citations and stale flags, and never returns metadata for
an unauthorized caller. `request_access` persists a caller- and purpose-bound
request. Reviews are performed by the node owner's local CLI, grants expire
within seven days and can be revoked, and RAG searches release gated bodies
only for an exact active grant. `summarize` returns only the authored
`approved_summary`; approval-gated documents return their teaser and decision
without the gated body. `find_experts` returns opted-in role/skill/evidence
records by default. A separate `kind="intro"` request, approved by the node's
CHRO role, reveals the name only to the original requester while that grant is
active. Node state lives under
`app/.neuralmesh/nodes/<node>/`, separately from the generated KB pack.

```powershell
..\venv\Scripts\python.exe -m mcp_nodes.approvals --node kec list
..\venv\Scripts\python.exe -m mcp_nodes.approvals --node kec approve AR-... --approver "PMO head" --hours 24
..\venv\Scripts\python.exe -m mcp_nodes.approvals --node kec revoke GR-... --approver "PMO head"
..\venv\Scripts\python.exe -m mcp_nodes.approvals --node kec verify-audit
```

The hash-chained audit stores caller/node IDs, datapoint, decision, rule and
grant/request IDs only; it excludes query text, content and justification. Keep
nodes on loopback and use only the synthetic pack; do not connect real data or
bind to all interfaces. A node-specific port can be overridden with
`NEURALMESH_CEAT_PORT`, `NEURALMESH_KEC_PORT`, `NEURALMESH_ZENSAR_PORT`, or
`NEURALMESH_HARRISONS_PORT`.

## Central Query API

The API exposes `POST /api/v1/mesh/query`. It accepts a question, selected
subsidiary IDs, a purpose, and optional mode/date. The LangGraph query graph
fans out only to the selected MCP processes, requests a separate Entra
audience token for each node, then returns cited sources, withheld items, and
per-node availability. The Ask screen is connected to this evidence response;
Groq-based agent planning, follow-up tool calls, and grounded answer synthesis
are the next orchestration milestone.

Configure the same `APP_SECRET_KEY` for the API and node processes. The API
accepts only signed POC sessions; the orchestrator mints node-audience tokens
from verified claims instead of forwarding the API token. Calls fail closed
when a node is unavailable. This shortcut is strictly for the synthetic-data
POC; replace it with subsidiary identity federation before any real data use.