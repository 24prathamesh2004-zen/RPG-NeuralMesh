# Accelerator Bootstrapper Template

A cloneable, production-shaped skeleton for **agentic apps on the ZenLabs Agent
Foundry** — the same standard structure behind `digital-onboarding`, `zenarc`,
`merchant-onboard`, `capmarkets`, and friends. Clone it, run one command, and
you have a running FastAPI + LangGraph + Temporal + React app ready to deploy to
Azure Container Apps.

> This repo holds the **template** (with `__PLACEHOLDER__` tokens). You don't run
> the template directly — you `bootstrap` it into a new app repo.

---

## The stack

| Layer | Tech |
|---|---|
| API | FastAPI (async), environment-scoped CORS, `/health` probe |
| Agents | LangGraph **supervisor loop** — specialists route back to a supervisor |
| Durability | Temporal workflows + activities, dedicated worker process |
| State / cache | Redis (session store) |
| Database | Postgres via SQLAlchemy async + Alembic migrations |
| LLM | Azure OpenAI via `langchain-openai` |
| Observability | OpenTelemetry → Arize Phoenix (LangChain + OpenAI instrumented) |
| Secrets | Azure Key Vault (resolved at startup from `*_KV_URI` settings) |
| UI | React + Vite + Tailwind (ZenLabs design system) behind nginx |
| Deploy | Azure Container Apps — `infra/aca-setup.sh` + Azure Pipelines |

---

## Quick start — create a new app

```bash
# 1. Clone the template
git clone https://dev.azure.com/Zenlabs-Agent-Foundry/Zenlabs-Agent-Foundry/_git/accelerator-bootstrapper-template
cd accelerator-bootstrapper-template

# 2. Bootstrap a new app (creates ../payment-insights)
python bootstrap.py --name payment-insights \
  --title "Payment Insights" \
  --desc "Real-time payment analytics agent" \
  --backend-port 8010 --frontend-port 3010

# 3. Run it
cd ../payment-insights/app
cp .env.example .env                                   # add Azure OpenAI creds
docker compose -f ../docker-compose.local.yml up -d    # postgres + redis
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
alembic upgrade head
uvicorn api.main:app --reload --port 8010              # API
python -m workers.worker                               # worker (separate shell)
cd ui && npm install && npm run dev                    # UI
```

The generated app has a working **Playground** page that talks to the example
agent graph over `/api/v1/example` — proof the whole spine is wired.

### Bootstrap options

| Flag | Default | Purpose |
|---|---|---|
| `--name` | *(required)* | kebab-case app + resource name |
| `--title` | derived | Human title (UI + API) |
| `--desc` | derived | One-line description |
| `--backend-port` | `8000` | FastAPI port |
| `--frontend-port` | `3000` | Vite dev port |
| `--namespace` | `<name>` | Temporal namespace |
| `--task-queue` | `<name>-agents` | Temporal task queue |
| `--db-name` | snake_case name | Postgres DB name |
| `--dest` | `../<name>` | output directory |
| `--git-init` / `--remote <url>` | — | init git (+ set origin) |

Placeholders and defaults are declared in [`template.config.json`](template.config.json).

---

## Deploy to Azure Container Apps

```bash
bash infra/aca-setup.sh     # one-time provisioning (edit the VARIABLES block first)
```

This provisions three apps with the **correct ingress topology** (a hard-won
default — see [BOOTSTRAP_GUIDE.md](BOOTSTRAP_GUIDE.md)):

- `<name>-be` — **internal** ingress **+ `--allow-insecure`** (so the FE nginx can
  proxy over `http://…be.internal…` without a 301 http→https redirect)
- `<name>-worker` — no ingress (Temporal worker)
- `<name>-fe` — external ingress; `BACKEND_URL=http://<name>-be.internal…`

CI/CD: push to `main` and `azure-pipelines-be.yml` / `azure-pipelines-fe.yml`
build to ACR and roll the apps. `azure-pipelines-temporal.yml` is optional (most
apps reuse the shared Temporal server).

---

## What's inside

See [BOOTSTRAP_GUIDE.md](BOOTSTRAP_GUIDE.md) for the full directory map, the
supervisor-loop pattern, and how to add an agent, a router, a workflow, and a UI
page. The short version:

```
app/
  api/        FastAPI app, routers, schemas
  agents/     LangGraph nodes, tools, state, guardrails, human-in-the-loop
  workflows/  Temporal workflows + activities
  workers/    worker entrypoint
  config/     YAML prompts, rules, temporal dynamic-config
  db/         SQLAlchemy models + async engine, alembic/
  observability/  OTel + Phoenix tracing
  security/   Key Vault + auth
  shared/     config, llm, logger, prompt loader
  ui/         React + Vite + Tailwind + nginx
infra/        aca-setup.sh
azure-pipelines-{be,fe,temporal}.yml
```

# RPG-NeuralMesh

# starter_template
