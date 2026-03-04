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

## 10. Prompt Generation

The Prompt Generation Service constructs a structured prompt containing:

- affected components
- traffic impact
- dependency propagation
- similar historical PR incidents

This prompt is passed to the LLM layer.

---

## 11. LLM Analysis Layer

The LLM interprets system signals and generates:

- blast radius explanation
- risk classification
- impacted services summary
- mitigation suggestions

Example output:

Risk: HIGH

Reason:
- Change affects auth token validator
- Module serves 80% of login requests
- Historically similar PR caused auth outage

---

## 12. PR Comment Integration

The result is returned through the API Gateway and posted directly to the Pull Request as a comment.

Example:

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