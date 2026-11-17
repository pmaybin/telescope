# Source of truth for dev tasks. mise.toml tasks are thin aliases to these targets.
COMPOSE_FILE := infra/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) $(if $(wildcard .env),--env-file .env)

.DEFAULT_GOAL := help

.PHONY: help install up dev down logs test test-backend test-frontend lint fmt openapi gen-client

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && pnpm install

up: ## Start the stack with Docker Compose
	$(COMPOSE) up -d --build

dev: ## Start the stack with hot reload (uvicorn --reload + Vite HMR on mounted sources)
	$(COMPOSE) -f infra/docker-compose.dev.yml up -d --build --wait
	@echo "Web (HMR): http://localhost:$${WEB_PORT:-8080}  API: http://localhost:$${API_PORT:-8000}/docs  Grafana: http://localhost:$${GRAFANA_PORT:-3000}"

down: ## Stop the stack
	$(COMPOSE) down

logs: ## Tail stack logs
	$(COMPOSE) logs -f

test: ## Run backend and frontend tests concurrently
	$(MAKE) -j2 --output-sync=target test-backend test-frontend

test-backend: ## Run backend tests
	cd backend && uv run pytest

test-frontend: ## Run frontend tests
	cd frontend && pnpm test

lint: ## Run all linters and type checks
	cd backend && uv run ruff check
	cd backend && uv run ruff format --check
	cd backend && uv run mypy src
	cd frontend && pnpm lint
	cd frontend && pnpm fmt:check
	cd frontend && pnpm typecheck
	cd frontend && pnpm gen:api:check
	python3 scripts/export_prompt_log.py --check

fmt: ## Format backend and frontend code
	cd backend && uv run ruff check --fix
	cd backend && uv run ruff format
	cd frontend && pnpm fmt

openapi: ## Export the OpenAPI contract to openapi.json
	cd backend && uv run python -m telescope.export_openapi

gen-client: openapi ## Regenerate openapi.json and the typed TS client
	cd frontend && pnpm gen:api
