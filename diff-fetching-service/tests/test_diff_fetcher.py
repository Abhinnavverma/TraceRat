"""Tests for the GitHub diff fetcher."""

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.models import FileStatus
from app.services.diff_fetcher import DiffFetcher

from tests.conftest import make_github_file_response


class TestDiffFetcherParsing:
    """Test file response parsing."""

    def test_parse_modified_file(self):
        """Standard modified file parses correctly."""
        data = make_github_file_response(
            "src/auth/handler.py", status="modified", additions=10, deletions=5
        )
        result = DiffFetcher._parse_file(data)

        assert result.filename == "src/auth/handler.py"
        assert result.status == FileStatus.MODIFIED
        assert result.additions == 10
        assert result.deletions == 5
        assert result.changes == 15
        assert result.patch is not None

    def test_parse_added_file(self):
        """Added file parses correctly."""
        data = make_github_file_response("new_file.py", status="added")
        result = DiffFetcher._parse_file(data)
        assert result.status == FileStatus.ADDED

    def test_parse_removed_file(self):
        """Removed file parses correctly."""
        data = make_github_file_response("old_file.py", status="removed")
        result = DiffFetcher._parse_file(data)
        assert result.status == FileStatus.REMOVED

    def test_parse_renamed_file(self):
        """Renamed file includes previous_filename."""
        data = make_github_file_response(
            "new_name.py", status="renamed", previous_filename="old_name.py"
        )
        result = DiffFetcher._parse_file(data)
        assert result.status == FileStatus.RENAMED
        assert result.previous_filename == "old_name.py"

    def test_parse_unknown_status_defaults_to_modified(self):
        """Unknown status falls back to 'modified'."""
        data = make_github_file_response("file.py")
        data["status"] = "some-unknown-status"
        result = DiffFetcher._parse_file(data)
        assert result.status == FileStatus.MODIFIED

    def test_parse_file_without_patch(self):
        """Binary files may lack a patch field."""
        data = make_github_file_response("image.png")
        del data["patch"]
        result = DiffFetcher._parse_file(data)
        assert result.patch is None


class TestDiffFetcherAPI:
    """Test API fetching with mocked HTTP responses."""

    @pytest.mark.asyncio
    async def test_fetch_single_page(self):
        """Fetch files for a PR with fewer than 100 files."""
        mock_files = [
            make_github_file_response("src/auth/handler.py"),
            make_github_file_response("src/auth/models.py"),
            make_github_file_response("tests/test_auth.py", status="added"),
        ]

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = mock_files
        mock_response.raise_for_status = MagicMock()

        # Second call returns empty (no more pages)
        mock_empty_response = MagicMock()
        mock_empty_response.status_code = 200
        mock_empty_response.json.return_value = []
        mock_empty_response.raise_for_status = MagicMock()

        with patch("app.services.diff_fetcher.GitHubAppAuth") as mock_auth_cls:
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.get_token = AsyncMock(return_value="test-token")

            fetcher = DiffFetcher()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                # First call returns files, second returns empty
                mock_client.get = AsyncMock(side_effect=[mock_response, mock_empty_response])
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                files = await fetcher.fetch_changed_files(
                    owner="octocat", repo="hello-world",
                    pr_number=42, installation_id=99999,
                )

        assert len(files) == 3
        assert files[0].filename == "src/auth/handler.py"
        assert files[2].status == FileStatus.ADDED

    @pytest.mark.asyncio
    async def test_fetch_handles_pagination(self):
        """Fetch paginated results when PR has >100 files."""
        # Page 1: 100 files (full page triggers pagination)
        page1 = [make_github_file_response(f"file_{i}.py") for i in range(100)]
        # Page 2: 20 files (partial page means last page)
        page2 = [make_github_file_response(f"file_{i + 100}.py") for i in range(20)]

        mock_resp_1 = MagicMock()
        mock_resp_1.status_code = 200
        mock_resp_1.json.return_value = page1
        mock_resp_1.raise_for_status = MagicMock()

        mock_resp_2 = MagicMock()
        mock_resp_2.status_code = 200
        mock_resp_2.json.return_value = page2
        mock_resp_2.raise_for_status = MagicMock()

        with patch("app.services.diff_fetcher.GitHubAppAuth") as mock_auth_cls:
            mock_auth_instance = mock_auth_cls.return_value
            mock_auth_instance.get_token = AsyncMock(return_value="test-token")

            fetcher = DiffFetcher()

            with patch("httpx.AsyncClient") as mock_client_cls:
                mock_client = AsyncMock()
                mock_client.get = AsyncMock(side_effect=[mock_resp_1, mock_resp_2])
                mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
                mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

                files = await fetcher.fetch_changed_files(
                    owner="octocat", repo="hello-world",
                    pr_number=42, installation_id=99999,
                )

        assert len(files) == 120
