# Contributing to TraceRat

Thank you for your interest in contributing to TraceRat! This document provides guidelines and instructions for contributing to the project.

---

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Setup](#development-setup)
- [Architecture Overview](#architecture-overview)
- [Development Rules](#development-rules)
- [Adding a New Service](#adding-a-new-service)
- [Making Changes](#making-changes)
- [Testing](#testing)
- [Code Style](#code-style)
- [Commit Conventions](#commit-conventions)
- [Pull Request Process](#pull-request-process)
- [Issue Guidelines](#issue-guidelines)
- [License](#license)

---

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](https://www.contributor-covenant.org/version/2/1/code_of_conduct/). By participating, you are expected to uphold this code. Report unacceptable behavior by opening an issue.

---

## Getting Started

1. **Fork** the repository on GitHub
2. **Clone** your fork locally:
   ```bash
   git clone https://github.com/<your-username>/TraceRat.git
   cd TraceRat
   ```
3. **Add the upstream remote**:
   ```bash
   git remote add upstream https://github.com/<org>/TraceRat.git
   ```
4. **Create a feature branch**:
   ```bash
   git checkout -b feat/<short-description>
   ```

---

## Development Setup

### Prerequisites

| Tool | Version | Purpose |
|------|---------|---------|
| Python | 3.12+ | Service runtime |
| Docker & Docker Compose | v2+ | Infrastructure + containers |
| Git | any | Version control |

### Local Environment

```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# Install dev dependencies for a specific service
cd api-gateway
pip install -r requirements.txt
pip install pytest pytest-asyncio ruff

# Return to root
cd ..
```

### Infrastructure

```bash
# Copy environment config
cp .env.example .env
# Fill in LLM_API_KEY at minimum (free Gemini key from https://aistudio.google.com/app/apikey)

# Start all containers
make up-build

# Seed test data (optional — needed for full pipeline testing)
pip install -r tools/requirements.txt
make seed-all SEED_REPO=tiangolo/fastapi
```

### Verify Setup

```bash
# All services should be running
docker compose ps

# Run the full test suite
make test-all

# Lint all services
make lint
```

---

## Architecture Overview

TraceRat is an event-driven microservices system. Before contributing, read [`docs/Architecture.md`](docs/Architecture.md) to understand:

- The Kafka topic chain and how events flow between services
- The weighted dependency graph model in Neo4j
- The four-factor risk scoring algorithm
- The role of each service in the pipeline

```
pr-events → diff-metadata / diff-content → delta-graph → pr-context
         → prediction-results → llm-prompts → POST /results
```

### Services

| Service | Port | Responsibility |
|---------|------|----------------|
| `api-gateway` | 8000 | Webhook ingestion, result storage, PR commenting |
| `diff-fetching-service` | 8001 | GitHub API diff retrieval, file parsing |
| `dependency-graph` | 8002 | Neo4j graph queries, delta BFS computation |
| `vectorization-service` | 8003 | Embedding generation, Qdrant similarity search |
| `prediction-service` | 8004 | Four-factor risk scoring |
| `prompt-generation-service` | 8005 | Structured LLM prompt construction |
| `llm-service` | 8006 | LLM API calls, result posting |

### Shared Code

The `shared/` directory contains code shared across all services:

| Module | Purpose |
|--------|---------|
| `shared/config.py` | Pydantic settings for all service configurations |
| `shared/kafka.py` | Kafka producer/consumer base classes |
| `shared/github_auth.py` | GitHub App JWT + installation token management |
| `shared/logging.py` | Structured logging via `structlog` |
| `shared/metrics.py` | Prometheus metric definitions |
| `shared/models.py` | Shared Pydantic models |

---

## Development Rules

These rules are **non-negotiable**. PRs that violate them will be rejected.

### Architectural Constraints

1. **Dependency graph logic must remain deterministic** — Given the same inputs, the graph service must always produce the same delta graph. No randomness, no external state.

2. **Prediction service must remain stateless** — The scorer computes results from the current signal bundle only. No in-memory caches, no database calls, no side effects.

3. **Data ingestion must flow through the Kafka pipeline** — Services communicate exclusively via Kafka topics. No direct HTTP calls between pipeline services (except the final result POST).

4. **PR analysis must be asynchronous** — The webhook handler returns immediately. All processing happens asynchronously via Kafka consumers.

5. **All services must expose Prometheus metrics** — Every new service must integrate `prometheus-fastapi-instrumentator` and register relevant custom counters/histograms in `shared/metrics.py`.

### Code Conventions

- **Modular microservices** — Prefer creating a new service over adding unrelated functionality to an existing one.
- **No tight coupling** — Services should depend on Kafka message schemas, not on other services' internals.
- **Typed Python** — Use type annotations everywhere. No `Any` unless absolutely necessary.
- **Pydantic models** — All data structures crossing service boundaries must be Pydantic `BaseModel` subclasses.
- **Async I/O** — All I/O-bound operations must be async. Use `httpx.AsyncClient`, `aiokafka`, and async Neo4j/Qdrant drivers.

---

## Adding a New Service

If your contribution requires a new microservice:

1. **Create the service directory**:
   ```
   my-service/
   ├── app/
   │   ├── __init__.py
   │   ├── main.py          # FastAPI app with health/ready/metrics endpoints
   │   ├── consumer.py      # Kafka consumer logic
   │   ├── models.py        # Service-specific Pydantic models
   │   ├── routes/           # HTTP endpoints (if any)
   │   └── services/         # Business logic
   ├── tests/
   │   ├── __init__.py
   │   └── test_*.py
   ├── Dockerfile           # Multi-stage build (builder + runtime)
   └── requirements.txt
   ```

2. **Follow the existing Dockerfile pattern** — Multi-stage build with a non-root `tracerat` user. Copy `shared/` into the image.

3. **Register in `docker-compose.yml`** — Add the service with proper `depends_on`, health checks, environment variables, and network membership.

4. **Add to the Makefile** — Include the service in the `SERVICES` variable so `make test-all` and `make lint` cover it.

5. **Expose metrics** — Integrate `prometheus-fastapi-instrumentator` and add a scrape target in `monitoring/prometheus.yml`.

6. **Document the Kafka topics** — If the service produces or consumes Kafka topics, update `docs/Architecture.md` with the topic schema and data flow.

---

## Making Changes

### Modifying an Existing Service

1. Make your changes in the service's `app/` directory
2. Add or update tests in the service's `tests/` directory
3. If you change a Kafka message schema, update all producing and consuming services
4. If you modify `shared/`, verify that **all** services still pass their tests

### Modifying Shared Code

Changes to `shared/` affect every service. Extra care is required:

```bash
# After modifying shared/, run ALL tests
make test-all
```

### Modifying Infrastructure

Changes to `docker-compose.yml`, `monitoring/`, or `Makefile` should be tested by running a full `docker compose down -v && make demo-up` cycle.

---

## Testing

### Requirements

- Every new feature or bug fix must include tests
- Tests live in the `tests/` directory of each service
- Use `pytest` with `pytest-asyncio` for async tests
- Mock external dependencies (Kafka, Neo4j, Qdrant, GitHub API)

### Running Tests

```bash
# All services
make test-all

# Single service
make test-api-gateway
make test-prediction-service

# With verbose output
cd prediction-service && python -m pytest tests/ -v --tb=short
```

### Test Structure

```python
"""Tests for the risk scorer."""

import pytest
from app.services.scorer import RiskScorer


class TestRiskScorer:
    """Unit tests for RiskScorer."""

    def test_low_risk_classification(self):
        scorer = RiskScorer()
        assert scorer.classify(0.15) == RiskLevel.LOW

    @pytest.mark.asyncio
    async def test_async_operation(self):
        result = await some_async_function()
        assert result is not None
```

### Coverage Expectations

- Core business logic (scorers, graph traversal, embedding) → **high coverage**
- Kafka consumer/producer wiring → **integration-level tests with mocks**
- HTTP routes → **endpoint tests with `httpx.AsyncClient`**

---

## Code Style

### Linting & Formatting

TraceRat uses **Ruff** for linting and formatting:

```bash
# Check for lint errors
make lint

# Auto-format
make format
```

### Ruff Configuration

Defined in `pyproject.toml`:

```toml
[tool.ruff]
target-version = "py312"
line-length = 100

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP"]
```

### Style Guidelines

- **Line length**: 100 characters max
- **Imports**: Sorted by `isort` rules (handled by Ruff `I` rule)
- **Docstrings**: Use Google-style or NumPy-style docstrings for public functions and classes
- **Naming**: `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants

---

## Commit Conventions

Use [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <short description>

[optional body]

[optional footer]
```

### Types

| Type | When to use |
|------|-------------|
| `feat` | New feature or capability |
| `fix` | Bug fix |
| `refactor` | Code restructuring (no behavior change) |
| `test` | Adding or updating tests |
| `docs` | Documentation changes |
| `chore` | Build, CI, dependency updates |
| `perf` | Performance improvement |

### Scopes

Use the service name as scope:

```
feat(prediction-service): add confidence interval to risk scores
fix(diff-fetching-service): handle GitHub API redirect responses
test(dependency-graph): add BFS traversal edge cases
docs(architecture): update Kafka topic flow diagram
chore(docker): upgrade Neo4j to 5.19
```

---

## Pull Request Process

### Before Submitting

- [ ] Code compiles and runs without errors
- [ ] All existing tests pass (`make test-all`)
- [ ] New tests added for new functionality
- [ ] Linting passes (`make lint`)
- [ ] Commit messages follow conventional commit format
- [ ] Branch is up to date with `main`

### PR Description Template

```markdown
## What

Brief description of the change.

## Why

Motivation — what problem does this solve?

## How

Technical approach — what was changed and why this approach was chosen.

## Testing

How was this tested? Include relevant commands or screenshots.

## Breaking Changes

List any breaking changes to Kafka schemas, API contracts, or configuration.
```

### Review Process

1. Open a PR against `main`
2. Ensure CI checks pass (tests, linting)
3. At least one maintainer review is required
4. Address review feedback with fixup commits
5. Squash and merge once approved

### What We Look For

- **Correctness** — Does it work? Are edge cases handled?
- **Architecture fit** — Does it follow the event-driven pattern? Is coupling minimal?
- **Test quality** — Are the tests meaningful, not just coverage padding?
- **Code clarity** — Is the code readable without excessive comments?
- **Performance** — Does it introduce unnecessary overhead in the hot path?

---

## Issue Guidelines

### Bug Reports

Include:

1. **Description** — What happened vs. what you expected
2. **Reproduction steps** — Minimal steps to reproduce
3. **Environment** — OS, Python version, Docker version
4. **Logs** — Relevant service logs (`docker compose logs <service> --tail 50`)
5. **Kafka state** — Which topics have messages, which are empty (check Kafka UI)

### Feature Requests

Include:

1. **Problem statement** — What limitation are you hitting?
2. **Proposed solution** — How would you solve it?
3. **Alternatives considered** — What other approaches did you evaluate?
4. **Service impact** — Which services would be affected?

### Good First Issues

Look for issues labeled `good-first-issue`. These are typically:

- Adding tests for uncovered paths
- Improving error messages or logging
- Documentation improvements
- Small refactors with clear scope

---

## License

By contributing to TraceRat, you agree that your contributions will be licensed under the [Apache License 2.0](LICENSE).
