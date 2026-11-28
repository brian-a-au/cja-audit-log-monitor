"""Authentication handling for Adobe CJA API."""

import logging
import re
import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import quote, quote_plus, urlparse

import httpx

from .config import CJASettings
from .credentials import NO_CREDENTIAL
from .models import TokenInfo

logger = logging.getLogger(__name__)

# The shortest time, in seconds, a token is kept, so a lifetime of 0 does not cost an IMS
# call per request. A token that really expires sooner gets a 401, and the client then
# fetches a new one.
MIN_TOKEN_KEEP = 60


class AuthenticationError(Exception):
    """Raised when authentication fails.

    ``transient`` is True when trying again later may work: a network error, or IMS
    answering 429 or 5xx. Bad or missing credentials are not transient.

    ``code`` is the sign-in code of the Adobe credentials standard that fits the failure.
    ``detail`` is Adobe's own message, cut to 200 characters and with any secret removed.
    """

    def __init__(
        self,
        message: str,
        transient: bool = False,
        network: bool = False,
        code: str = "sign_in_failed",
        detail: str = "",
    ) -> None:
        super().__init__(message)
        self.transient = transient
        # True when IMS could not be reached at all (DNS, refused, timed out).
        self.network = network
        self.code = code
        self.detail = detail or message[:200]


def _redact(text: str, secret: str = "") -> str:
    """``text`` without a client secret, cut to 200 characters.

    ``secret`` is the secret that was sent. It is removed wherever the answer repeats it,
    as it is and in the form a request body holds it.
    """
    text = re.sub(r"client_secret=[^&\s]+", "client_secret=***", text)
    for form in {secret, quote_plus(secret), quote(secret, safe="")} - {""}:
        text = text.replace(form, "***")
    return text[:200]


def sign_in_code(error_code: str, description: str) -> str:
    """The standard's code for an IMS error answer. Only codes the tool can tell apart."""
    if error_code == "invalid_client":
        return "bad_secret" if "secret" in description.lower() else "bad_client_id"
    if error_code == "invalid_scope":
        return "scopes_rejected"
    return "sign_in_failed"


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
                raise AuthenticationError(f"OAuth not configured. {NO_CREDENTIAL}")

            token = self._get_oauth_token()

            # Refresh 5 minutes early, or at half the lifetime for a short-lived token.
            # A lifetime is capped at a day, so an odd value cannot overflow the date.
            lifetime = min(max(token.expires_in, 0), 86_400)
            margin = 300 if lifetime > 600 else lifetime // 2
            keep = max(lifetime - margin, MIN_TOKEN_KEEP)
            expiry = datetime.now(UTC) + timedelta(seconds=keep)
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
                    raise AuthenticationError(
                        "IMS returned a non-JSON response", code="unreachable"
                    ) from None

                # A 200 answer without a token did not come from Adobe's sign-in service.
                if not isinstance(token_data, dict) or not token_data.get("access_token"):
                    raise AuthenticationError(
                        "IMS response had no access_token", code="unreachable"
                    )
                try:
                    expires_in = int(token_data.get("expires_in", 86400))
                except (ValueError, TypeError, OverflowError):
                    raise AuthenticationError("IMS response had an unreadable expires_in") from None
                try:
                    return TokenInfo(
                        access_token=token_data["access_token"],
                        token_type=token_data.get("token_type", "bearer"),
                        expires_in=expires_in,
                    )
                except (KeyError, ValueError, TypeError, AttributeError):
                    raise AuthenticationError("IMS response had no access_token") from None
        except httpx.HTTPStatusError as e:
            error_detail, code, detail = self._parse_oauth_error(e)
            status = e.response.status_code
            raise AuthenticationError(
                error_detail,
                transient=status == 429 or status >= 500,
                code=code,
                detail=detail,
            ) from e
        except httpx.RequestError as e:
            host = urlparse(token_url).hostname or token_url
            raise AuthenticationError(
                f"could not reach {host} ({type(e).__name__})",
                transient=True,
                network=True,
                code="unreachable",
            ) from e

    def _parse_oauth_error(self, e: httpx.HTTPStatusError) -> tuple[str, str, str]:
        """Parse an OAuth error answer: a helpful message, the code, and Adobe's own text."""
        secret = self.settings.secret.get_secret_value()
        try:
            error_data = e.response.json()
            raw_code = str(error_data.get("error", ""))
            raw_desc = str(error_data.get("error_description", ""))
            # The code is found from Adobe's own text, before any of it is removed.
            code = sign_in_code(raw_code, raw_desc)
            error_code = _redact(raw_code, secret)[:100]
            error_desc = _redact(raw_desc, secret)
        except Exception:
            status = e.response.status_code
            body = _redact(e.response.text, secret)
            if status == 401:
                text = "401 Unauthorized: Check that credentials are current and not regenerated."
            elif status == 403:
                text = (
                    "403 Forbidden: Ensure both CJA API and Experience Platform API are added "
                    "to your project in Developer Console, and service account is assigned "
                    "to product profiles in Admin Console."
                )
            else:
                text = f"OAuth authentication failed: {status} - {body}"
            return text, "sign_in_failed", body or f"HTTP {status}"

        if raw_code == "invalid_client":
            text = (
                f"invalid_client: {error_desc}\n"
                "Check that CLIENT_ID and SECRET are correct and not expired. "
                "Re-retrieve credentials from Adobe Developer Console."
            )
        elif raw_code == "invalid_scope":
            text = (
                f"invalid_scope: {error_desc}\n"
                "Copy SCOPES exactly from Developer Console > OAuth Server-to-Server > Scopes."
            )
        elif raw_code == "unauthorized_client":
            text = (
                f"unauthorized_client: {error_desc}\n"
                "Ensure OAuth Server-to-Server is enabled in Developer Console."
            )
        else:
            text = f"OAuth error ({e.response.status_code}): {error_code} - {error_desc}"
        detail = error_desc or error_code or f"HTTP {e.response.status_code}"
        return text, code, detail

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
