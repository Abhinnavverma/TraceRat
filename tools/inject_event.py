"""Inject a simulated PR event into the Kafka pr-events topic.

Bypasses the GitHub webhook + GitHub App entirely — lets you test the
full downstream pipeline (diff → graph → vector → predict → prompt →
LLM → result) using any *public* PR on GitHub.

The diff-fetching-service will still call the GitHub API to fetch the
actual PR files, but it works with public repos without auth.

Usage::

    # Inject a real public PR (diff-fetching will fetch its files)
    python tools/inject_event.py --repo tiangolo/fastapi --pr 12345

    # Use a custom installation ID (default: 0 — triggers public API path)
    python tools/inject_event.py --repo pallets/flask --pr 5678 --installation-id 0
"""

from __future__ import annotations

import argparse
import json
import time
import uuid

from kafka import KafkaProducer

# ---------------------------------------------------------------------------
# Event builder — matches the schema api-gateway publishes to pr-events
# ---------------------------------------------------------------------------


def build_pr_event(
    repo: str,
    pr_number: int,
    installation_id: int = 0,
    head_sha: str = "",
    action: str = "opened",
) -> dict:
    """Build a PREvent payload matching the api-gateway schema.

    Parameters
    ----------
    repo:
        Full repository name (e.g. ``tiangolo/fastapi``).
    pr_number:
        Pull request number.
    installation_id:
        GitHub App installation ID. Use 0 for public API (no auth).
    head_sha:
        Head commit SHA. Auto-generated if not provided.
    action:
        PR action (opened/synchronize/reopened).
    """
    event_id = f"inject-{uuid.uuid4().hex[:12]}"

    if not head_sha:
        head_sha = uuid.uuid4().hex[:40]

    owner, name = repo.split("/", 1)

    return {
        "event_id": event_id,
        "action": action,
        "repo_full_name": repo,
        "repo_owner": owner,
        "repo_name": name,
        "pr_number": pr_number,
        "head_sha": head_sha,
        "base_branch": "main",
        "head_branch": f"simulated-pr-{pr_number}",
        "installation_id": installation_id,
        "sender": "tracerat-injector",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Inject a simulated PR event into the Kafka pr-events topic."
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repo in owner/name format",
    )
    parser.add_argument(
        "--pr",
        required=True,
        type=int,
        help="PR number (must exist on the repo for diff-fetching to work)",
    )
    parser.add_argument(
        "--kafka-bootstrap",
        default="localhost:9092",
        help="Kafka bootstrap servers (default: localhost:9092)",
    )
    parser.add_argument(
        "--topic",
        default="pr-events",
        help="Kafka topic to publish to (default: pr-events)",
    )
    parser.add_argument(
        "--installation-id",
        type=int,
        default=0,
        help="GitHub App installation ID (default: 0 for public repos)",
    )
    parser.add_argument(
        "--head-sha",
        default="",
        help="Head commit SHA (auto-generated if not provided)",
    )
    args = parser.parse_args()

    event = build_pr_event(
        repo=args.repo,
        pr_number=args.pr,
        installation_id=args.installation_id,
        head_sha=args.head_sha,
    )

    print(f"Publishing PR event to Kafka topic '{args.topic}' …")
    print(f"  repo:    {args.repo}")
    print(f"  PR:      #{args.pr}")
    print(f"  event_id: {event['event_id']}")

    producer = KafkaProducer(
        bootstrap_servers=args.kafka_bootstrap,
        value_serializer=lambda v: json.dumps(v).encode("utf-8"),
        key_serializer=lambda k: k.encode("utf-8") if k else None,
    )

    key = event["event_id"]
    future = producer.send(args.topic, key=key, value=event)
    record = future.get(timeout=10)

    print(f"  ✓ Published to partition {record.partition}, offset {record.offset}")
    print()
    print("Watch the pipeline:")
    print(f"  Kafka UI:     http://localhost:8080")
    print(f"  Grafana:      http://localhost:3000")
    print(f"  API Gateway:  http://localhost:8000/health")

    producer.close()


if __name__ == "__main__":
    main()
