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
    pr_context_topic: str = Field(
        default="pr-context", alias="KAFKA_PR_CONTEXT_TOPIC"
    )
    prediction_results_topic: str = Field(
        default="prediction-results", alias="KAFKA_PREDICTION_RESULTS_TOPIC"
    )
    llm_prompts_topic: str = Field(
        default="llm-prompts", alias="KAFKA_LLM_PROMPTS_TOPIC"
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

    provider: str = Field(default="gemini", alias="LLM_PROVIDER")
    api_key: str = Field(default="", alias="LLM_API_KEY")
    model: str = Field(default="gemini-2.0-flash", alias="LLM_MODEL")
    max_retries: int = Field(default=3, ge=0, alias="LLM_MAX_RETRIES")
    retry_base_delay: float = Field(
        default=1.0, ge=0.1, alias="LLM_RETRY_BASE_DELAY"
    )
    api_gateway_results_url: str = Field(
        default="http://api-gateway:8000/results",
        alias="API_GATEWAY_RESULTS_URL",
    )

    model_config = {"env_prefix": "", "extra": "ignore"}


class QdrantSettings(BaseSettings):
    """Qdrant vector database connection settings."""

    host: str = Field(default="localhost", alias="QDRANT_HOST")
    port: int = Field(default=6333, alias="QDRANT_PORT")
    grpc_port: int = Field(default=6334, alias="QDRANT_GRPC_PORT")
    collection_name: str = Field(
        default="pr-embeddings", alias="QDRANT_COLLECTION_NAME"
    )

    model_config = {"env_prefix": "", "extra": "ignore"}


class EmbeddingSettings(BaseSettings):
    """Embedding model settings."""

    backend: str = Field(
        default="sentence-transformer", alias="EMBEDDING_BACKEND"
    )
    model_name: str = Field(
        default="all-MiniLM-L6-v2", alias="EMBEDDING_MODEL_NAME"
    )
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")

    model_config = {"env_prefix": "", "extra": "ignore"}


class PredictionSettings(BaseSettings):
    """Prediction service scoring weights and configuration."""

    depth_weight: float = Field(
        default=0.25, ge=0.0, le=1.0, alias="PREDICTION_DEPTH_WEIGHT"
    )
    traffic_weight: float = Field(
        default=0.25, ge=0.0, le=1.0, alias="PREDICTION_TRAFFIC_WEIGHT"
    )
    history_weight: float = Field(
        default=0.20, ge=0.0, le=1.0, alias="PREDICTION_HISTORY_WEIGHT"
    )
    change_size_weight: float = Field(
        default=0.30, ge=0.0, le=1.0, alias="PREDICTION_CHANGE_SIZE_WEIGHT"
    )
    buffer_ttl_seconds: int = Field(
        default=60, ge=5, alias="PREDICTION_BUFFER_TTL_SECONDS"
    )
    sweep_interval_seconds: int = Field(
        default=10, ge=1, alias="PREDICTION_SWEEP_INTERVAL_SECONDS"
    )

    model_config = {"env_prefix": "", "extra": "ignore"}


class Settings(BaseSettings):
    """Root settings aggregating all sub-configs."""

    kafka: KafkaSettings = KafkaSettings()
    github: GitHubAppSettings = GitHubAppSettings()
    postgres: PostgresSettings = PostgresSettings()
    neo4j: Neo4jSettings = Neo4jSettings()
    llm: LLMSettings = LLMSettings()
    qdrant: QdrantSettings = QdrantSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    prediction: PredictionSettings = PredictionSettings()

    model_config = {"env_prefix": "", "extra": "ignore"}


def get_settings() -> Settings:
    """Create and return a Settings instance."""
    return Settings()
