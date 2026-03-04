"""Pytest configuration and fixtures for diff-fetching-service tests."""

import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models import ChangedFile, FileStatus


def make_changed_file(
    filename: str,
    status: str = "modified",
    additions: int = 10,
    deletions: int = 5,
    patch: str | None = "@@ -1,5 +1,10 @@\n+new line",
    previous_filename: str | None = None,
) -> ChangedFile:
    """Factory for creating test ChangedFile instances."""
    return ChangedFile(
        filename=filename,
        status=FileStatus(status),
        additions=additions,
        deletions=deletions,
        changes=additions + deletions,
        patch=patch,
        previous_filename=previous_filename,
        sha="abc123",
        contents_url=f"https://api.github.com/repos/test/repo/contents/{filename}",
    )


def make_github_file_response(
    filename: str,
    status: str = "modified",
    additions: int = 10,
    deletions: int = 5,
    patch: str = "@@ -1,5 +1,10 @@\n+new line",
    previous_filename: str | None = None,
) -> dict:
    """Factory for creating mock GitHub API file responses."""
    data = {
        "sha": "abc123def456",
        "filename": filename,
        "status": status,
        "additions": additions,
        "deletions": deletions,
        "changes": additions + deletions,
        "patch": patch,
        "contents_url": f"https://api.github.com/repos/test/repo/contents/{filename}",
    }
    if previous_filename:
        data["previous_filename"] = previous_filename
    return data


SAMPLE_PR_EVENT = {
    "event_id": "evt-001",
    "repo_full_name": "octocat/hello-world",
    "repo_id": 123456,
    "pr_number": 42,
    "pr_title": "Fix authentication bug",
    "action": "opened",
    "author": "octocat",
    "head_sha": "abc123def456",
    "base_ref": "main",
    "head_ref": "fix/auth-bug",
    "diff_url": "https://github.com/octocat/hello-world/pull/42.diff",
    "html_url": "https://github.com/octocat/hello-world/pull/42",
    "installation_id": 99999,
    "changed_files": 3,
    "additions": 50,
    "deletions": 10,
    "timestamp": "2026-03-04T10:00:00",
}
