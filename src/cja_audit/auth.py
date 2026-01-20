"""Authentication handling for Adobe CJA API."""

import logging
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .config import CJASettings
from .models import TokenInfo

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


class TokenManager:
    """Manages OAuth/JWT tokens for Adobe CJA API."""

    def __init__(self, settings: CJASettings) -> None:
        self.settings = settings
        self._token: TokenInfo | None = None
        self._token_expiry: datetime | None = None

    def get_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if self._is_token_valid():
            return self._token.access_token  # type: ignore

        # Try OAuth first, fall back to JWT
        if self.settings.is_oauth_configured():
            self._token = self._get_oauth_token()
        elif self.settings.is_jwt_configured():
            self._token = self._get_jwt_token()
        else:
            raise AuthenticationError(
                "No authentication configured. Set CJA_CLIENT_ID, CJA_CLIENT_SECRET, "
                "and CJA_ORG_ID environment variables for OAuth authentication."
            )

        # Set expiry with 5 minute buffer
        self._token_expiry = datetime.now(UTC) + timedelta(
            seconds=self._token.expires_in - 300
        )
        self._token.expires_at = self._token_expiry

        logger.debug("Token refreshed, expires at %s", self._token_expiry)
        return self._token.access_token

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
            "client_secret": self.settings.client_secret,
            "scope": ",".join(self.settings.scopes_list),
        }

        logger.debug("Requesting OAuth token from %s", token_url)

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(token_url, data=data)
                response.raise_for_status()
                token_data = response.json()

                return TokenInfo(
                    access_token=token_data["access_token"],
                    token_type=token_data.get("token_type", "bearer"),
                    expires_in=token_data.get("expires_in", 86400),
                )
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text
            raise AuthenticationError(
                f"OAuth authentication failed: {e.response.status_code} - {error_detail}"
            ) from e
        except httpx.RequestError as e:
            raise AuthenticationError(f"OAuth request failed: {e}") from e

    def _get_jwt_token(self) -> TokenInfo:
        """Get token using JWT authentication (legacy)."""
        try:
            import jwt as pyjwt
        except ImportError:
            raise AuthenticationError(
                "PyJWT package required for JWT authentication. Install with: pip install PyJWT"
            )

        # Read private key
        key_path = Path(self.settings.private_key_path)
        if not key_path.exists():
            raise AuthenticationError(f"Private key file not found: {key_path}")

        with open(key_path) as f:
            private_key = f.read()

        # Build JWT claims
        now = int(time.time())
        expiry = now + 86400  # 24 hours

        claims = {
            "exp": expiry,
            "iss": self.settings.org_id,
            "sub": self.settings.tech_account_id,
            "aud": f"{self.settings.ims_base_url}/c/{self.settings.client_id}",
            f"{self.settings.ims_base_url}/s/ent_cja_sdk": True,
        }

        # Sign JWT
        jwt_token = pyjwt.encode(claims, private_key, algorithm="RS256")

        # Exchange JWT for access token
        exchange_url = f"{self.settings.ims_base_url}/ims/exchange/jwt"

        data = {
            "client_id": self.settings.client_id,
            "client_secret": self.settings.client_secret,
            "jwt_token": jwt_token,
        }

        logger.debug("Exchanging JWT token at %s", exchange_url)

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.post(exchange_url, data=data)
                response.raise_for_status()
                token_data = response.json()

                return TokenInfo(
                    access_token=token_data["access_token"],
                    token_type=token_data.get("token_type", "bearer"),
                    expires_in=token_data.get("expires_in", 86400),
                )
        except httpx.HTTPStatusError as e:
            error_detail = ""
            try:
                error_detail = e.response.json()
            except Exception:
                error_detail = e.response.text
            raise AuthenticationError(
                f"JWT exchange failed: {e.response.status_code} - {error_detail}"
            ) from e
        except httpx.RequestError as e:
            raise AuthenticationError(f"JWT exchange request failed: {e}") from e

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
