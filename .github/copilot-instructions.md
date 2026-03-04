# AI Agent Instructions

This repository implements a blast radius prediction system for GitHub pull requests.

## Architecture

See:
docs/architecture.md

## Core Concepts

- Base Dependency Graph (repo level)
- Delta Dependency Graph (PR specific)
- PR Context Retrieval
- Prediction Generation

## Rules

- Dependency graph logic must remain deterministic
- Prediction service should remain stateless
- Data ingestion must go through Kafka pipeline
- PR analysis must be asynchronous

## Key Services

api-gateway/
diff-fetching-service/
dependency-graph/
prediction-service/
vectorization-service/
prompt-generation-service/

## Development Guidelines

- Prefer modular microservices
- Avoid tight coupling between prediction and ingestion
- All new services must expose metrics