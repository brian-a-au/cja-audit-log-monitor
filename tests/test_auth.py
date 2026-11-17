"""Tests for authentication module."""

import pytest
from pytest_httpx import HTTPXMock

from cja_audit_log_monitor.auth import AuthenticationError, TokenManager
from cja_audit_log_monitor.config import CJASettings

pytestmark = pytest.mark.httpx_mock(can_send_already_matched_responses=True)


class TestTokenManager:
    """Tests for TokenManager class."""

    def test_get_oauth_token(
        self,
        sample_settings: CJASettings,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test OAuth token acquisition."""
        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            json={
                "access_token": "test_access_token",
                "token_type": "bearer",
                "expires_in": 86400,
            },
        )

        token_manager = TokenManager(sample_settings)
        token = token_manager.get_token()

        assert token == "test_access_token"

    def test_token_caching(
        self,
        sample_settings: CJASettings,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test that tokens are cached and reused."""
        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            json={
                "access_token": "test_token",
                "token_type": "bearer",
                "expires_in": 86400,
            },
        )

        token_manager = TokenManager(sample_settings)
        token1 = token_manager.get_token()
        token2 = token_manager.get_token()

        assert token1 == token2
        # Only one HTTP request should have been made
        assert len(httpx_mock.get_requests()) == 1

    def test_token_invalidation(
        self,
        sample_settings: CJASettings,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test token invalidation forces refresh."""
        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            json={
                "access_token": "token_1",
                "token_type": "bearer",
                "expires_in": 86400,
            },
        )
        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            json={
                "access_token": "token_2",
                "token_type": "bearer",
                "expires_in": 86400,
            },
        )

        token_manager = TokenManager(sample_settings)
        token1 = token_manager.get_token()
        token_manager.invalidate_token()
        token2 = token_manager.get_token()

        assert token1 == "token_1"
        assert token2 == "token_2"

    def test_oauth_error_handling(
        self,
        sample_settings: CJASettings,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test OAuth error is properly raised with helpful message."""
        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            status_code=401,
            json={"error": "invalid_client"},
        )

        token_manager = TokenManager(sample_settings)
        with pytest.raises(AuthenticationError) as exc_info:
            token_manager.get_token()

        assert "invalid_client" in str(exc_info.value)

    def test_no_credentials_error(self) -> None:
        """Test error when no credentials configured."""
        # Explicitly create settings with empty credentials (bypass .env loading)
        settings = CJASettings(
            client_id="",
            secret="",
            org_id="",
            _env_file=None,  # Disable .env loading for this test
        )
        token_manager = TokenManager(settings)

        with pytest.raises(AuthenticationError) as exc_info:
            token_manager.get_token()

        assert "OAuth not configured" in str(exc_info.value)

    def test_get_auth_headers(
        self,
        sample_settings: CJASettings,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test auth headers generation."""
        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            json={
                "access_token": "test_token",
                "token_type": "bearer",
                "expires_in": 86400,
            },
        )

        token_manager = TokenManager(sample_settings)
        headers = token_manager.get_auth_headers()

        assert headers["Authorization"] == "Bearer test_token"
        assert headers["x-api-key"] == sample_settings.client_id
        assert headers["x-gw-ims-org-id"] == sample_settings.org_id

    def test_is_token_valid_no_token(self, sample_settings: CJASettings) -> None:
        """Test _is_token_valid returns False when no token."""
        token_manager = TokenManager(sample_settings)
        assert token_manager._is_token_valid() is False
