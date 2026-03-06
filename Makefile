.PHONY: build up down restart logs test lint format clean \
       test-all seed-graph seed-prs seed-all demo-up demo-trigger

SERVICES = api-gateway diff-fetching-service dependency-graph \
           vectorization-service prediction-service \
           prompt-generation-service llm-service

SEED_REPO ?= tiangolo/fastapi
SEED_PR_COUNT ?= 30

# --------------------------------------------------------
# Docker
# --------------------------------------------------------

build:
	docker compose build

up:
	docker compose up -d

up-build:
	docker compose up -d --build

down:
	docker compose down

down-clean:
	docker compose down -v

restart:
	docker compose restart

logs:
	docker compose logs -f

logs-%:
	docker compose logs -f $*

# --------------------------------------------------------
# Testing
# --------------------------------------------------------

test-%:
	cd $* && python -m pytest tests/ -v

test-all:
	@for svc in $(SERVICES); do \
		echo "\n========== $$svc =========="; \
		cd $$svc && python -m pytest tests/ -v && cd ..; \
	done

test: test-all

# --------------------------------------------------------
# Linting / Formatting
# --------------------------------------------------------

lint:
	@for svc in $(SERVICES); do \
		echo "\n========== $$svc =========="; \
		cd $$svc && python -m ruff check . && cd ..; \
	done

format:
	@for svc in $(SERVICES); do \
		cd $$svc && python -m ruff format . && cd ..; \
	done

# --------------------------------------------------------
# Seeding  (run AFTER `make up`)
# --------------------------------------------------------

seed-graph:
	python tools/seed_repo.py --repo $(SEED_REPO)

seed-prs:
	python tools/seed_prs.py --repo $(SEED_REPO) --count $(SEED_PR_COUNT)

seed-all: seed-graph seed-prs

# --------------------------------------------------------
# Demo workflow
# --------------------------------------------------------

demo-up: up
	@echo "Waiting for infrastructure to be healthy..."
	@sleep 20
	$(MAKE) seed-all
	@echo "\nInfrastructure ready.  Open:"
	@echo "  Kafka UI   → http://localhost:8080"
	@echo "  Neo4j      → http://localhost:7474"
	@echo "  Grafana    → http://localhost:3000  (admin / tracerat)"
	@echo "  Prometheus → http://localhost:9090"

demo-trigger:
	python tools/inject_event.py --repo $(SEED_REPO) --pr 1

# --------------------------------------------------------
# Cleanup
# --------------------------------------------------------

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	find . -type d -name .pytest_cache -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
