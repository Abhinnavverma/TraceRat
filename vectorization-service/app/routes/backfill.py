"""HTTP route for backfilling historical PR embeddings.

Provides an endpoint to fetch and embed past PRs for a repository,
bootstrapping the similarity search index for new repos.
"""

from __future__ import annotations

import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

# Ensure shared module is importable
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.models import BackfillRequest, BackfillResponse, PRMetadata, PROutcome
from app.services.diff_chunker import MAX_CHUNK_LENGTH
from app.services.embedder import EmbeddingBackend
from app.services.vector_store import VectorStore
from shared.github_auth import GitHubAppAuth
from shared.logging import get_logger

logger = get_logger("backfill")

router = APIRouter(prefix="/repos", tags=["backfill"])

# Module-level references set by main.py lifespan
_embedder: EmbeddingBackend | None = None
_vector_store: VectorStore | None = None
_github_auth: GitHubAppAuth | None = None


def set_dependencies(
    embedder: EmbeddingBackend,
    vector_store: VectorStore,
    github_auth: GitHubAppAuth | None = None,
) -> None:
    """Inject dependencies from the lifespan handler."""
    global _embedder, _vector_store, _github_auth
    _embedder = embedder
    _vector_store = vector_store
    _github_auth = github_auth


@router.post(
    "/{owner}/{repo}/backfill",
    response_model=BackfillResponse,
    summary="Backfill historical PR embeddings",
    description=(
        "Fetches the last N closed/merged PRs for a repository from "
        "GitHub, generates embeddings, and stores them in the vector "
        "database. This bootstraps similarity search for new repos."
    ),
)
async def backfill_repo(
    owner: str,
    repo: str,
    request: BackfillRequest,
) -> BackfillResponse:
    """Backfill historical PR embeddings for a repository."""
    if not _embedder or not _vector_store:
        raise HTTPException(
            status_code=503,
            detail="Service dependencies not initialized",
        )

    repo_full_name = f"{owner}/{repo}"
    indexed = 0
    failed = 0

    try:
        import httpx

        # Get GitHub API token
        token = ""
        if _github_auth:
            token = await _github_auth.get_token_for_repo(owner, repo)

        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        async with httpx.AsyncClient(
            base_url="https://api.github.com",
            headers=headers,
            timeout=30.0,
        ) as client:
            # Fetch closed/merged PRs
            prs = await _fetch_closed_prs(
                client, owner, repo, request.max_prs
            )

            for pr in prs:
                try:
                    await _process_historical_pr(
                        client, owner, repo, pr, repo_full_name
                    )
                    indexed += 1
                except Exception:
                    logger.exception(
                        "Failed to index PR",
                        repo=repo_full_name,
                        pr_number=pr.get("number"),
                    )
                    failed += 1

    except Exception:
        logger.exception(
            "Backfill failed",
            repo=repo_full_name,
        )
        raise HTTPException(
            status_code=500,
            detail=f"Backfill failed for {repo_full_name}",
        )

    total = indexed + failed
    logger.info(
        "Backfill complete",
        repo=repo_full_name,
        indexed=indexed,
        failed=failed,
        total=total,
    )

    return BackfillResponse(
        indexed=indexed,
        failed=failed,
        total=total,
        repo_full_name=repo_full_name,
    )


async def _fetch_closed_prs(
    client, owner: str, repo: str, max_prs: int
) -> list[dict]:
    """Fetch closed PRs from GitHub API with pagination."""
    prs: list[dict] = []
    page = 1
    per_page = min(max_prs, 100)

    while len(prs) < max_prs:
        response = await client.get(
            f"/repos/{owner}/{repo}/pulls",
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": per_page,
                "page": page,
            },
        )
        response.raise_for_status()
        batch = response.json()
        if not batch:
            break
        prs.extend(batch)
        page += 1

    return prs[:max_prs]


async def _process_historical_pr(
    client,
    owner: str,
    repo: str,
    pr: dict,
    repo_full_name: str,
) -> None:
    """Fetch diff for a single PR, embed it, and store in Qdrant."""
    pr_number = pr["number"]
    head_sha = pr.get("head", {}).get("sha", "")

    # Fetch PR files
    response = await client.get(
        f"/repos/{owner}/{repo}/pulls/{pr_number}/files",
        params={"per_page": 100},
    )
    response.raise_for_status()
    files = response.json()

    # Build diff text (same format as diff_chunker)
    parts: list[str] = []
    current_length = 0
    file_names: list[str] = []

    for f in files:
        filename = f.get("filename", "")
        file_names.append(filename)
        status = f.get("status", "unknown")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch = f.get("patch", "")

        header = f"File: {filename} ({status}) +{additions}/-{deletions}"
        file_text = f"{header}\n{patch}\n" if patch else f"{header}\n"

        if current_length + len(file_text) > MAX_CHUNK_LENGTH:
            remaining = MAX_CHUNK_LENGTH - current_length
            if remaining > len(header) + 10:
                parts.append(file_text[:remaining])
            break

        parts.append(file_text)
        current_length += len(file_text)

    diff_text = "".join(parts)
    if not diff_text:
        return

    # Determine outcome
    outcome = PROutcome.UNKNOWN
    if pr.get("merged_at"):
        outcome = PROutcome.MERGED
    elif pr.get("state") == "closed":
        outcome = PROutcome.CLOSED

    # Generate embedding
    vector = await _embedder.embed(diff_text)

    # Build metadata
    metadata = PRMetadata(
        repo_full_name=repo_full_name,
        pr_number=pr_number,
        head_sha=head_sha,
        title=pr.get("title", ""),
        files_changed=file_names,
        total_additions=sum(f.get("additions", 0) for f in files),
        total_deletions=sum(f.get("deletions", 0) for f in files),
        outcome=outcome,
    )

    # Store in Qdrant
    point_id = f"{repo_full_name}#{pr_number}"
    await _vector_store.upsert(
        point_id=point_id,
        vector=vector,
        payload=metadata.model_dump(),
    )

    logger.debug(
        "Indexed historical PR",
        repo=repo_full_name,
        pr_number=pr_number,
        outcome=outcome,
    )
