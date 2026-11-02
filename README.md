# RPG NeuralMesh

RPG NeuralMesh is a synthetic-data proof of concept for cross-subsidiary knowledge discovery. Each pilot company runs a separate MCP server over its own local knowledge pack. A central FastAPI/LangGraph service fans a question out to the selected nodes, which apply their own exposure policies and return cited evidence. No source records are migrated to a group data lake.

> **POC only:** all included knowledge and demo accounts are synthetic. Local accounts use a development identity flow; do not connect real corporate data or expose the development services publicly.

## Current capabilities

- Four independent subsidiary MCP servers: CEAT (`8101`), KEC (`8102`), Zensar (`8103`), and Harrisons Malayalam (`8104`).
- Node-local FTS5 search, approved summaries, health/capability discovery, consent-filtered expert search, and access requests.
- Node-side exposure policy, metadata-only restrictions, configured UPSI blackout handling, time-limited grants, and content-free hash-chained audit logs.
- A central LangGraph fan-out endpoint at `POST /api/v1/mesh/query` that calls the selected MCP nodes and returns cited evidence, withheld decisions, and per-node status.
- SQLite-backed signup/sign-in, subsidiary membership, and optional consented expert profiles.
- React UI pages for Dashboard, Ask NeuralMesh, Expert Finder, Mesh Nodes, Governance, and Admin. Governance reviews are simulated for local demo accounts only.
- A synthetic KB pack and golden scenarios under `app/neuralmesh_kb_pack/`.

**Current orchestration limit:** LangGraph currently performs parallel MCP evidence fan-out. Iterative agent planning and Groq-backed answer synthesis are not implemented yet; the Ask page presents evidence and citations rather than claiming a synthesized answer.

## Prerequisites

- Python 3.11+
- Node.js 20+
- The workspace venv at `../venv` or another environment with `app/requirements.txt` installed

## Start locally on Windows

Run each service in its own PowerShell terminal.

1. Start the API from the repository root:

```powershell
Push-Location app
..\venv\Scripts\python.exe -m uvicorn api.main:app --reload --host 127.0.0.1 --port 8000
```

2. Start the subsidiary MCP servers from `app`, one process per node:

```powershell
..\venv\Scripts\python.exe -m mcp_nodes.ceat
..\venv\Scripts\python.exe -m mcp_nodes.kec
..\venv\Scripts\python.exe -m mcp_nodes.zensar
..\venv\Scripts\python.exe -m mcp_nodes.harrisons
```

3. Start the UI:

```powershell
Push-Location app/ui
npm install
npm run dev
```

Open the Vite URL, normally `http://localhost:5173`.

## Seed presentation data

From the repository root:

```powershell
Push-Location app
..\venv\Scripts\python.exe -m scripts.seed_demo_accounts
```

The development-only seed creates five `@neuralmesh.local` accounts, four opted-in synthetic experts, one pending KEC content request, and one pending CEAT expert-introduction request. It is idempotent and only updates accounts in the reserved demo domain. The shared demo password and account list are documented in [app/scripts/DEMO_ACCOUNTS.md](app/scripts/DEMO_ACCOUNTS.md).

The flagship Ask example is the CEAT-to-Harrisons latex-spoilage question. The included seed data contains approved materials-handling summaries, aggregate spoilage trends, source citations, restricted-data canaries, and policy scenarios.

## Configuration and local state

- API accounts: `app/.neuralmesh/accounts.db`
- Node grants/audits: `app/.neuralmesh/nodes/<node>/`
- Generated synthetic node indexes and structured mock databases: `app/neuralmesh_kb_pack/data_pack/`
- Optional Groq setting: `NEURALMESH_GROQ_API_KEY` in a local `app/.env`; never place the key in the browser or commit it.
- Local runtime databases, `.env` files, virtual environments, `node_modules`, and build output are excluded by `.gitignore`.

## Tests

From the repository root:

```powershell
.\venv\Scripts\python.exe -c "import sys,pytest; sys.path.insert(0,'app'); raise SystemExit(pytest.main(['app/tests','-q']))"
```

Build the frontend from the repository root:

```powershell
npm.cmd --prefix app/ui run build
```

## Planning artifacts

- [Design plan](planning_docs/RPG_NeuralMesh_Design_Plan_v3_2.md)
- [Subsidiary MCP server plan](planning_docs/RPG_NeuralMesh_MCP_Servers_Plan.md)
- [Target wireframe](planning_docs/RPG_NeuralMesh_Wireframe_v4.html)
