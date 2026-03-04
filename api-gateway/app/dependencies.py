"""Dependency injection / singleton management for the API Gateway.

Provides access to shared resources (Kafka producer, GitHub auth)
across route handlers without passing them as function arguments.
"""

from shared.config import get_settings
from shared.github_auth import GitHubAppAuth
from shared.kafka_producer import KafkaProducerClient

# --- Singletons ---
_kafka_producer: KafkaProducerClient | None = None
_github_auth: GitHubAppAuth | None = None


def get_kafka_producer() -> KafkaProducerClient:
    """Get the singleton Kafka producer instance."""
    global _kafka_producer
    if _kafka_producer is None:
        settings = get_settings()
        _kafka_producer = KafkaProducerClient(settings.kafka)
    return _kafka_producer


def set_kafka_producer(producer: KafkaProducerClient) -> None:
    """Override the Kafka producer (used in testing)."""
    global _kafka_producer
    _kafka_producer = producer


def get_github_auth() -> GitHubAppAuth:
    """Get the singleton GitHub App auth instance."""
    global _github_auth
    if _github_auth is None:
        settings = get_settings()
        _github_auth = GitHubAppAuth(settings.github)
    return _github_auth


def set_github_auth(auth: GitHubAppAuth) -> None:
    """Override the GitHub auth (used in testing)."""
    global _github_auth
    _github_auth = auth
