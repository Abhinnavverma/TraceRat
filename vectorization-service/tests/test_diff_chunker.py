"""Tests for the diff chunking utility."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.diff_chunker import (
    chunk_diff,
    compute_change_stats,
    extract_file_list,
)

from tests.conftest import SAMPLE_DIFF_CONTENT


class TestChunkDiff:
    """Tests for the chunk_diff function."""

    def test_chunks_all_files(self):
        """Should include headers and patches for all files."""
        result = chunk_diff(SAMPLE_DIFF_CONTENT)
        # Modified files come first in priority order
        assert "src/auth/handler.py" in result
        assert "src/auth/utils.py" in result
        assert "docs/README.md" in result

    def test_modified_files_come_first(self):
        """Modified files should appear before added files."""
        result = chunk_diff(SAMPLE_DIFF_CONTENT)
        handler_pos = result.index("src/auth/handler.py")
        utils_pos = result.index("src/auth/utils.py")
        assert handler_pos < utils_pos

    def test_includes_patch_content(self):
        """Should include actual patch content for files with patches."""
        result = chunk_diff(SAMPLE_DIFF_CONTENT)
        assert "validate_token" in result
        assert "audit_log" in result

    def test_handles_no_patch_content(self):
        """Files without patches should show [no patch content]."""
        result = chunk_diff(SAMPLE_DIFF_CONTENT)
        assert "[no patch content]" in result

    def test_truncates_at_max_length(self):
        """Should truncate when total text exceeds max_length."""
        result = chunk_diff(SAMPLE_DIFF_CONTENT, max_length=100)
        assert len(result) <= 100

    def test_empty_files_returns_empty_string(self):
        """Should return empty string when no files are present."""
        result = chunk_diff({"files": []})
        assert result == ""

    def test_missing_files_key_returns_empty(self):
        """Should handle missing 'files' key gracefully."""
        result = chunk_diff({})
        assert result == ""

    def test_includes_additions_and_deletions_in_header(self):
        """Header should show +additions/-deletions."""
        result = chunk_diff(SAMPLE_DIFF_CONTENT)
        assert "+30/-5" in result
        assert "+50/-0" in result

    def test_handles_single_file(self):
        """Should work with a single-file diff."""
        single = {
            "files": [
                {
                    "filename": "main.py",
                    "status": "modified",
                    "additions": 1,
                    "deletions": 1,
                    "patch": "+new line\n-old line\n",
                }
            ]
        }
        result = chunk_diff(single)
        assert "main.py" in result
        assert "+new line" in result


class TestExtractFileList:
    """Tests for the extract_file_list function."""

    def test_extracts_all_filenames(self):
        """Should extract filenames from all changed files."""
        result = extract_file_list(SAMPLE_DIFF_CONTENT)
        assert len(result) == 3
        assert "src/auth/handler.py" in result
        assert "src/auth/utils.py" in result
        assert "docs/README.md" in result

    def test_empty_input(self):
        """Should return empty list for no files."""
        result = extract_file_list({"files": []})
        assert result == []

    def test_skips_empty_filenames(self):
        """Should skip files with empty/missing filenames."""
        data = {"files": [{"filename": ""}, {"filename": "real.py"}]}
        result = extract_file_list(data)
        assert result == ["real.py"]


class TestComputeChangeStats:
    """Tests for the compute_change_stats function."""

    def test_computes_totals(self):
        """Should sum additions, deletions, and file count."""
        result = compute_change_stats(SAMPLE_DIFF_CONTENT)
        assert result["total_additions"] == 82  # 30 + 50 + 2
        assert result["total_deletions"] == 6  # 5 + 0 + 1
        assert result["total_files"] == 3

    def test_empty_files(self):
        """Should return zeros for empty file list."""
        result = compute_change_stats({"files": []})
        assert result["total_additions"] == 0
        assert result["total_deletions"] == 0
        assert result["total_files"] == 0
