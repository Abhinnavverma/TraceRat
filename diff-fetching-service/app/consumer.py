"""Kafka consumer for processing PR events.

Consumes from the pr-events topic, fetches file changes from GitHub,
maps files to modules, and publishes results to diff-metadata and
diff-content topics.
"""

from collections import Counter
from pathlib import PurePosixPath
from typing import Any

from app.models import DiffContent, DiffMetadata, FileTypeBreakdown
from app.services.diff_fetcher import DiffFetcher
from app.services.module_mapper import ModuleMapper
from shared.config import KafkaSettings, get_settings
from shared.kafka_consumer import KafkaConsumerBase
from shared.kafka_producer import KafkaProducerClient
from shared.logging import get_logger
from shared.metrics import kafka_messages_consumed, kafka_messages_produced

logger = get_logger("consumer")


class DiffConsumer(KafkaConsumerBase):
    """Consumes PR events and produces diff analysis results.

    For each PR event:
    1. Fetches changed files from GitHub API
    2. Maps files to modules/services
    3. Publishes DiffMetadata to diff-metadata topic
    4. Publishes DiffContent to diff-content topic
    """

    def __init__(
        self,
        kafka_settings: KafkaSettings | None = None,
        diff_fetcher: DiffFetcher | None = None,
        module_mapper: ModuleMapper | None = None,
        producer: KafkaProducerClient | None = None,
    ):
        settings = kafka_settings or get_settings().kafka
        super().__init__(
            topics=[settings.pr_events_topic],
            settings=settings,
            group_id="diff-fetching-service",
        )
        self._kafka_settings = settings
        self._diff_fetcher = diff_fetcher or DiffFetcher()
        self._module_mapper = module_mapper or ModuleMapper()
        self._producer = producer or KafkaProducerClient(settings)

    @property
    def producer(self) -> KafkaProducerClient:
        """Expose producer for lifespan management."""
        return self._producer

    async def start(self) -> None:
        """Start consumer and producer."""
        await self._producer.start()
        await super().start()

    async def stop(self) -> None:
        """Stop consumer and producer."""
        await super().stop()
        await self._producer.stop()

    async def handle_message(
        self, topic: str, key: str | None, value: dict[str, Any]
    ) -> None:
        """Process a single PR event message.

        Args:
            topic: Source Kafka topic.
            key: Message key (repo#pr_number).
            value: Deserialized PREvent payload.
        """
        kafka_messages_consumed.labels(
            topic=topic, consumer_group="diff-fetching-service"
        ).inc()

        event_id = value.get("event_id", "unknown")
        repo_full_name = value.get("repo_full_name", "")
        pr_number = value.get("pr_number", 0)
        installation_id = value.get("installation_id", 0)

        logger.info(
            "Processing PR event",
            event_id=event_id,
            repo=repo_full_name,
            pr_number=pr_number,
        )

        # 1. Parse owner/repo
        try:
            owner, repo = repo_full_name.split("/", 1)
        except ValueError:
            logger.error("Invalid repo_full_name", repo_full_name=repo_full_name)
            return

        # 2. Fetch changed files from GitHub
        try:
            changed_files = await self._diff_fetcher.fetch_changed_files(
                owner=owner,
                repo=repo,
                pr_number=pr_number,
                installation_id=installation_id,
            )
        except Exception:
            logger.exception(
                "Failed to fetch PR files from GitHub",
                repo=repo_full_name,
                pr_number=pr_number,
            )
            return

        if not changed_files:
            logger.warning(
                "No changed files found",
                repo=repo_full_name,
                pr_number=pr_number,
            )
            return

        # 3. Map files to modules
        module_mappings = self._module_mapper.map_files(changed_files)

        # 4. Compute file type breakdown
        ext_counter: Counter = Counter()
        for f in changed_files:
            ext = PurePosixPath(f.filename).suffix or "(no extension)"
            ext_counter[ext] += 1

        file_types = [
            FileTypeBreakdown(extension=ext, count=count)
            for ext, count in ext_counter.most_common()
        ]

        # 5. Build file metadata (without patch content)
        files_metadata = [
            {
                "filename": f.filename,
                "status": f.status.value,
                "additions": f.additions,
                "deletions": f.deletions,
                "changes": f.changes,
                "previous_filename": f.previous_filename,
            }
            for f in changed_files
        ]

        total_additions = sum(f.additions for f in changed_files)
        total_deletions = sum(f.deletions for f in changed_files)

        # 6. Build DiffMetadata
        diff_metadata = DiffMetadata(
            event_id=event_id,
            repo_full_name=repo_full_name,
            repo_id=value.get("repo_id", 0),
            pr_number=pr_number,
            pr_title=value.get("pr_title", ""),
            action=value.get("action", ""),
            author=value.get("author", ""),
            head_sha=value.get("head_sha", ""),
            base_ref=value.get("base_ref", ""),
            head_ref=value.get("head_ref", ""),
            html_url=value.get("html_url", ""),
            installation_id=installation_id,
            changed_files=files_metadata,
            total_files_changed=len(changed_files),
            total_additions=total_additions,
            total_deletions=total_deletions,
            file_types=file_types,
            affected_modules=module_mappings,
        )

        # 7. Build DiffContent
        diff_content = DiffContent(
            event_id=event_id,
            repo_full_name=repo_full_name,
            pr_number=pr_number,
            head_sha=value.get("head_sha", ""),
            installation_id=installation_id,
            files=changed_files,
        )

        # 8. Publish to both topics
        message_key = f"{repo_full_name}#{pr_number}"

        await self._producer.send(
            topic=self._kafka_settings.diff_metadata_topic,
            value=diff_metadata.model_dump(),
            key=message_key,
        )
        kafka_messages_produced.labels(
            topic=self._kafka_settings.diff_metadata_topic
        ).inc()

        await self._producer.send(
            topic=self._kafka_settings.diff_content_topic,
            value=diff_content.model_dump(),
            key=message_key,
        )
        kafka_messages_produced.labels(
            topic=self._kafka_settings.diff_content_topic
        ).inc()

        logger.info(
            "Diff analysis published",
            event_id=event_id,
            repo=repo_full_name,
            pr_number=pr_number,
            files_changed=len(changed_files),
            modules_affected=len(module_mappings),
            total_additions=total_additions,
            total_deletions=total_deletions,
        )
