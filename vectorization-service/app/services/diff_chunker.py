"""Diff chunking utility for preparing PR diffs for embedding.

Combines individual file patches into a single text representation
suitable for vector embedding. Produces one embedding per PR (not
per file) to keep the vector count manageable and ensure similarity
search matches the full change context.
"""

from __future__ import annotations

# Maximum character length for the combined diff text.
# Keeps embedding input within model token limits (~8000 chars ≈ ~2000 tokens).
MAX_CHUNK_LENGTH = 8000

# File status priority: modified files carry the most signal,
# followed by added, then removed. Renamed/copied are lower priority.
_STATUS_PRIORITY = {
    "modified": 0,
    "added": 1,
    "removed": 2,
    "changed": 3,
    "renamed": 4,
    "copied": 5,
    "unchanged": 6,
}


def _file_sort_key(file_dict: dict) -> tuple[int, str]:
    """Sort key: prioritize modified files, then by filename."""
    status = file_dict.get("status", "unchanged")
    priority = _STATUS_PRIORITY.get(status, 99)
    return (priority, file_dict.get("filename", ""))


def chunk_diff(diff_content: dict, max_length: int = MAX_CHUNK_LENGTH) -> str:
    """Combine file patches into a single text for embedding.

    Args:
        diff_content: Deserialized DiffContent message from Kafka.
            Expected shape: {"files": [...], "repo_full_name": "...", ...}
        max_length: Maximum character length for the combined text.

    Returns:
        A single string containing file headers and patches,
        truncated to max_length if necessary.
    """
    files = diff_content.get("files", [])
    if not files:
        return ""

    # Sort by priority: modified > added > removed > rest
    sorted_files = sorted(files, key=_file_sort_key)

    parts: list[str] = []
    current_length = 0

    for file_dict in sorted_files:
        filename = file_dict.get("filename", "unknown")
        status = file_dict.get("status", "unknown")
        patch = file_dict.get("patch")

        # Build header line
        additions = file_dict.get("additions", 0)
        deletions = file_dict.get("deletions", 0)
        header = f"File: {filename} ({status}) +{additions}/-{deletions}"

        if patch:
            file_text = f"{header}\n{patch}\n"
        else:
            # Binary or empty files — include header only
            file_text = f"{header}\n[no patch content]\n"

        # Check if adding this file would exceed the limit
        if current_length + len(file_text) > max_length:
            # Add as much as we can fit
            remaining = max_length - current_length
            if remaining > len(header) + 10:
                # Enough space for at least the header + some patch
                truncated = file_text[:remaining]
                parts.append(truncated)
            break

        parts.append(file_text)
        current_length += len(file_text)

    return "".join(parts)


def extract_file_list(diff_content: dict) -> list[str]:
    """Extract the list of filenames from a diff-content message.

    Args:
        diff_content: Deserialized DiffContent message.

    Returns:
        List of filenames that were changed.
    """
    return [
        f.get("filename", "")
        for f in diff_content.get("files", [])
        if f.get("filename")
    ]


def compute_change_stats(diff_content: dict) -> dict[str, int]:
    """Compute aggregate change statistics from a diff-content message.

    Returns:
        Dict with total_additions, total_deletions, total_files.
    """
    files = diff_content.get("files", [])
    total_additions = sum(f.get("additions", 0) for f in files)
    total_deletions = sum(f.get("deletions", 0) for f in files)
    return {
        "total_additions": total_additions,
        "total_deletions": total_deletions,
        "total_files": len(files),
    }
