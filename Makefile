# Source of truth for dev tasks. mise.toml tasks are thin aliases to these targets.
COMPOSE_FILE := infra/docker-compose.yml
COMPOSE := docker compose -f $(COMPOSE_FILE) $(if $(wildcard .env),--env-file .env)

.DEFAULT_GOAL := help

.PHONY: help install up down logs test test-backend test-frontend lint fmt openapi gen-client

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install backend and frontend dependencies
	cd backend && uv sync
	cd frontend && pnpm install

up: ## Start the stack with Docker Compose
	$(COMPOSE) up -d --build

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

fmt: ## Format backend and frontend code
	cd backend && uv run ruff check --fix
	cd backend && uv run ruff format
	cd frontend && pnpm fmt

openapi: ## Export the OpenAPI schema
	# TODO: the contract bead creates telescope.export_openapi
	cd backend && uv run python -m telescope.export_openapi

gen-client: ## Generate the typed frontend API client
	# TODO: the contract bead fills this in
	@echo "gen-client: not implemented yet"
