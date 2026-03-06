"
# Blast Radius Predictor System

## Overview

The Blast Radius Predictor analyzes GitHub Pull Requests and predicts the potential impact (blast radius) of a change before it is merged.

The system evaluates risk using multiple signals:

- repository dependency structure
- runtime traffic patterns
- historical PR outcomes
- observability metrics
- semantic similarity with past changes

The system generates a **risk score and explanation** and posts it as a comment on the Pull Request.

---

# Architecture

![Architecture](./blast-radius-architecture.png)

---

# Core Idea

Traditional blast radius tools rely only on **static dependency graphs**.

This system improves prediction accuracy by constructing a **Weighted Dependency Graph** that incorporates runtime telemetry.

This allows the system to distinguish between:

- dependencies that exist but are rarely used
- dependencies that handle critical production traffic

Example:

Module A -> Module B (called 1M/day)  
Module B -> Module C (called 5/day)

A change to Module C should produce a smaller blast radius than a change to Module B.

Edge weights allow the system to model this difference.

---

# Weighted Dependency Graph

Each repository maintains a **Base Dependency Graph** enriched with runtime telemetry.

## Node

Represents:

- service
- module
- package
- file

## Node Weight

Represents component criticality.

Example factors:

node_weight =
request_volume +
error_rate +
latency_sensitivity +
production_criticality

## Edge Weight

Represents runtime interaction strength.

edge_weight =
call_frequency +
traffic_between_services +
historical_failure_propagation

Edge weights are derived from:

- distributed tracing
- observability metrics
- runtime logs

---

# System Flow

## 1. Data Ingestion

Repository context and telemetry are ingested continuously.

Sources:

- Observability Metrics
- GitHub Commit History
- Repository Codebase
- Historical PR Data
- Runtime Traces

These sources enter the system through the **Kafka Gateway**.

Sources -> Kafka Gateway -> Ingestion Pipeline

Consumers process these streams and populate the repository datastore.

---

## 2. Repository Context Store

A central datastore stores repository intelligence.

Contains:

- Base Dependency Graph
- Weighted Runtime Graph
- Commit History
- Codebase Context
- PR Telemetry Data
- Historical Production Incidents
- Observability Metrics

Possible storage technologies:

- GraphDB for dependency graph
- ClickHouse for metrics
- S3 for code snapshots
- Vector database for PR similarity

---

## 3. Base Dependency Graph Service

Builds the **static dependency graph** from repository code.

Sources:

- import graphs
- package dependencies
- service relationships

This graph represents structural relationships between components.

---

## 4. Runtime Weighting Layer

Runtime telemetry enriches the dependency graph.

Telemetry sources may include:

- distributed tracing
- service call metrics
- endpoint traffic
- error propagation signals

This produces the **Weighted Dependency Graph**, which reflects real production usage.

---

## 5. PR Event Flow

When a PR is opened or updated:

Developer -> GitHub PR  
GitHub -> Webhook  
Webhook -> API Gateway

The system then begins analysis.

---

## 6. Diff Fetching Service

Fetches and analyzes the PR diff.

Responsibilities:

- detect changed files
- detect impacted modules
- build change metadata

---

## 7. Delta Dependency Graph

Using the base weighted graph, the system computes a **Delta Dependency Graph**.

This graph represents:

affected_nodes = downstream_dependencies(changed_nodes)

Propagation is weighted by runtime traffic.

High-traffic edges propagate more influence than low-traffic edges.

---

## 8. Context Retrieval

The system retrieves supporting information:

- similar historical PRs
- past production failures
- module criticality metrics
- dependency depth

This information is retrieved from the datastore and vector index.

---

## 9. Prediction Generation Service

The Prediction Service aggregates all signals.

Inputs:

- change size
- dependency graph depth
- runtime traffic weights
- historical failure rates
- semantic similarity to past PRs

Example conceptual formula:

risk_score =
change_size *
dependency_depth *
traffic_weight *
historical_failure_probability

---

## 10. Prompt Generation Service

**Service:** `prompt-generation-service` (port 8005)

The Prompt Generation Service consumes prediction results from the `prediction-results` Kafka topic and constructs structured LLM prompts.

Responsibilities:

- Filter degraded predictions (skip LLM for incomplete signals)
- Build a system + user message pair from prediction data
- Publish the prompt payload to the `llm-prompts` Kafka topic

The system message defines the LLM's role as a blast-radius analyst and specifies the expected Markdown output format (Summary, Affected Components table, Historical Context, Recommendations).

The user message contains the structured prediction data: risk score, risk level, affected components, similar PRs, traffic impact, and existing recommendations.

The prompt payload includes PR routing metadata (`event_id`, `repo_full_name`, `pr_number`, `installation_id`, `head_sha`) and the full original prediction in `metadata.original_prediction` so the downstream LLM service can route its response back to the correct PR and fall back to the deterministic score on LLM failure.

Kafka flow:

prediction-results -> prompt-generation-service -> llm-prompts

---

## 11. LLM Service

**Service:** `llm-service` (port 8006)

The LLM Service consumes structured prompts from the `llm-prompts` Kafka topic and calls an external LLM provider API to generate the blast-radius analysis.

Responsibilities:

- Consume prompt payloads from the `llm-prompts` topic
- Call the configured LLM provider (Gemini by default — pluggable for future providers)
- Parse the LLM response into a structured result
- POST the enriched result to the API Gateway `POST /results` endpoint
- On LLM failure (timeout, rate limit), fall back to posting the deterministic prediction from `metadata.original_prediction`

The LLM interprets system signals and generates:

- blast radius explanation
- risk classification
- impacted services summary
- mitigation suggestions

This service is intentionally separated from prompt generation to allow:

- Independent scaling of LLM API calls
- Provider-specific retry and rate-limit handling
- Easy swap between LLM providers without touching prompt logic
- Testing prompt quality without incurring LLM API costs

Retry strategy: 3 attempts with exponential backoff (1s, 2s, 4s). On exhaustion, the deterministic prediction is posted as-is with a note that LLM analysis was unavailable.

Kafka + HTTP flow:

llm-prompts -> llm-service -> HTTP POST -> api-gateway /results

---

## 12. PR Comment Integration

The API Gateway receives prediction results via its `POST /results` endpoint and posts them directly to the Pull Request as a GitHub comment.

The **LLM Service** is the sole publisher to this endpoint. It posts either:

1. An LLM-enriched result with a detailed Markdown explanation and recommendations (happy path)
2. The deterministic prediction score as a fallback when the LLM is unavailable

This single-comment design ensures each PR receives exactly one blast-radius comment.

Example comment:

Blast Radius Score: 0.82 (High)

Affected Components:
- auth-service
- login-gateway
- session-manager

Traffic Impact:
~2.3M requests/hour

Recommendation:
Add additional integration tests for token validation.

---

# Service Summary

| Service | Port | Kafka Input | Kafka Output | HTTP Output |
|---------|------|-------------|-------------|-------------|
| api-gateway | 8000 | — | pr-events | GitHub API |
| diff-fetching-service | 8001 | pr-events | diff-metadata, diff-content | — |
| dependency-graph | 8002 | diff-metadata, telemetry-events | delta-graph | — |
| vectorization-service | 8003 | diff-content | pr-context | — |
| prediction-service | 8004 | delta-graph, pr-context | prediction-results | — |
| prompt-generation-service | 8005 | prediction-results | llm-prompts | — |
| llm-service | 8006 | llm-prompts | — | api-gateway /results |

Kafka Topic Flow:

    pr-events
    ├── diff-fetching-service
    │   ├── diff-metadata ──► dependency-graph ──► delta-graph ─────────┐
    │   └── diff-content  ──► vectorization-service ──► pr-context ─────┤
    │                                                                    │
    └── prediction-service ◄──── (delta-graph + pr-context) ────────────┘
            │
            └──► Kafka: prediction-results
                    └──► prompt-generation-service
                            └──► Kafka: llm-prompts
                                    └──► llm-service
                                            └──► HTTP: api-gateway /results

---

# Non Functional Requirements

- High Availability (~99% uptime)
- Asynchronous Processing
- Secure ingestion pipeline
- Horizontal scalability (~1000 PR/day)
- Observability and tracing
- Eventual consistency

---

# Failure Scenarios

The system must gracefully handle:

Webhook Retry  
GitHub may resend events if responses fail.

Kafka Lag  
Ingestion pipelines must tolerate delayed telemetry.

Missing Dependency Graph  
Fallback to static graph.

LLM Timeout  
Return deterministic risk score without explanation.

Stale Repository Context  
Background jobs periodically refresh repo graph and telemetry.

---

# Future Improvements

Potential enhancements:

- CI pipeline integration
- auto-generated test recommendations
- visualization of blast radius graph
- service criticality scoring
- incident correlation with past outages
"