"""Pydantic models for the Diff Fetching Service."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

# --- GitHub File Change Models ---


class FileStatus(StrEnum):
    """Status of a changed file in a PR."""

    ADDED = "added"
    MODIFIED = "modified"
    REMOVED = "removed"
    RENAMED = "renamed"
    COPIED = "copied"
    CHANGED = "changed"
    UNCHANGED = "unchanged"


class ChangedFile(BaseModel):
    """A single file changed in a pull request.

    Populated from the GitHub Pull Request Files API response.
    """

    filename: str = Field(description="Path of the file relative to repo root")
    status: FileStatus = Field(description="Type of change")
    additions: int = Field(default=0, description="Lines added")
    deletions: int = Field(default=0, description="Lines deleted")
    changes: int = Field(default=0, description="Total line changes")
    patch: str | None = Field(
        default=None, description="Unified diff patch content (may be absent for binary files)"
    )
    previous_filename: str | None = Field(
        default=None, description="Original filename (for renames/copies)"
    )
    sha: str = Field(default="", description="Blob SHA of the file")
    contents_url: str = Field(default="", description="URL to fetch file contents")


class FileTypeBreakdown(BaseModel):
    """Breakdown of changed files by extension."""

    extension: str = Field(description="File extension (e.g., '.py', '.ts')")
    count: int = Field(description="Number of files with this extension")


# --- Module Mapping Models ---


class MappingRule(BaseModel):
    """A rule for mapping file paths to module/service names."""

    pattern: str = Field(description="Regex pattern to match against file paths")
    module_name: str = Field(description="Module/service name to assign on match")
    description: str = Field(default="", description="Human-readable rule description")


class ModuleMapping(BaseModel):
    """Result of mapping changed files to a module/service."""

    module_name: str = Field(description="Detected module or service name")
    matched_files: list[str] = Field(description="Files that matched this module")
    confidence: float = Field(
        ge=0.0, le=1.0, default=1.0, description="Confidence of the mapping"
    )
    matching_rule: str = Field(
        default="", description="The pattern that triggered this mapping"
    )


# --- Kafka Output Models ---


class DiffMetadata(BaseModel):
    """Lightweight diff analysis metadata published to the diff-metadata topic.

    Consumed by the dependency-graph service to compute delta graphs.
    Does NOT include raw patch content to keep messages small.
    """

    event_id: str = Field(description="Original PR event ID from api-gateway")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    repo_id: int = Field(description="GitHub repository ID")
    pr_number: int = Field(description="Pull request number")
    pr_title: str = Field(description="Pull request title")
    action: str = Field(description="PR action that triggered analysis")
    author: str = Field(description="PR author login")
    head_sha: str = Field(description="Head commit SHA")
    base_ref: str = Field(description="Base branch name")
    head_ref: str = Field(description="Head branch name")
    html_url: str = Field(description="Web URL of the PR")
    installation_id: int = Field(description="GitHub App installation ID")

    # File-level summary (no patch content)
    changed_files: list[dict] = Field(
        default_factory=list,
        description="List of changed file metadata (filename, status, additions, deletions)",
    )
    total_files_changed: int = Field(default=0)
    total_additions: int = Field(default=0)
    total_deletions: int = Field(default=0)
    file_types: list[FileTypeBreakdown] = Field(
        default_factory=list, description="Breakdown by file extension"
    )

    # Module mapping results
    affected_modules: list[ModuleMapping] = Field(
        default_factory=list, description="Modules/services impacted by the change"
    )

    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Analysis timestamp (ISO 8601)",
    )


class DiffContent(BaseModel):
    """Full diff content published to the diff-content topic.

    Consumed by the vectorization service for embedding generation.
    Contains the raw patch data for each file.
    """

    event_id: str = Field(description="Original PR event ID from api-gateway")
    repo_full_name: str = Field(description="Full repository name (owner/repo)")
    pr_number: int = Field(description="Pull request number")
    head_sha: str = Field(description="Head commit SHA")
    installation_id: int = Field(description="GitHub App installation ID")

    files: list[ChangedFile] = Field(
        default_factory=list, description="Changed files with full patch content"
    )

    timestamp: str = Field(
        default_factory=lambda: datetime.utcnow().isoformat(),
        description="Analysis timestamp (ISO 8601)",
    )
