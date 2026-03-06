"""Tests for the similarity enricher."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models import PROutcome
from app.services.similarity_enricher import compute_incident_rate, enrich_results

from tests.conftest import SAMPLE_SEARCH_RESULTS


class TestEnrichResults:
    """Tests for the enrich_results function."""

    def test_converts_search_results_to_similar_prs(self):
        """Should convert raw search results to SimilarPR objects."""
        current_files = ["src/auth/handler.py", "src/auth/utils.py"]
        result = enrich_results(SAMPLE_SEARCH_RESULTS, current_files)

        assert len(result) == 3
        assert result[0].pr_number == 10  # highest score first
        assert result[0].similarity_score == 0.92

    def test_computes_overlapping_files(self):
        """Should compute file overlap between current and historical PRs."""
        current_files = ["src/auth/handler.py", "src/auth/utils.py"]
        result = enrich_results(SAMPLE_SEARCH_RESULTS, current_files)

        # PR #10 changed handler.py and logger.py → overlap is handler.py
        pr10 = next(p for p in result if p.pr_number == 10)
        assert "src/auth/handler.py" in pr10.overlapping_files
        assert "src/auth/logger.py" not in pr10.overlapping_files

    def test_parses_outcome_correctly(self):
        """Should parse PR outcome from payload."""
        current_files = []
        result = enrich_results(SAMPLE_SEARCH_RESULTS, current_files)

        pr10 = next(p for p in result if p.pr_number == 10)
        assert pr10.outcome == PROutcome.MERGED

        pr25 = next(p for p in result if p.pr_number == 25)
        assert pr25.outcome == PROutcome.INCIDENT

    def test_sorted_by_score_descending(self):
        """Results should be sorted by similarity score, highest first."""
        current_files = []
        result = enrich_results(SAMPLE_SEARCH_RESULTS, current_files)
        scores = [p.similarity_score for p in result]
        assert scores == sorted(scores, reverse=True)

    def test_handles_empty_results(self):
        """Should return empty list for empty input."""
        result = enrich_results([], [])
        assert result == []

    def test_handles_unknown_outcome(self):
        """Should default to UNKNOWN for unrecognized outcomes."""
        results = [
            {
                "id": "repo#1",
                "score": 0.5,
                "payload": {
                    "repo_full_name": "test/repo",
                    "pr_number": 1,
                    "outcome": "invalid_outcome",
                },
            }
        ]
        result = enrich_results(results, [])
        assert result[0].outcome == PROutcome.UNKNOWN

    def test_clamps_score_to_valid_range(self):
        """Scores should be clamped to [0, 1]."""
        results = [
            {
                "id": "repo#1",
                "score": 1.5,
                "payload": {"repo_full_name": "test/repo", "pr_number": 1},
            }
        ]
        result = enrich_results(results, [])
        assert result[0].similarity_score == 1.0

    def test_no_overlap_returns_empty_list(self):
        """Should return empty overlapping_files when no files match."""
        current_files = ["totally/different/file.py"]
        result = enrich_results(SAMPLE_SEARCH_RESULTS, current_files)
        pr30 = next(p for p in result if p.pr_number == 30)
        assert pr30.overlapping_files == []


class TestComputeIncidentRate:
    """Tests for the compute_incident_rate function."""

    def test_computes_rate_correctly(self):
        """Should return fraction of PRs with incident outcome."""
        current_files = []
        similar_prs = enrich_results(SAMPLE_SEARCH_RESULTS, current_files)
        rate = compute_incident_rate(similar_prs)
        # 1 incident out of 3 total
        assert abs(rate - 1 / 3) < 0.01

    def test_returns_zero_for_empty_list(self):
        """Should return 0.0 for empty input."""
        rate = compute_incident_rate([])
        assert rate == 0.0

    def test_returns_one_when_all_incidents(self):
        """Should return 1.0 when all PRs are incidents."""
        results = [
            {
                "id": "repo#1",
                "score": 0.9,
                "payload": {
                    "repo_full_name": "test/repo",
                    "pr_number": 1,
                    "outcome": "incident",
                },
            }
        ]
        similar_prs = enrich_results(results, [])
        rate = compute_incident_rate(similar_prs)
        assert rate == 1.0
