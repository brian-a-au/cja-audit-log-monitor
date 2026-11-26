"""Authentication handling for Adobe CJA API."""

import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

import httpx

from .config import CJASettings
from .models import TokenInfo

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails.

    ``transient`` is True when trying again later may work: a network error, or IMS
    answering 429 or 5xx. Bad or missing credentials are not transient.
    """

    def __init__(self, message: str, transient: bool = False, network: bool = False) -> None:
        super().__init__(message)
        self.transient = transient
        # True when IMS could not be reached at all (DNS, refused, timed out).
        self.network = network


class TokenManager:
    """Manages OAuth tokens for Adobe CJA API."""

    def __init__(self, settings: CJASettings) -> None:
        self.settings = settings
        self._token: TokenInfo | None = None
        self._token_expiry: datetime | None = None
        # Plain Lock: nothing under it calls back into get_token/invalidate_token,
        # and the client calls invalidate_token only after get_token has returned.
        self._lock = threading.Lock()

    def get_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        with self._lock:
            if self._is_token_valid():
                return self._token.access_token.get_secret_value()  # type: ignore

            if not self.settings.is_oauth_configured():
                raise AuthenticationError(
                    "OAuth not configured. Set ORG_ID, CLIENT_ID, SECRET and SCOPES as "
                    "environment variables or in a .env file."
                )

            token = self._get_oauth_token()

            # Refresh 5 minutes early, or at half the lifetime for a short-lived token.
            # A lifetime is capped at a day, so an odd value cannot overflow the date.
            lifetime = min(max(token.expires_in, 0), 86_400)
            margin = 300 if lifetime > 600 else lifetime // 2
            expiry = datetime.now(UTC) + timedelta(seconds=lifetime - margin)
            token.expires_at = expiry
            self._token = token
            self._token_expiry = expiry

            logger.debug("Token refreshed, expires at %s", expiry)
            return token.access_token.get_secret_value()

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

                if not isinstance(token_data, dict) or not token_data.get("access_token"):
                    raise AuthenticationError("IMS response had no access_token")
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
            status = e.response.status_code
            raise AuthenticationError(error_detail, transient=status == 429 or status >= 500) from e
        except httpx.RequestError as e:
            host = urlparse(token_url).hostname or token_url
            raise AuthenticationError(
                f"could not reach {host} ({type(e).__name__})", transient=True, network=True
            ) from e

    def _parse_oauth_error(self, e: httpx.HTTPStatusError) -> str:
        """Parse OAuth error response and return helpful message."""
        try:
            error_data = e.response.json()
            error_code = str(error_data.get("error", ""))[:100]
            error_desc = re.sub(
                r"client_secret=[^&\s]+",
                "client_secret=***",
                str(error_data.get("error_description", "")),
            )[:200]

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
                return "401 Unauthorized: Check that credentials are current and not regenerated."
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
        with self._lock:
            self._token = None
            self._token_expiry = None
        logger.debug("Token invalidated")
