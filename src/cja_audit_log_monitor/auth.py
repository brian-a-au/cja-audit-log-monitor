"""Authentication handling for Adobe CJA API."""

import logging
import re
from datetime import UTC, datetime, timedelta

import httpx

from .config import CJASettings
from .models import TokenInfo

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


class TokenManager:
    """Manages OAuth tokens for Adobe CJA API."""

    def __init__(self, settings: CJASettings) -> None:
        self.settings = settings
        self._token: TokenInfo | None = None
        self._token_expiry: datetime | None = None

    def get_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._is_token_valid():
            return self._token.access_token.get_secret_value()  # type: ignore

        if not self.settings.is_oauth_configured():
            raise AuthenticationError(
                "OAuth not configured. Set ORG_ID, CLIENT_ID, SECRET, and SCOPES "
                "environment variables. See .env.example for details."
            )

        self._token = self._get_oauth_token()

        # Set expiry with 5 minute buffer
        self._token_expiry = datetime.now(UTC) + timedelta(
            seconds=self._token.expires_in - 300
        )
        self._token.expires_at = self._token_expiry

        logger.debug("Token refreshed, expires at %s", self._token_expiry)
        return self._token.access_token.get_secret_value()

    def _is_token_valid(self) -> bool:
        """Check if current token is still valid."""
        if not self._token or not self._token_expiry:
            return False
        return datetime.now(UTC) < self._token_expiry

    def _get_oauth_token(self) -> TokenInfo:
        """Get token using OAuth Server-to-Server flow."""
        token_url = f"{self.settings.ims_base_url}/ims/token/v3"

        data = {
            "grant_type": "client_credentials",
            "client_id": self.settings.client_id,
            "client_secret": self.settings.secret.get_secret_value(),
            "scope": ",".join(self.settings.scopes_list),
        }

        logger.debug("Requesting OAuth token from %s", token_url)

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(token_url, data=data)
                response.raise_for_status()
                try:
                    token_data = response.json()
                except ValueError:
                    raise AuthenticationError("IMS returned a non-JSON response") from None

                try:
                    return TokenInfo(
                        access_token=token_data["access_token"],
                        token_type=token_data.get("token_type", "bearer"),
                        expires_in=int(token_data.get("expires_in", 86400)),
                    )
                except (KeyError, ValueError, TypeError, AttributeError):
                    raise AuthenticationError("IMS response had no access_token") from None
        except httpx.HTTPStatusError as e:
            error_detail = self._parse_oauth_error(e)
            raise AuthenticationError(error_detail) from e
        except httpx.RequestError as e:
            raise AuthenticationError(f"OAuth request failed: {e}") from e

    def _parse_oauth_error(self, e: httpx.HTTPStatusError) -> str:
        """Parse OAuth error response and return helpful message."""
        try:
            error_data = e.response.json()
            error_code = error_data.get("error", "")
            error_desc = error_data.get("error_description", "")

            if error_code == "invalid_client":
                return (
                    f"invalid_client: {error_desc}\n"
                    "Check that CLIENT_ID and SECRET are correct and not expired. "
                    "Re-retrieve credentials from Adobe Developer Console."
                )
            elif error_code == "invalid_scope":
                return (
                    f"invalid_scope: {error_desc}\n"
                    "Copy SCOPES exactly from Developer Console > OAuth Server-to-Server > Scopes."
                )
            elif error_code == "unauthorized_client":
                return (
                    f"unauthorized_client: {error_desc}\n"
                    "Ensure OAuth Server-to-Server is enabled in Developer Console."
                )
            else:
                return f"OAuth error ({e.response.status_code}): {error_code} - {error_desc}"
        except Exception:
            status = e.response.status_code
            if status == 401:
                return (
                    "401 Unauthorized: Check that credentials are current and not regenerated."
                )
            elif status == 403:
                return (
                    "403 Forbidden: Ensure both CJA API and Experience Platform API are added "
                    "to your project in Developer Console, and service account is assigned "
                    "to product profiles in Admin Console."
                )
            body = re.sub(r"client_secret=[^&\s]+", "client_secret=***", e.response.text)[:200]
            return f"OAuth authentication failed: {status} - {body}"

    def get_auth_headers(self) -> dict[str, str]:
        """Get headers with authentication for API requests."""
        token = self.get_token()
        return {
            "Authorization": f"Bearer {token}",
            "x-api-key": self.settings.client_id,
            "x-gw-ims-org-id": self.settings.org_id,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    def invalidate_token(self) -> None:
        """Invalidate the current token, forcing refresh on next request."""
        self._token = None
        self._token_expiry = None
        logger.debug("Token invalidated")
