"""GitHub API client for posting PR comments.

Uses GitHub App installation tokens for authentication.
"""

import httpx

from shared.config import GitHubAppSettings
from shared.github_auth import GitHubAppAuth
from shared.logging import get_logger
from shared.metrics import github_api_requests

logger = get_logger("github_client")

GITHUB_API_BASE = "https://api.github.com"


class GitHubClient:
    """Async client for GitHub API operations.

    Authenticates using GitHub App installation tokens.
    """

    def __init__(self, settings: GitHubAppSettings | None = None):
        self._settings = settings or GitHubAppSettings()
        self._auth = GitHubAppAuth(self._settings)

    async def post_pr_comment(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        installation_id: int,
    ) -> str:
        """Post a comment on a GitHub Pull Request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            body: Comment body (Markdown).
            installation_id: GitHub App installation ID.

        Returns:
            URL of the created comment.

        Raises:
            httpx.HTTPStatusError: If the GitHub API returns an error.
        """
        token = await self._auth.get_token(installation_id)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/issues/{pr_number}/comments"

        async with httpx.AsyncClient() as client:
            response = await client.post(
                url,
                json={"body": body},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )

            github_api_requests.labels(
                endpoint="create_issue_comment",
                status=str(response.status_code),
            ).inc()

            response.raise_for_status()
            data = response.json()

            logger.info(
                "PR comment created",
                repo=f"{owner}/{repo}",
                pr_number=pr_number,
                comment_id=data.get("id"),
            )

            return data.get("html_url", "")

    async def get_pr_diff(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
    ) -> str:
        """Fetch the diff for a Pull Request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            installation_id: GitHub App installation ID.

        Returns:
            PR diff as a string.
        """
        token = await self._auth.get_token(installation_id)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github.diff",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )

            github_api_requests.labels(
                endpoint="get_pr_diff",
                status=str(response.status_code),
            ).inc()

            response.raise_for_status()
            return response.text

    async def get_pr_files(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        installation_id: int,
    ) -> list[dict]:
        """Fetch the list of changed files in a Pull Request.

        Args:
            owner: Repository owner.
            repo: Repository name.
            pr_number: Pull request number.
            installation_id: GitHub App installation ID.

        Returns:
            List of file change objects.
        """
        token = await self._auth.get_token(installation_id)
        url = f"{GITHUB_API_BASE}/repos/{owner}/{repo}/pulls/{pr_number}/files"

        async with httpx.AsyncClient() as client:
            response = await client.get(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "X-GitHub-Api-Version": "2022-11-28",
                },
                timeout=30.0,
            )

            github_api_requests.labels(
                endpoint="get_pr_files",
                status=str(response.status_code),
            ).inc()

            response.raise_for_status()
            return response.json()
