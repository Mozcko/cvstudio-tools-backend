# Common tasks, run inside Docker so everyone uses the same Python and tools.
# Use `make COMPOSE="podman compose" <target>` with Podman.

COMPOSE ?= docker compose
RUN      = $(COMPOSE) run --rm
TEST_DB  = cvstudio_test
TEST_URL = postgresql+asyncpg://postgres:postgres@db:5432/$(TEST_DB)
MIG_DB   = cvstudio_migrations
MIG_URL  = postgresql+asyncpg://postgres:postgres@db:5432/$(MIG_DB)

.DEFAULT_GOAL := help
.PHONY: help up down logs shell lint format test-db test migrations-check check audit migrate migration

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

up: ## Start the API (with reload) and the database
	$(COMPOSE) up --build

down: ## Stop everything
	$(COMPOSE) down

logs: ## Follow the API logs
	$(COMPOSE) logs -f api

shell: ## Open a shell in the API container
	$(RUN) api bash

lint: ## Lint and check formatting (what CI runs)
	$(RUN) api sh -c "ruff check . && ruff format --check ."

format: ## Fix what can be fixed automatically and format the code
	$(RUN) api sh -c "ruff check --fix . && ruff format ."

test-db: ## Create the throwaway test database if it is missing
	@$(COMPOSE) up -d db
	@$(COMPOSE) exec -T db sh -c "until pg_isready -U postgres -q; do sleep 1; done; \
	  psql -U postgres -tAc \"SELECT 1 FROM pg_database WHERE datname='$(TEST_DB)'\" | grep -q 1 \
	  || psql -U postgres -qc 'CREATE DATABASE $(TEST_DB)'"

test: test-db ## Run the tests with coverage (wipes the test database, never the dev one)
	$(RUN) -e DATABASE_URL=$(TEST_URL) api pytest --cov $(ARGS)

migrations-check: ## Build a scratch database from the migrations and compare it with the models
	@$(COMPOSE) up -d db
	@$(COMPOSE) exec -T db sh -c "until pg_isready -U postgres -q; do sleep 1; done; \
	  psql -U postgres -qc 'DROP DATABASE IF EXISTS $(MIG_DB)' -c 'CREATE DATABASE $(MIG_DB)'"
	$(RUN) -e DATABASE_URL=$(MIG_URL) -e CLERK_ISSUER=https://clerk.test.example api sh -c "alembic upgrade head && alembic check && alembic downgrade base && alembic upgrade head"

audit: ## Check runtime dependencies for known vulnerabilities
	$(RUN) api pip-audit -r requirements.txt

check: lint test migrations-check ## Everything CI checks, in one command

migrate: ## Apply migrations to the development database
	$(RUN) api alembic upgrade head

migration: ## Create a migration from model changes: make migration m="add x to y"
	@test -n "$(m)" || (echo 'Usage: make migration m="describe the change"' && exit 1)
	$(RUN) api alembic revision --autogenerate -m "$(m)"
