"""Seed Qdrant with historical PR embeddings from a public GitHub repo.

Fetches the last N merged/closed PRs from the GitHub API, generates
embeddings using the local SentenceTransformer model (no API key),
and upserts them into Qdrant with the same payload schema the
vectorization-service uses.

Usage::

    python tools/seed_prs.py --repo tiangolo/fastapi
    python tools/seed_prs.py --repo pallets/flask --count 50
"""

from __future__ import annotations

import argparse
import sys
import uuid
from datetime import datetime

import httpx
from qdrant_client import QdrantClient
from qdrant_client.models import Distance, PointStruct, VectorParams
from sentence_transformers import SentenceTransformer
import os

# ---------------------------------------------------------------------------
# GitHub API
# ---------------------------------------------------------------------------

GITHUB_API = "https://api.github.com"


def _github_headers() -> dict[str, str]:
    """Return GitHub API headers, including auth token if available."""
    headers = {"Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def fetch_closed_prs(repo: str, count: int = 30) -> list[dict]:
    """Fetch the most recently closed/merged PRs."""
    prs: list[dict] = []
    page = 1
    per_page = min(count, 100)
    headers = _github_headers()

    while len(prs) < count:
        url = f"{GITHUB_API}/repos/{repo}/pulls"
        resp = httpx.get(
            url,
            headers=headers,
            params={
                "state": "closed",
                "sort": "updated",
                "direction": "desc",
                "per_page": per_page,
                "page": page,
            },
            timeout=30,
            follow_redirects=True,
        )
        resp.raise_for_status()
        batch = resp.json()
        if not batch:
            break
        prs.extend(batch)
        page += 1

    return prs[:count]


def fetch_pr_files(repo: str, pr_number: int) -> list[dict]:
    """Fetch the changed files for a PR (max 100)."""
    url = f"{GITHUB_API}/repos/{repo}/pulls/{pr_number}/files"
    headers = _github_headers()
    resp = httpx.get(url, headers=headers, params={"per_page": 100}, timeout=30, follow_redirects=True)
    if resp.status_code != 200:
        return []
    return resp.json()


# ---------------------------------------------------------------------------
# Diff text builder (mirrors DiffChunker logic)
# ---------------------------------------------------------------------------


def build_diff_text(files: list[dict], max_length: int = 8000) -> str:
    """Build a text representation of the diff for embedding."""
    parts: list[str] = []
    for f in files:
        filename = f.get("filename", "")
        status = f.get("status", "modified")
        additions = f.get("additions", 0)
        deletions = f.get("deletions", 0)
        patch = f.get("patch", "")

        header = f"[{status}] {filename} (+{additions}/-{deletions})"
        parts.append(header)
        if patch:
            parts.append(patch[:500])  # Truncate large patches

    text = "\n\n".join(parts)
    return text[:max_length]


# ---------------------------------------------------------------------------
# Qdrant population
# ---------------------------------------------------------------------------


def seed_qdrant(
    qdrant_host: str,
    qdrant_port: int,
    collection: str,
    repo: str,
    prs: list[dict],
    model: SentenceTransformer,
    dimension: int,
) -> int:
    """Embed PRs and upsert into Qdrant. Returns count of seeded PRs."""
    client = QdrantClient(host=qdrant_host, port=qdrant_port, timeout=30)

    # Ensure collection exists
    existing = [c.name for c in client.get_collections().collections]
    if collection not in existing:
        client.create_collection(
            collection_name=collection,
            vectors_config=VectorParams(size=dimension, distance=Distance.COSINE),
        )
        print(f"  Created Qdrant collection '{collection}'")

    seeded = 0

    for i, pr in enumerate(prs):
        pr_number = pr["number"]
        title = pr.get("title", "")
        merged = pr.get("merged_at") is not None
        outcome = "merged" if merged else "closed"
        head_sha = pr.get("head", {}).get("sha", "")

        if (i + 1) % 10 == 0 or i == 0:
            print(f"  Processing PR #{pr_number} ({i + 1}/{len(prs)}) …")

        # Fetch files
        files = fetch_pr_files(repo, pr_number)
        if not files:
            continue

        # Build diff text and embed
        diff_text = build_diff_text(files)
        if not diff_text.strip():
            continue

        vector = model.encode(diff_text, normalize_embeddings=True).tolist()

        # Build payload matching PRMetadata schema
        filenames = [f.get("filename", "") for f in files]
        total_additions = sum(f.get("additions", 0) for f in files)
        total_deletions = sum(f.get("deletions", 0) for f in files)

        # Derive modules_affected from directory structure
        modules: set[str] = set()
        for fn in filenames:
            parts = fn.replace("\\", "/").split("/")
            if len(parts) > 1:
                modules.add(parts[0])

        payload = {
            "repo_full_name": repo,
            "pr_number": pr_number,
            "head_sha": head_sha,
            "title": title,
            "files_changed": filenames,
            "modules_affected": sorted(modules),
            "total_additions": total_additions,
            "total_deletions": total_deletions,
            "outcome": outcome,
            "timestamp": pr.get("closed_at", datetime.utcnow().isoformat()),
        }

        point_id = f"{repo}#{pr_number}"
        # Qdrant needs a UUID or int for point ID — hash the string
        uid = uuid.uuid5(uuid.NAMESPACE_URL, point_id)

        client.upsert(
            collection_name=collection,
            points=[
                PointStruct(
                    id=uid.hex,
                    vector=vector,
                    payload=payload,
                )
            ],
        )
        seeded += 1

    client.close()
    return seeded


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main():
    parser = argparse.ArgumentParser(
        description="Seed Qdrant with historical PR embeddings from GitHub."
    )
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repo in owner/name format (e.g. tiangolo/fastapi)",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=30,
        help="Number of recent closed PRs to seed (default: 30)",
    )
    parser.add_argument(
        "--qdrant-host",
        default="localhost",
        help="Qdrant host (default: localhost)",
    )
    parser.add_argument(
        "--qdrant-port",
        type=int,
        default=6333,
        help="Qdrant port (default: 6333)",
    )
    parser.add_argument(
        "--collection",
        default="pr-embeddings",
        help="Qdrant collection name (default: pr-embeddings)",
    )
    parser.add_argument(
        "--model",
        default="all-MiniLM-L6-v2",
        help="SentenceTransformer model name (default: all-MiniLM-L6-v2)",
    )
    args = parser.parse_args()

    print(f"[1/4] Loading embedding model ({args.model}) …")
    model = SentenceTransformer(args.model)
    dimension = model.get_sentence_embedding_dimension()
    print(f"  Model loaded (dimension={dimension})")

    print(f"[2/4] Fetching {args.count} closed PRs from {args.repo} …")
    prs = fetch_closed_prs(args.repo, args.count)
    print(f"  Fetched {len(prs)} PRs")

    print(f"[3/4] Embedding PR diffs and seeding Qdrant …")
    seeded = seed_qdrant(
        args.qdrant_host,
        args.qdrant_port,
        args.collection,
        args.repo,
        prs,
        model,
        dimension,
    )
    print(f"  ✓ Qdrant seeded: {seeded} PRs embedded")

    print("[4/4] Done!")
    print(f"  Neo4j browser:  http://localhost:7474")
    print(f"  Qdrant dashboard: http://localhost:6333/dashboard")


if __name__ == "__main__":
    main()
