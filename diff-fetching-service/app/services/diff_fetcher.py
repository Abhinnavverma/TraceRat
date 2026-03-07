"""GitHub diff fetcher — retrieves PR file changes via the GitHub API.

Uses the Pull Request Files API to get structured file-level changes
including filename, status, additions/deletions, and patch content.
"""


import httpx

from app.models import ChangedFile, FileStatus
from shared.config import GitHubAppSettings
from shared.github_auth import GitHubAppAuth
from shared.logging import get_logger
from shared.metrics import github_api_requests

logger = get_logger("diff_fetcher")

GITHUB_API_BASE = "https://api.github.com"
FILES_PER_PAGE = 100  # GitHub max per page


class DiffFetcher:
    """Fetches PR file changes from the GitHub API.

    Handles pagination for PRs with >100 changed files.
    """

    def __init__(self, settings: GitHubAppSettings | None = None):
        self._settings = settings or GitHubAppSettings()
        self._auth = GitHubAppAuth(self._settings)

    async def fetch_changed_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
    ) -> list[ChangedFile]:
        """Fetch all changed files for a pull request.

        Automatically paginates if the PR has more than 100 files.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            installation_id: GitHub App installation ID.

        Returns:
            List of ChangedFile models with patch content.

        Raises:
            httpx.HTTPStatusError: If the GitHub API returns an error.
        """
        token = await self._auth.get_token(installation_id)
        all_files: list[ChangedFile] = []
        page = 1

        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            while True:
                url = (
                    f"{GITHUB_API_BASE}/repos/{owner}/{repo}"
                    f"/pulls/{pr_number}/files"
                )

                headers = {
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                }
                if token:
                    headers["Authorization"] = f"Bearer {token}"

                response = await client.get(
                    url,
                    params={"per_page": FILES_PER_PAGE, "page": page},
                    headers=headers,
                )

                github_api_requests.labels(
                    endpoint="get_pr_files",
                    status=str(response.status_code),
                ).inc()

                response.raise_for_status()
                files_data = response.json()

                if not files_data:
                    break

                for file_data in files_data:
                    changed_file = self._parse_file(file_data)
                    all_files.append(changed_file)

                # Check if there are more pages
                if len(files_data) < FILES_PER_PAGE:
                    break

                page += 1

        logger.info(
            "Fetched PR files",
            owner=owner,
            repo=repo,
            pr_number=pr_number,
            total_files=len(all_files),
            pages_fetched=page,
        )

        return all_files

    @staticmethod
    def _parse_file(file_data: dict) -> ChangedFile:
        """Parse a GitHub API file response into a ChangedFile model.

        Args:
            file_data: Raw file dict from the GitHub API response.

        Returns:
            Parsed ChangedFile model.
        """
        # Normalize status to our enum
        raw_status = file_data.get("status", "modified")
        try:
            status = FileStatus(raw_status)
        except ValueError:
            status = FileStatus.MODIFIED

        return ChangedFile(
            filename=file_data.get("filename", ""),
            status=status,
            additions=file_data.get("additions", 0),
            deletions=file_data.get("deletions", 0),
            changes=file_data.get("changes", 0),
            patch=file_data.get("patch"),
            previous_filename=file_data.get("previous_filename"),
            sha=file_data.get("sha", ""),
            contents_url=file_data.get("contents_url", ""),
        )
