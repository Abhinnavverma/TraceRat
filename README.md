<div align="center">

# 🐀 TraceRat

**Blast Radius Prediction for GitHub Pull Requests**

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)
[![Kafka](https://img.shields.io/badge/Apache%20Kafka-Streaming-231F20.svg)](https://kafka.apache.org)
[![Neo4j](https://img.shields.io/badge/Neo4j-Graph%20DB-008CC1.svg)](https://neo4j.com)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

TraceRat analyzes GitHub Pull Requests and predicts the **potential blast radius** of a code change before it is merged — combining static dependency analysis, runtime traffic telemetry, historical PR outcomes, and LLM-powered risk explanation.

[Getting Started](#getting-started) •
[Architecture](#architecture) •
[How It Works](#how-it-works) •
[Services](#services) •
[Configuration](#configuration) •
[Contributing](#contributing) •
[License](#license)

</div>

---

## The Problem

Traditional code review tooling treats all dependencies equally. A change to a utility function used by one internal script is flagged the same way as a change to an authentication module handling millions of requests per hour.

Engineers lack visibility into:

- Which downstream services are **actually affected** by a change
- How much **production traffic** flows through the modified code paths
- Whether **historically similar PRs** caused incidents
- The real-world **blast radius** of merging a pull request

## The Solution

TraceRat constructs a **Weighted Dependency Graph** for each repository — a static dependency graph enriched with runtime telemetry (request volume, error rates, latency, call frequency). When a PR is opened, TraceRat computes a **Delta Dependency Graph** that propagates risk scores through weighted edges, retrieves similar historical PRs via vector similarity search, aggregates all signals into a quantitative risk score, and posts an actionable analysis directly on the PR as a GitHub comment.

```
Blast Radius Score: 0.82 (HIGH) 🔴

Affected Components:
  • auth-service (risk: 0.82, depth: 0)
  • login-gateway (risk: 0.61, depth: 1)
  • session-manager (risk: 0.34, depth: 2)

Traffic Impact: ~2.3M requests/hour

Recommendation:
  Add additional integration tests for token validation.
```

---

## Architecture

<div align="center">

![Architecture](docs/blast-radius-architecture.png)

</div>

TraceRat is built as a set of event-driven microservices communicating over Apache Kafka:

```
GitHub Webhook
      │
      ▼
┌──────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│  API Gateway │────▶│ Diff Fetching Service│────▶│ Dependency Graph    │
│  (port 8000) │     │ (port 8001)         │     │ Service (port 8002) │
└──────┬───────┘     └─────────────────────┘     └──────────┬──────────┘
       │                                                     │
       │              ┌─────────────────────┐                │
       │              │ Vectorization       │                │
       │              │ Service (port 8003) │◀───────────────┤
       │              └──────────┬──────────┘                │
       │                         │                           │
       │              ┌──────────▼──────────┐     ┌──────────▼──────────┐
       │              │ Prompt Generation   │◀────│ Prediction Service  │
       │              │ Service (port 8005) │     │ (port 8004)         │
       │              └──────────┬──────────┘     └─────────────────────┘
       │                         │
       │                    LLM Layer
       │                         │
       ◀─────────────────────────┘
       │
   PR Comment
```

### Core Concepts

| Concept | Description |
|---------|-------------|
| **Base Dependency Graph** | Static dependency graph built from repository import graphs, package dependencies, and service relationships. Stored in Neo4j. |
| **Weighted Dependency Graph** | Base graph enriched with runtime telemetry — request volume, error rates, call frequency, latency sensitivity. |
| **Delta Dependency Graph** | PR-specific subgraph computed by traversing weighted edges outward from changed nodes, propagating risk scores with depth-limited BFS. |
| **Blast Radius Score** | Quantitative risk score (0.0–1.0) aggregating change size, dependency depth, traffic weight, and historical failure probability. |

---

## How It Works

1. **PR Event** — A developer opens or updates a pull request. GitHub sends a webhook to the API Gateway.

2. **Diff Fetching** — The diff-fetching-service consumes the PR event from Kafka, fetches structured file-level changes via the GitHub API, maps changed files to modules/services using path-based heuristics, and publishes diff metadata and content to Kafka.

3. **Delta Graph Computation** — The dependency-graph service consumes diff metadata, queries the weighted dependency graph in Neo4j, and computes the delta — a list of affected components with propagated risk scores based on runtime traffic weights.

4. **Vectorization & Context Retrieval** — The vectorization service embeds the PR diff and retrieves semantically similar historical PRs from the vector store, along with past production failures and module criticality metrics.

5. **Prediction** — The prediction service aggregates all signals (change size × dependency depth × traffic weight × historical failure probability) into a deterministic risk score. The service is stateless.

6. **Prompt Generation & LLM Analysis** — A structured prompt is constructed with affected components, traffic impact, dependency propagation paths, and similar incidents. The LLM generates a human-readable explanation, risk classification, and mitigation suggestions.

7. **PR Comment** — The result is posted back to the pull request as a formatted Markdown comment via the API Gateway.

All inter-service communication is **asynchronous via Kafka**. Every service exposes **Prometheus metrics** and **health/readiness endpoints**.

---

## Services

| Service | Port | Kafka Topics | Description |
|---------|------|--------------|-------------|
| [`api-gateway`](api-gateway/) | 8000 | Produces: `pr-events` | Receives GitHub webhooks, verifies signatures, publishes PR events, posts prediction results as PR comments |
| [`diff-fetching-service`](diff-fetching-service/) | 8001 | Consumes: `pr-events` · Produces: `diff-metadata`, `diff-content` | Fetches PR file changes from GitHub API, maps files to modules, publishes structured diff analysis |
| [`dependency-graph`](dependency-graph/) | 8002 | Consumes: `diff-metadata`, `telemetry-events` · Produces: `delta-graph` | Maintains weighted dependency graph in Neo4j, computes delta dependency graphs for PRs |
| [`vectorization-service`](vectorization-service/) | 8003 | — | Generates vector embeddings for PR diffs, supports similarity search for historical PRs |
| [`prediction-service`](prediction-service/) | 8004 | — | Aggregates signals and computes blast radius risk scores (stateless) |
| [`prompt-generation-service`](prompt-generation-service/) | 8005 | — | Constructs structured prompts for LLM analysis |

### Shared Libraries

The [`shared/`](shared/) directory contains common utilities used across all services:

| Module | Purpose |
|--------|---------|
| [`shared/config.py`](shared/config.py) | Centralized Pydantic settings for Kafka, Neo4j, PostgreSQL, GitHub App, and LLM configuration |
| [`shared/kafka_producer.py`](shared/kafka_producer.py) | Async Kafka producer wrapper (aiokafka) |
| [`shared/kafka_consumer.py`](shared/kafka_consumer.py) | Async Kafka consumer base class with metrics and error handling |
| [`shared/github_auth.py`](shared/github_auth.py) | GitHub App authentication — webhook signature verification, JWT generation, installation token management |
| [`shared/metrics.py`](shared/metrics.py) | Prometheus metrics exposure for FastAPI services |
| [`shared/logging.py`](shared/logging.py) | Structured JSON logging via structlog |

---

## Getting Started

### Prerequisites

- **Python 3.12+**
- **Docker** and **Docker Compose** (v2)
- A **GitHub App** with webhook permissions (for production use)

### Quick Start

```bash
# Clone the repository
git clone https://github.com/your-org/TraceRat.git
cd TraceRat

# Copy environment template
cp .env.example .env
# Edit .env with your configuration (see Configuration section)

# Start all infrastructure and services
make up-build

# Verify services are running
curl http://localhost:8000/health   # API Gateway
curl http://localhost:8001/health   # Diff Fetching Service
curl http://localhost:8002/health   # Dependency Graph Service
```

### Infrastructure

Docker Compose starts the following infrastructure:

| Component | Port | Purpose |
|-----------|------|---------|
| Apache Kafka | 9092 | Event streaming between services |
| Zookeeper | 2181 | Kafka coordination |
| Neo4j | 7474 (HTTP), 7687 (Bolt) | Weighted dependency graph storage |
| PostgreSQL | 5432 | Relational metadata storage |
| Kafka UI | 8080 | Kafka topic monitoring (development) |

### Running Tests

```bash
# Run all tests
make test

# Run tests for a specific service
make test-api-gateway
make test-diff-fetching
make test-dependency-graph

# Run with coverage
cd api-gateway && python -m pytest tests/ -v --cov=app

# Lint all services
make lint
```

### Local Development

```bash
# Create a virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # macOS/Linux

# Install all development dependencies
pip install -r api-gateway/requirements.txt
pip install -r api-gateway/requirements-dev.txt

# Start infrastructure only (no application services)
docker-compose up -d kafka zookeeper neo4j postgres

# Run a single service locally
cd api-gateway
uvicorn app.main:app --reload --port 8000
```

---

## Configuration

All configuration is managed via environment variables. See [`.env.example`](.env.example) for the full list.

### GitHub App

| Variable | Description | Required |
|----------|-------------|----------|
| `GITHUB_APP_ID` | Your GitHub App's ID | Yes |
| `GITHUB_PRIVATE_KEY_PATH` | Path to the `.pem` private key file | Yes |
| `GITHUB_WEBHOOK_SECRET` | Webhook secret for signature verification | Yes |

### Kafka

| Variable | Default | Description |
|----------|---------|-------------|
| `KAFKA_BOOTSTRAP_SERVERS` | `localhost:9092` | Kafka broker addresses |
| `KAFKA_PR_EVENTS_TOPIC` | `pr-events` | Topic for PR webhook events |
| `KAFKA_DIFF_METADATA_TOPIC` | `diff-metadata` | Topic for parsed diff structure |
| `KAFKA_DIFF_CONTENT_TOPIC` | `diff-content` | Topic for raw diff/patch content |
| `KAFKA_DELTA_GRAPH_TOPIC` | `delta-graph` | Topic for delta dependency graph results |
| `KAFKA_TELEMETRY_EVENTS_TOPIC` | `telemetry-events` | Topic for runtime telemetry ingestion |

### Neo4j

| Variable | Default | Description |
|----------|---------|-------------|
| `NEO4J_URI` | `bolt://localhost:7687` | Neo4j Bolt connection URI |
| `NEO4J_USER` | `neo4j` | Neo4j username |
| `NEO4J_PASSWORD` | `tracerat` | Neo4j password |

### PostgreSQL

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `tracerat` | Database name |
| `POSTGRES_USER` | `tracerat` | Database user |
| `POSTGRES_PASSWORD` | `tracerat` | Database password |

---

## API Reference

### API Gateway (port 8000)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/webhook` | Receive GitHub webhook events |
| `POST` | `/results` | Receive prediction results (internal) |
| `GET` | `/health` | Health check |
| `GET` | `/ready` | Readiness check (verifies Kafka connectivity) |
| `GET` | `/metrics` | Prometheus metrics |
| `GET` | `/docs` | Interactive API documentation (Swagger UI) |

### Webhook Payload

TraceRat processes the following GitHub webhook events:

| Event | Action | Behavior |
|-------|--------|----------|
| `pull_request` | `opened` | Triggers full blast radius analysis |
| `pull_request` | `synchronize` | Re-analyzes on new commits |
| `pull_request` | `reopened` | Re-analyzes on reopen |

All other events are acknowledged with `200 OK` and ignored.

---

## Observability

Every service exposes:

- **`/health`** — Liveness probe (always returns `200` if the process is running)
- **`/ready`** — Readiness probe (checks downstream dependencies: Kafka, Neo4j)
- **`/metrics`** — Prometheus-compatible metrics endpoint

### Key Metrics

| Metric | Type | Description |
|--------|------|-------------|
| `kafka_messages_produced_total` | Counter | Messages published to Kafka |
| `kafka_messages_consumed_total` | Counter | Messages consumed from Kafka |
| `kafka_consumer_errors_total` | Counter | Consumer processing errors |
| `github_api_calls_total` | Counter | GitHub API requests made |
| `http_request_duration_seconds` | Histogram | HTTP request latency |

---

## Failure Handling

TraceRat is designed to degrade gracefully:

| Scenario | Behavior |
|----------|----------|
| **Webhook retry** | Idempotent processing; duplicate events are safely handled |
| **Kafka lag** | Services tolerate delayed messages; processing continues when caught up |
| **Missing dependency graph** | Falls back to empty affected components; PR still receives a comment |
| **LLM timeout** | Returns deterministic risk score without natural language explanation |
| **Stale telemetry** | Observability fallback pulls fresh data; staleness threshold is configurable |
| **GitHub API rate limit** | Exponential backoff with configurable retry limits |

---

## Project Structure

```
TraceRat/
├── .env.example                    # Environment variable template
├── .gitignore                      # Python/Docker/IDE ignores
├── Makefile                        # Build, test, lint, and deploy commands
├── docker-compose.yml              # Full infrastructure + services
├── pyproject.toml                  # Root Python tooling config
├── LICENSE                         # Apache License 2.0
│
├── docs/
│   └── Architecture.md            # Detailed system architecture
│
├── shared/                         # Common libraries (all services)
│   ├── config.py
│   ├── kafka_producer.py
│   ├── kafka_consumer.py
│   ├── github_auth.py
│   ├── metrics.py
│   └── logging.py
│
├── api-gateway/                    # GitHub webhook ingress + PR comment posting
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── dependencies.py
│   │   ├── routes/
│   │   │   ├── webhook.py
│   │   │   ├── health.py
│   │   │   └── results.py
│   │   └── services/
│   │       └── github_client.py
│   └── tests/
│
├── diff-fetching-service/          # PR diff analysis + module mapping
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── consumer.py
│   │   └── services/
│   │       ├── diff_fetcher.py
│   │       └── module_mapper.py
│   └── tests/
│
├── dependency-graph/               # Weighted graph + delta computation
│   ├── app/
│   │   ├── main.py
│   │   ├── models.py
│   │   ├── consumer.py
│   │   └── services/
│   │       ├── neo4j_client.py
│   │       ├── delta_calculator.py
│   │       ├── telemetry_consumer.py
│   │       └── observability_fallback.py
│   └── tests/
│
├── prediction-service/             # Risk score aggregation (stateless)
├── vectorization-service/          # Embedding + similarity search
├── prompt-generation-service/      # LLM prompt construction
└── secrets/                        # GitHub App PEM key (not committed)
```

## Contributing

Contributions are welcome! Please read the following before submitting a PR:

1. **Follow the architecture** — See [`docs/Architecture.md`](docs/Architecture.md) for the system design. New services must fit the event-driven microservice pattern.

2. **Read the agent instructions** — [`AGENTS.md`](AGENTS.md) and [`.github/copilot-instructions.md`](.github/copilot-instructions.md) contain development rules that must be followed.

3. **Key rules:**
   - Dependency graph logic must remain **deterministic**
   - Prediction service must remain **stateless**
   - Data ingestion must flow through the **Kafka pipeline**
   - PR analysis must be **asynchronous**
   - All services must expose **Prometheus metrics**
   - Prefer **modular microservices** — avoid tight coupling between prediction and ingestion

4. **Testing** — All new code must include unit tests. Run `make test` before submitting.

5. **Linting** — Code must pass `ruff check .` with zero errors.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12 |
| Web Framework | FastAPI + Uvicorn |
| Event Streaming | Apache Kafka (aiokafka) |
| Graph Database | Neo4j 5.x |
| Relational Database | PostgreSQL 16 |
| Containerization | Docker + Docker Compose |
| Metrics | Prometheus + FastAPI Instrumentator |
| Logging | structlog (structured JSON) |
| Auth | GitHub App (JWT + installation tokens) |
| LLM | Pluggable (OpenAI / Claude / Ollama) |
| Linting | Ruff |
| Testing | pytest + pytest-asyncio |

---

## License

This project is licensed under the **Apache License 2.0** — see the [LICENSE](LICENSE) file for details.

---

<div align="center">

**TraceRat** — Know the blast radius before you merge.

</div>
