"""Similarity search result enrichment.

Converts raw Qdrant search results into structured SimilarPR objects,
computing overlapping files and historical incident rates for the
prediction service.
"""

from __future__ import annotations

from app.models import PROutcome, SimilarPR


def enrich_results(
    search_results: list[dict],
    current_files: list[str],
) -> list[SimilarPR]:
    """Convert raw Qdrant search results into SimilarPR objects.

    Args:
        search_results: List of dicts from VectorStore.search()
            with 'id', 'score', and 'payload' keys.
        current_files: List of filenames changed in the current PR.

    Returns:
        List of SimilarPR objects sorted by similarity score descending.
    """
    similar_prs: list[SimilarPR] = []
    current_file_set = set(current_files)

    for result in search_results:
        payload = result.get("payload", {})
        score = result.get("score", 0.0)

        # Compute overlapping files
        historical_files = set(payload.get("files_changed", []))
        overlapping = sorted(current_file_set & historical_files)

        # Parse outcome safely
        raw_outcome = payload.get("outcome", PROutcome.UNKNOWN)
        try:
            outcome = PROutcome(raw_outcome)
        except ValueError:
            outcome = PROutcome.UNKNOWN

        similar_pr = SimilarPR(
            repo_full_name=payload.get("repo_full_name", ""),
            pr_number=payload.get("pr_number", 0),
            similarity_score=min(max(score, 0.0), 1.0),
            title=payload.get("title", ""),
            outcome=outcome,
            overlapping_files=overlapping,
            blast_radius_score=payload.get("blast_radius_score"),
            timestamp=payload.get("timestamp", ""),
        )
        similar_prs.append(similar_pr)

    return sorted(similar_prs, key=lambda p: p.similarity_score, reverse=True)


def compute_incident_rate(similar_prs: list[SimilarPR]) -> float:
    """Calculate the fraction of similar PRs that resulted in incidents.

    Args:
        similar_prs: List of SimilarPR objects.

    Returns:
        Incident rate between 0.0 and 1.0.
        Returns 0.0 if the list is empty.
    """
    if not similar_prs:
        return 0.0

    incident_count = sum(
        1 for pr in similar_prs if pr.outcome == PROutcome.INCIDENT
    )
    return incident_count / len(similar_prs)
