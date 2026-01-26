.PHONY: help build build-dev up up-dev down logs bash bash-dev test clean prune health benchmark-up benchmark-down benchmark-migrate-postgres benchmark-migrate-qdrant benchmark-run benchmark-full benchmark-clean

# Default target
help:
	@echo "mem-mesh Docker Management"
	@echo ""
	@echo "Available targets:"
	@echo "  build      - Build production Docker image"
	@echo "  build-dev  - Build development Docker image"
	@echo "  up         - Start production container"
	@echo "  up-dev     - Start development container"
	@echo "  down       - Stop and remove containers"
	@echo "  logs       - View container logs"
	@echo "  bash       - Open bash shell in production container"
	@echo "  bash-dev   - Open bash shell in development container"
	@echo "  test       - Run tests in container"
	@echo "  health     - Check container health"
	@echo "  clean      - Remove containers and images"
	@echo "  prune      - Clean up Docker system"
	@echo ""
	@echo "Benchmark targets:"
	@echo "  benchmark-up                - Start PostgreSQL + Qdrant"
	@echo "  benchmark-down              - Stop benchmark environment"
	@echo "  benchmark-migrate-postgres  - Migrate data to PostgreSQL"
	@echo "  benchmark-migrate-qdrant    - Migrate data to Qdrant"
	@echo "  benchmark-run               - Run benchmark comparison"
	@echo "  benchmark-full              - Run full benchmark pipeline"
	@echo "  benchmark-clean             - Clean benchmark data and volumes"

# Build targets
build:
	@echo "Building production image..."
	docker-compose build mem-mesh

build-dev:
	@echo "Building development image..."
	docker-compose build mem-mesh-dev

# Run targets
up:
	@echo "Starting production container..."
	docker-compose up -d mem-mesh
	@echo "Container started. Access at http://localhost:8000"

up-dev:
	@echo "Starting development container..."
	docker-compose up -d mem-mesh-dev
	@echo "Development container started with hot-reload"
	@echo "Access at http://localhost:8000"

# Stop targets
down:
	@echo "Stopping containers..."
	docker-compose down

# Logs
logs:
	docker-compose logs -f

logs-prod:
	docker-compose logs -f mem-mesh

logs-dev:
	docker-compose logs -f mem-mesh-dev

# Shell access
bash:
	@echo "Opening bash shell in production container..."
	docker-compose exec mem-mesh bash

bash-dev:
	@echo "Opening bash shell in development container..."
	docker-compose exec mem-mesh-dev bash

# Interactive shell (if container is not running)
shell:
	@echo "Starting interactive shell in new container..."
	docker-compose run --rm mem-mesh bash

shell-dev:
	@echo "Starting interactive shell in new development container..."
	docker-compose run --rm mem-mesh-dev bash

# Testing
test:
	@echo "Running tests in container..."
	docker-compose run --rm mem-mesh-dev pytest tests/ -v

test-unit:
	@echo "Running unit tests..."
	docker-compose run --rm mem-mesh-dev pytest tests/ -v -m unit

test-integration:
	@echo "Running integration tests..."
	docker-compose run --rm mem-mesh-dev pytest tests/ -v -m integration

# Health check
health:
	@echo "Checking container health..."
	@docker ps --filter name=mem-mesh --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
	@echo ""
	@curl -s http://localhost:8000/health | python -m json.tool || echo "Service not responding"

# Python commands in container
python:
	docker-compose exec mem-mesh-dev python

ipython:
	docker-compose exec mem-mesh-dev ipython

# Database operations
db-migrate:
	@echo "Running database migrations..."
	docker-compose exec mem-mesh-dev python scripts/migrate_embeddings.py

db-check:
	@echo "Checking database consistency..."
	docker-compose exec mem-mesh-dev python scripts/verify_db_consistency.py

# Cleanup targets
clean:
	@echo "Removing containers and images..."
	docker-compose down --rmi all --volumes --remove-orphans

clean-data:
	@echo "WARNING: This will delete all data!"
	@read -p "Are you sure? [y/N] " -n 1 -r; \
	echo; \
	if [[ $$REPLY =~ ^[Yy]$$ ]]; then \
		rm -rf data/*.db data/*.db-shm data/*.db-wal; \
		echo "Data cleaned"; \
	fi

prune:
	@echo "Pruning Docker system..."
	docker system prune -f

# Development helpers
format:
	@echo "Formatting code..."
	docker-compose run --rm mem-mesh-dev black app/ tests/

lint:
	@echo "Linting code..."
	docker-compose run --rm mem-mesh-dev black --check app/ tests/

# Quick start
quickstart: build-dev up-dev logs-dev

# Production deployment
deploy: build up health

# Restart services
restart:
	docker-compose restart

restart-prod:
	docker-compose restart mem-mesh

restart-dev:
	docker-compose restart mem-mesh-dev

# Benchmark targets
benchmark-up:
	@echo "Starting benchmark environment (PostgreSQL + Qdrant)..."
	docker-compose -f docker-compose.benchmark.yml up -d
	@echo "Waiting for services to be ready..."
	@sleep 5
	@echo "PostgreSQL: localhost:5432 (user: memmesh, db: memmesh)"
	@echo "Qdrant: localhost:6333"

benchmark-down:
	@echo "Stopping benchmark environment..."
	docker-compose -f docker-compose.benchmark.yml down

benchmark-logs:
	docker-compose -f docker-compose.benchmark.yml logs -f

benchmark-migrate-postgres:
	@echo "Migrating data to PostgreSQL..."
	python scripts/migrate_to_postgres.py

benchmark-migrate-qdrant:
	@echo "Migrating data to Qdrant..."
	python scripts/migrate_to_qdrant.py

benchmark-run:
	@echo "Running vector database benchmark..."
	python scripts/benchmark_vector_dbs.py

benchmark-full: benchmark-up benchmark-migrate-postgres benchmark-migrate-qdrant benchmark-run
	@echo "Full benchmark completed. Check results in benchmark_results.json"

benchmark-clean:
	@echo "Cleaning benchmark environment..."
	docker-compose -f docker-compose.benchmark.yml down -v
	@echo "Benchmark data cleaned"
