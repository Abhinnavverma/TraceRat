"""GitHub App authentication utilities.

Handles webhook signature verification, JWT generation,
and installation access token retrieval.
"""

import hashlib
import hmac
import logging
import time
from pathlib import Path

import httpx
import jwt

from shared.config import GitHubAppSettings

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"


def verify_webhook_signature(payload: bytes, signature: str, secret: str) -> bool:
    """Verify GitHub webhook HMAC-SHA256 signature.

    Args:
        payload: Raw request body bytes.
        signature: Value of X-Hub-Signature-256 header (e.g. "sha256=abc...").
        secret: Webhook secret configured in the GitHub App.

    Returns:
        True if the signature is valid.
    """
    if not signature.startswith("sha256="):
        return False

    expected = hmac.new(
        key=secret.encode("utf-8"),
        msg=payload,
        digestmod=hashlib.sha256,
    ).hexdigest()

    received = signature.removeprefix("sha256=")
    return hmac.compare_digest(expected, received)


def generate_jwt(app_id: str, private_key_path: str) -> str:
    """Generate a JSON Web Token for GitHub App authentication.

    The JWT is valid for 10 minutes (GitHub's maximum).

    Args:
        app_id: GitHub App ID.
        private_key_path: Path to the PEM private key file.

    Returns:
        Encoded JWT string.
    """
    private_key = Path(private_key_path).read_text()
    now = int(time.time())

    payload = {
        "iat": now - 60,  # issued at (60s in past to handle clock drift)
        "exp": now + (10 * 60),  # expires in 10 minutes
        "iss": app_id,
    }

    return jwt.encode(payload, private_key, algorithm="RS256")


async def get_installation_token(
    app_id: str, private_key_path: str, installation_id: int
) -> str:
    """Get an installation access token for a GitHub App installation.

    Args:
        app_id: GitHub App ID.
        private_key_path: Path to the PEM private key file.
        installation_id: GitHub App installation ID.

    Returns:
        Installation access token string.
    """
    app_jwt = generate_jwt(app_id, private_key_path)

    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{GITHUB_API_BASE}/app/installations/{installation_id}/access_tokens",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["token"]


async def get_installation_id_for_repo(
    app_id: str, private_key_path: str, owner: str, repo: str
) -> int:
    """Find the installation ID for a specific repository.

    Args:
        app_id: GitHub App ID.
        private_key_path: Path to the PEM private key file.
        owner: Repository owner.
        repo: Repository name.

    Returns:
        Installation ID.
    """
    app_jwt = generate_jwt(app_id, private_key_path)

    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"{GITHUB_API_BASE}/repos/{owner}/{repo}/installation",
            headers={
                "Authorization": f"Bearer {app_jwt}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["id"]


class GitHubAppAuth:
    """High-level GitHub App authentication manager.

    Caches installation tokens and refreshes them as needed.
    """

    def __init__(self, settings: GitHubAppSettings | None = None):
        self._settings = settings or GitHubAppSettings()
        self._token_cache: dict[int, tuple[str, float]] = {}  # installation_id -> (token, expiry)

    def verify_signature(self, payload: bytes, signature: str) -> bool:
        """Verify webhook signature using configured secret."""
        return verify_webhook_signature(payload, signature, self._settings.webhook_secret)

    async def get_token(self, installation_id: int) -> str | None:
        """Get a cached or fresh installation token.

        Args:
            installation_id: GitHub App installation ID.
                Use 0 for public repo access without authentication.

        Returns:
            Valid installation access token, or None for public API access.
        """
        # installation_id == 0 means public API (no auth needed)
        if installation_id == 0:
            return None

        # Check cache (tokens valid for 1 hour, refresh at 50 min)
        if installation_id in self._token_cache:
            token, expiry = self._token_cache[installation_id]
            if time.time() < expiry:
                return token

        token = await get_installation_token(
            self._settings.app_id,
            self._settings.private_key_path,
            installation_id,
        )
        # Cache for 50 minutes (tokens last 60 min)
        self._token_cache[installation_id] = (token, time.time() + 3000)
        return token

    async def get_token_for_repo(self, owner: str, repo: str) -> str:
        """Get an installation token for a specific repository.

        Args:
            owner: Repository owner.
            repo: Repository name.

        Returns:
            Valid installation access token.
        """
        installation_id = await get_installation_id_for_repo(
            self._settings.app_id,
            self._settings.private_key_path,
            owner,
            repo,
        )
        return await self.get_token(installation_id)
