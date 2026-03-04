.PHONY: help install test test-live test-live-api test-live-mcp test-live-realdata test-all clean run-api run-mcp run-dashboard docker-build docker-up docker-down docker-logs format lint version bump

# Default target
.DEFAULT_GOAL := help

# Variables
PYTHON := python
PIP := pip
PYTEST := pytest
VERSION := $(shell grep '^version' pyproject.toml | head -1 | sed 's/.*"\(.*\)"/\1/')
DOCKER_REGISTRY := jinwoo
DOCKER_IMAGE := $(DOCKER_REGISTRY)/mem-mesh
DOCKER_TAG_VERSION := $(DOCKER_IMAGE):$(VERSION)
DOCKER_TAG_LATEST := $(DOCKER_IMAGE):latest
DOCKER_COMPOSE := docker compose -f docker/docker-compose.yml

help: ## Show this help message
	@echo "mem-mesh - AI Memory Management System"
	@echo ""
	@echo "Available commands:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}'

install: ## Install dependencies
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r requirements.txt
	@echo "✓ Dependencies installed"

install-dev: ## Install development dependencies
	$(PIP) install --upgrade pip setuptools wheel
	$(PIP) install -r requirements.txt
	$(PIP) install pytest pytest-asyncio pytest-cov hypothesis black ruff
	@echo "✓ Development dependencies installed"

test: ## Run unit tests (no server needed)
	$(PYTEST) tests/ --ignore=tests/integration -v

test-live: ## Run live integration tests (requires localhost:8000)
	$(PYTEST) tests/integration/ -v

test-live-api: ## Live tests — REST API only
	$(PYTEST) tests/integration/test_api_live.py -v

test-live-mcp: ## Live tests — MCP SSE only
	$(PYTEST) tests/integration/test_mcp_sse_live.py -v

test-live-realdata: ## Live tests — real data scenarios only
	$(PYTEST) tests/integration/test_realdata_scenarios.py -v

test-all: ## Run all tests (unit + live)
	$(PYTEST) tests/ -v

test-cov: ## Run tests with coverage
	$(PYTEST) tests/ -v --cov=app --cov-report=html --cov-report=term
	@echo "✓ Coverage report generated in htmlcov/"

test-watch: ## Run tests in watch mode
	$(PYTEST) tests/ -v --looponfail
	@echo "✓ Test watch mode"

run-api: ## Run FastAPI web server (development)
	$(PYTHON) -m app.web --reload
	@echo "✓ Web server running at http://localhost:8000"

run-mcp: ## Run MCP stdio server
	$(PYTHON) -m app.mcp_stdio
	@echo "✓ MCP stdio server running"

run-mcp-pure: ## Run pure MCP stdio server
	$(PYTHON) -m app.mcp_stdio_pure
	@echo "✓ Pure MCP stdio server running"

run-dashboard: ## Run dashboard (alias for run-api)
	$(MAKE) run-api

format: ## Format code with Black
	black app/ tests/ scripts/
	@echo "✓ Code formatted"

lint: ## Lint code with Ruff
	ruff check app/ tests/ scripts/
	@echo "✓ Code linted"

lint-fix: ## Lint and fix code with Ruff
	ruff check --fix app/ tests/ scripts/
	@echo "✓ Code linted and fixed"

clean: ## Clean up generated files
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".pytest_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name ".ruff_cache" -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name "htmlcov" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type f -name ".coverage" -delete 2>/dev/null || true
	@echo "✓ Cleaned up generated files"

docker-build: ## Build Docker image (tagged version + latest)
	docker build -t $(DOCKER_TAG_VERSION) -t $(DOCKER_TAG_LATEST) .
	@echo "✓ Built $(DOCKER_TAG_VERSION) and $(DOCKER_TAG_LATEST)"

docker-build-compose: ## Build Docker images via compose
	$(DOCKER_COMPOSE) build
	@echo "✓ Docker compose images built"

docker-build-mcp: ## Build MCP server Docker image
	$(DOCKER_COMPOSE) build mcp-server
	@echo "✓ MCP server image built"

docker-build-dashboard: ## Build dashboard Docker image
	$(DOCKER_COMPOSE) build dashboard
	@echo "✓ Dashboard image built"

docker-push: ## Push Docker image to registry
	docker push $(DOCKER_TAG_VERSION)
	docker push $(DOCKER_TAG_LATEST)
	@echo "✓ Pushed $(DOCKER_TAG_VERSION) and $(DOCKER_TAG_LATEST)"

docker-up: ## Start Docker containers (dashboard only)
	$(DOCKER_COMPOSE) up -d dashboard
	@echo "✓ Dashboard container started at http://localhost:8000"

docker-up-all: ## Start all Docker containers (including MCP)
	$(DOCKER_COMPOSE) --profile mcp up -d
	@echo "✓ All containers started"

docker-down: ## Stop Docker containers
	$(DOCKER_COMPOSE) down
	@echo "✓ Docker containers stopped"

docker-logs: ## Show Docker logs
	$(DOCKER_COMPOSE) logs -f

docker-logs-dashboard: ## Show dashboard logs
	$(DOCKER_COMPOSE) logs -f dashboard

docker-logs-mcp: ## Show MCP server logs
	$(DOCKER_COMPOSE) logs -f mcp-server

docker-restart: ## Restart Docker containers
	$(DOCKER_COMPOSE) restart
	@echo "✓ Docker containers restarted"

docker-clean: ## Remove Docker containers and volumes
	$(DOCKER_COMPOSE) down -v
	@echo "✓ Docker containers and volumes removed"

migrate: ## Run database migrations
	$(PYTHON) scripts/migrate_embeddings.py
	@echo "✓ Database migrations completed"

migrate-check: ## Check database migrations (dry-run)
	$(PYTHON) scripts/migrate_embeddings.py --check-only
	@echo "✓ Migration check completed"

db-backup: ## Backup database
	@mkdir -p backups
	@cp data/memories.db backups/memories-$$(date +%Y%m%d-%H%M%S).db
	@echo "✓ Database backed up to backups/"

db-restore: ## Restore database from latest backup
	@cp $$(ls -t backups/*.db | head -1) data/memories.db
	@echo "✓ Database restored from latest backup"

health-check: ## Check service health
	@curl -f http://localhost:8000/health || echo "✗ Service is not healthy"
	@echo "✓ Health check completed"

dev: ## Start development environment
	$(MAKE) install-dev
	$(MAKE) run-api

prod: ## Start production environment with Docker
	$(MAKE) docker-build
	$(MAKE) docker-up
	@echo "✓ Production environment started"
	@echo "  Dashboard: http://localhost:8000"
	@echo "  API Docs: http://localhost:8000/docs"

quickstart: ## Docker quick start (build + up)
	$(MAKE) prod

stop: ## Stop all services
	$(MAKE) docker-down
	@echo "✓ All services stopped"

version: ## Show current version
	@echo $(VERSION)

bump: ## Bump version (usage: make bump V=1.1.0)
ifndef V
	$(error Usage: make bump V=x.y.z)
endif
	@sed -i '' 's/^version = ".*"/version = "$(V)"/' pyproject.toml
	@echo "✓ Bumped version to $(V)"
	@echo "  pyproject.toml updated (single source of truth)"
	@echo "  app/core/version.py reads from pyproject.toml at runtime"
