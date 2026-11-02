.PHONY: help install dev worker migrate revision test lint seed-demo compose-up compose-down

help:
	@echo "install       Create venv and install requirements"
	@echo "dev           Run FastAPI with reload (port __BACKEND_PORT__)"
	@echo "worker        Run the Temporal worker"
	@echo "migrate       Apply DB migrations (alembic upgrade head)"
	@echo "revision      Autogenerate a migration (m='message')"
	@echo "test          Run pytest"
	@echo "seed-demo     Seed local synthetic presentation accounts and requests"
	@echo "compose-up    Start full local stack (postgres, redis, temporal, phoenix)"
	@echo "compose-down  Stop local stack"

install:
	python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

dev:
	uvicorn api.main:app --reload --host 0.0.0.0 --port __BACKEND_PORT__

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
