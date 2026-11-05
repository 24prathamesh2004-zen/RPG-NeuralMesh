.PHONY: help install dev worker migrate revision test lint seed-demo compose-up compose-down packs nodes gateway mesh-stop eval-recall live-check

help:
	@echo "install       Create venv and install requirements"
	@echo "dev           Run FastAPI with reload (port 8000)"
	@echo "worker        Run the Temporal worker"
	@echo "migrate       Apply DB migrations (alembic upgrade head)"
	@echo "revision      Autogenerate a migration (m='message')"
	@echo "test          Run pytest"
	@echo "seed-demo     Seed local synthetic presentation accounts and requests"
	@echo "compose-up    Start full local stack (postgres, redis, temporal, phoenix)"
	@echo "compose-down  Stop local stack"
	@echo "packs         Rebuild the data pack, the 19 knowledge packs and their vector indexes"
	@echo "nodes         Start the four subsidiary MCP nodes in the background (8101 to 8104)"
	@echo "gateway       Run the MCP context gateway for SkillForge (8100)"
	@echo "mesh-stop     Stop the nodes, the gateway and the API"
	@echo "eval-recall   Keyword against hybrid recall on the reworded golden questions"
	@echo "live-check    Check the wiring of the running API, gateway and nodes"

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

dev:
	uvicorn api.main:app --reload --host 127.0.0.1 --port 8000

worker:
	python -m workers.worker

migrate:
	alembic upgrade head

revision:
	alembic revision --autogenerate -m "$(m)"

test:
	pytest -q

seed-demo:
	python -m scripts.seed_demo_accounts

compose-up:
	docker compose up -d --build

compose-down:
	docker compose down

packs:
	cd neuralmesh_kb_pack && python kbgen.py

nodes:
	mkdir -p .neuralmesh/logs
	for n in ceat kec zensar harrisons; do nohup python -m mcp_nodes.$$n > .neuralmesh/logs/$$n.log 2>&1 & done

gateway:
	python -m mcp_gateway.server

mesh-stop:
	-for p in 8000 8100 8101 8102 8103 8104; do lsof -nP -iTCP:$$p -sTCP:LISTEN -t | xargs kill 2>/dev/null; done

eval-recall:
	python -m evaluations.reworded_recall

live-check:
	python -m evaluations.live_wiring_check
