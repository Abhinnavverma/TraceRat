"""Centralized configuration loaded from environment variables."""

from pydantic import Field
from pydantic_settings import BaseSettings


class KafkaSettings(BaseSettings):
    """Kafka connection settings."""

    bootstrap_servers: str = Field(
        default="localhost:9092", alias="KAFKA_BOOTSTRAP_SERVERS"
    )
    pr_events_topic: str = Field(default="pr-events", alias="KAFKA_PR_EVENTS_TOPIC")
    diff_metadata_topic: str = Field(
        default="diff-metadata", alias="KAFKA_DIFF_METADATA_TOPIC"
    )
    diff_content_topic: str = Field(
        default="diff-content", alias="KAFKA_DIFF_CONTENT_TOPIC"
    )
    delta_graph_topic: str = Field(
        default="delta-graph", alias="KAFKA_DELTA_GRAPH_TOPIC"
    )
    telemetry_events_topic: str = Field(
        default="telemetry-events", alias="KAFKA_TELEMETRY_EVENTS_TOPIC"
    )
    consumer_group: str = Field(default="tracerat", alias="KAFKA_CONSUMER_GROUP")

    model_config = {"env_prefix": "", "extra": "ignore"}


class GitHubAppSettings(BaseSettings):
    """GitHub App authentication settings."""

    app_id: str = Field(default="", alias="GITHUB_APP_ID")
    private_key_path: str = Field(default="", alias="GITHUB_APP_PRIVATE_KEY_PATH")
    webhook_secret: str = Field(default="", alias="GITHUB_WEBHOOK_SECRET")

    model_config = {"env_prefix": "", "extra": "ignore"}


class PostgresSettings(BaseSettings):
    """PostgreSQL connection settings."""

    host: str = Field(default="localhost", alias="POSTGRES_HOST")
    port: int = Field(default=5432, alias="POSTGRES_PORT")
    user: str = Field(default="tracerat", alias="POSTGRES_USER")
    password: str = Field(default="tracerat_dev", alias="POSTGRES_PASSWORD")
    db: str = Field(default="tracerat", alias="POSTGRES_DB")

    model_config = {"env_prefix": "", "extra": "ignore"}

    @property
    def dsn(self) -> str:
        return f"postgresql://{self.user}:{self.password}@{self.host}:{self.port}/{self.db}"


class Neo4jSettings(BaseSettings):
    """Neo4j connection settings."""

    uri: str = Field(default="bolt://localhost:7687", alias="NEO4J_URI")
    user: str = Field(default="neo4j", alias="NEO4J_USER")
    password: str = Field(default="tracerat_dev", alias="NEO4J_PASSWORD")

    model_config = {"env_prefix": "", "extra": "ignore"}


class LLMSettings(BaseSettings):
    """LLM provider settings (pluggable)."""

    provider: str = Field(default="openai", alias="LLM_PROVIDER")
    api_key: str = Field(default="", alias="LLM_API_KEY")
    model: str = Field(default="gpt-4", alias="LLM_MODEL")

    model_config = {"env_prefix": "", "extra": "ignore"}


class Settings(BaseSettings):
    """Root settings aggregating all sub-configs."""

    kafka: KafkaSettings = KafkaSettings()
    github: GitHubAppSettings = GitHubAppSettings()
    postgres: PostgresSettings = PostgresSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    llm: LLMSettings = LLMSettings()

    model_config = {"env_prefix": "", "extra": "ignore"}


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
