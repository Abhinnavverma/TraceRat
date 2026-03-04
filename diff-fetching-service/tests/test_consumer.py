"""Tests for the Kafka consumer (end-to-end message processing)."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.consumer import DiffConsumer

from shared.config import KafkaSettings
from shared.kafka_producer import KafkaProducerClient
from tests.conftest import SAMPLE_PR_EVENT, make_changed_file


@pytest.fixture
def mock_producer():
    """Create a mock Kafka producer."""
    producer = MagicMock(spec=KafkaProducerClient)
    producer.send = AsyncMock()
    producer.start = AsyncMock()
    producer.stop = AsyncMock()
    producer.is_connected = True
    return producer


@pytest.fixture
def sample_changed_files():
    """Create sample changed files for testing."""
    return [
        make_changed_file("src/services/auth/handler.py", additions=20, deletions=5),
        make_changed_file("src/services/auth/models.py", additions=10, deletions=3),
        make_changed_file("tests/test_auth.py", status="added", additions=50, deletions=0),
        make_changed_file("docs/api.md", additions=5, deletions=2),
        make_changed_file("docker-compose.yml", additions=3, deletions=1),
    ]


class TestDiffConsumerProcessing:
    """Test end-to-end message processing."""

    @pytest.mark.asyncio
    async def test_handle_message_publishes_to_both_topics(
        self, mock_producer, sample_changed_files
    ):
        """Processing a PR event publishes to both diff-metadata and diff-content topics."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(return_value=sample_changed_files)

        kafka_settings = KafkaSettings(
            KAFKA_BOOTSTRAP_SERVERS="localhost:9092",
            KAFKA_PR_EVENTS_TOPIC="pr-events",
            KAFKA_DIFF_METADATA_TOPIC="diff-metadata",
            KAFKA_DIFF_CONTENT_TOPIC="diff-content",
        )

        consumer = DiffConsumer(
            kafka_settings=kafka_settings,
            diff_fetcher=mock_fetcher,
            producer=mock_producer,
        )

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        # Should have called send twice: once for metadata, once for content
        assert mock_producer.send.call_count == 2

        # Extract calls
        calls = mock_producer.send.call_args_list

        # First call = diff-metadata
        metadata_call = calls[0]
        assert metadata_call.kwargs["topic"] == "diff-metadata"
        metadata_value = metadata_call.kwargs["value"]
        assert metadata_value["event_id"] == "evt-001"
        assert metadata_value["repo_full_name"] == "octocat/hello-world"
        assert metadata_value["pr_number"] == 42
        assert metadata_value["total_files_changed"] == 5
        assert len(metadata_value["affected_modules"]) > 0

        # Second call = diff-content
        content_call = calls[1]
        assert content_call.kwargs["topic"] == "diff-content"
        content_value = content_call.kwargs["value"]
        assert content_value["event_id"] == "evt-001"
        assert len(content_value["files"]) == 5

    @pytest.mark.asyncio
    async def test_handle_message_correct_file_type_breakdown(
        self, mock_producer, sample_changed_files
    ):
        """File type breakdown is computed correctly."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(return_value=sample_changed_files)

        kafka_settings = KafkaSettings(
            KAFKA_BOOTSTRAP_SERVERS="localhost:9092",
            KAFKA_PR_EVENTS_TOPIC="pr-events",
            KAFKA_DIFF_METADATA_TOPIC="diff-metadata",
            KAFKA_DIFF_CONTENT_TOPIC="diff-content",
        )

        consumer = DiffConsumer(
            kafka_settings=kafka_settings,
            diff_fetcher=mock_fetcher,
            producer=mock_producer,
        )

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        metadata_value = mock_producer.send.call_args_list[0].kwargs["value"]
        file_types = {ft["extension"]: ft["count"] for ft in metadata_value["file_types"]}

        assert file_types[".py"] == 3
        assert file_types[".md"] == 1
        assert file_types[".yml"] == 1

    @pytest.mark.asyncio
    async def test_handle_message_correct_additions_deletions(
        self, mock_producer, sample_changed_files
    ):
        """Total additions and deletions are summed correctly."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(return_value=sample_changed_files)

        kafka_settings = KafkaSettings(
            KAFKA_BOOTSTRAP_SERVERS="localhost:9092",
            KAFKA_PR_EVENTS_TOPIC="pr-events",
            KAFKA_DIFF_METADATA_TOPIC="diff-metadata",
            KAFKA_DIFF_CONTENT_TOPIC="diff-content",
        )

        consumer = DiffConsumer(
            kafka_settings=kafka_settings,
            diff_fetcher=mock_fetcher,
            producer=mock_producer,
        )

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        metadata_value = mock_producer.send.call_args_list[0].kwargs["value"]
        # 20 + 10 + 50 + 5 + 3 = 88
        assert metadata_value["total_additions"] == 88
        # 5 + 3 + 0 + 2 + 1 = 11
        assert metadata_value["total_deletions"] == 11

    @pytest.mark.asyncio
    async def test_handle_message_correct_module_mapping(
        self, mock_producer, sample_changed_files
    ):
        """Module mapping groups files by service correctly."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(return_value=sample_changed_files)

        kafka_settings = KafkaSettings(
            KAFKA_BOOTSTRAP_SERVERS="localhost:9092",
            KAFKA_PR_EVENTS_TOPIC="pr-events",
            KAFKA_DIFF_METADATA_TOPIC="diff-metadata",
            KAFKA_DIFF_CONTENT_TOPIC="diff-content",
        )

        consumer = DiffConsumer(
            kafka_settings=kafka_settings,
            diff_fetcher=mock_fetcher,
            producer=mock_producer,
        )

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        metadata_value = mock_producer.send.call_args_list[0].kwargs["value"]
        module_names = {m["module_name"] for m in metadata_value["affected_modules"]}

        # auth from src/services/auth/
        assert "auth" in module_names
        # documentation from docs/
        assert "documentation" in module_names
        # build-config from docker-compose.yml
        assert "build-config" in module_names

    @pytest.mark.asyncio
    async def test_handle_message_invalid_repo_name_skipped(self, mock_producer):
        """Invalid repo_full_name should be skipped gracefully."""
        consumer = DiffConsumer(producer=mock_producer)

        event = {**SAMPLE_PR_EVENT, "repo_full_name": "invalid-no-slash"}

        await consumer.handle_message(
            topic="pr-events",
            key="invalid#42",
            value=event,
        )

        # Should not have published anything
        mock_producer.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_github_api_failure_skipped(self, mock_producer):
        """GitHub API failure should be handled gracefully."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(side_effect=Exception("API error"))

        consumer = DiffConsumer(diff_fetcher=mock_fetcher, producer=mock_producer)

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        # Should not have published anything
        mock_producer.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_no_files_skipped(self, mock_producer):
        """Empty file list from GitHub should be handled."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(return_value=[])

        consumer = DiffConsumer(diff_fetcher=mock_fetcher, producer=mock_producer)

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        # Should not have published anything
        mock_producer.send.assert_not_called()

    @pytest.mark.asyncio
    async def test_handle_message_key_format(
        self, mock_producer, sample_changed_files
    ):
        """Published messages should use repo#pr_number as key."""
        mock_fetcher = MagicMock()
        mock_fetcher.fetch_changed_files = AsyncMock(return_value=sample_changed_files)

        kafka_settings = KafkaSettings(
            KAFKA_BOOTSTRAP_SERVERS="localhost:9092",
            KAFKA_PR_EVENTS_TOPIC="pr-events",
            KAFKA_DIFF_METADATA_TOPIC="diff-metadata",
            KAFKA_DIFF_CONTENT_TOPIC="diff-content",
        )

        consumer = DiffConsumer(
            kafka_settings=kafka_settings,
            diff_fetcher=mock_fetcher,
            producer=mock_producer,
        )

        await consumer.handle_message(
            topic="pr-events",
            key="octocat/hello-world#42",
            value=SAMPLE_PR_EVENT,
        )

        for call in mock_producer.send.call_args_list:
            assert call.kwargs["key"] == "octocat/hello-world#42"
