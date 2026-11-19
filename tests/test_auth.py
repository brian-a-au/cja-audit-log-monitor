"""Tests for authentication module."""

import re
import threading
import time

import httpx
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


def test_token_response_without_access_token(httpx_mock: HTTPXMock, sample_settings) -> None:
    httpx_mock.add_response(url=re.compile(".*/ims/token/v3"), json={"error": "weird"})
    with pytest.raises(AuthenticationError, match="access_token"):
        TokenManager(sample_settings).get_token()


def test_oauth_error_body_redacted(httpx_mock: HTTPXMock, sample_settings) -> None:
    httpx_mock.add_response(
        url=re.compile(".*/ims/token/v3"),
        status_code=400,
        text="bad request client_secret=TOPSECRET&x=1",
    )
    with pytest.raises(AuthenticationError) as info:
        TokenManager(sample_settings).get_token()
    assert "TOPSECRET" not in str(info.value)


def test_token_info_repr_hides_token() -> None:
    from cja_audit_log_monitor.models import TokenInfo

    info = TokenInfo(access_token="TOKSENTINEL", expires_in=10)
    assert "TOKSENTINEL" not in repr(info)


def test_token_response_not_json(httpx_mock: HTTPXMock, sample_settings) -> None:
    httpx_mock.add_response(url=re.compile(".*/ims/token/v3"), text="<html>oops</html>")
    with pytest.raises(AuthenticationError, match="non-JSON"):
        TokenManager(sample_settings).get_token()


class TestTokenManagerThreads:
    """Concurrent callers share one token request."""

    def test_concurrent_get_token_makes_one_request(
        self, sample_settings: CJASettings, httpx_mock: HTTPXMock
    ) -> None:
        def slow_token(request: httpx.Request) -> httpx.Response:
            time.sleep(0.1)  # keep the request in flight so the other threads pile up
            return httpx.Response(
                200,
                json={"access_token": "shared", "token_type": "bearer", "expires_in": 86400},
            )

        httpx_mock.add_callback(
            slow_token,
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            is_reusable=True,
        )
        manager = TokenManager(sample_settings)
        barrier = threading.Barrier(8)
        tokens: list[str] = []

        def worker() -> None:
            barrier.wait()
            tokens.append(manager.get_token())

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tokens == ["shared"] * 8
        assert len(httpx_mock.get_requests()) == 1


class TestTokenLifecycle:
    """Expiry and the token request itself (G50)."""

    IMS = "https://ims-na1.adobelogin.com/ims/token/v3"

    def test_expired_token_is_fetched_again(
        self, sample_settings: CJASettings, httpx_mock: HTTPXMock
    ) -> None:
        from datetime import UTC, datetime, timedelta

        httpx_mock.add_response(url=self.IMS, json={"access_token": "a", "expires_in": 86400})
        httpx_mock.add_response(url=self.IMS, json={"access_token": "b", "expires_in": 86400})
        manager = TokenManager(sample_settings)
        assert manager.get_token() == "a"
        manager._token_expiry = datetime.now(UTC) - timedelta(seconds=1)
        assert manager.get_token() == "b"

    def test_token_request_sends_the_credentials(
        self, sample_settings: CJASettings, httpx_mock: HTTPXMock
    ) -> None:
        from urllib.parse import parse_qs

        httpx_mock.add_response(url=self.IMS, json={"access_token": "a", "expires_in": 86400})
        TokenManager(sample_settings).get_token()
        body = parse_qs(httpx_mock.get_requests()[0].content.decode())
        assert body["grant_type"] == ["client_credentials"]
        assert body["client_id"] == [sample_settings.client_id]
        assert body["client_secret"] == [sample_settings.secret.get_secret_value()]
        assert body["scope"] == [",".join(sample_settings.scopes_list)]


class TestTransientFailures:
    """IMS outages and network errors are marked transient; bad credentials are not (G2)."""

    IMS = "https://ims-na1.adobelogin.com/ims/token/v3"

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_ims_server_error_is_transient(
        self, sample_settings: CJASettings, httpx_mock: HTTPXMock, status: int
    ) -> None:
        httpx_mock.add_response(url=self.IMS, status_code=status, text="busy")
        with pytest.raises(AuthenticationError) as info:
            TokenManager(sample_settings).get_token()
        assert info.value.transient is True

    def test_network_error_is_transient(
        self, sample_settings: CJASettings, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_exception(httpx.ConnectError("dns"), url=self.IMS)
        with pytest.raises(AuthenticationError) as info:
            TokenManager(sample_settings).get_token()
        assert info.value.transient is True

    @pytest.mark.parametrize("status", [400, 401])
    def test_bad_credentials_are_not_transient(
        self, sample_settings: CJASettings, httpx_mock: HTTPXMock, status: int
    ) -> None:
        httpx_mock.add_response(url=self.IMS, status_code=status, json={"error": "invalid_client"})
        with pytest.raises(AuthenticationError) as info:
            TokenManager(sample_settings).get_token()
        assert info.value.transient is False

    def test_missing_credentials_are_not_transient(self) -> None:
        with pytest.raises(AuthenticationError) as info:
            TokenManager(CJASettings(_env_file=None)).get_token()
        assert info.value.transient is False


class TestTokenEdges:
    IMS = "https://ims-na1.adobelogin.com/ims/token/v3"

    def test_short_lived_token_is_reused(self, sample_settings, httpx_mock) -> None:
        httpx_mock.add_response(url=self.IMS, json={"access_token": "a", "expires_in": 200})
        manager = TokenManager(sample_settings)
        manager.get_token()
        manager.get_token()
        assert len(httpx_mock.get_requests()) == 1

    def test_huge_expires_in_does_not_raise(self, sample_settings, httpx_mock) -> None:
        httpx_mock.add_response(
            url=self.IMS, json={"access_token": "a", "expires_in": 10**20}
        )
        assert TokenManager(sample_settings).get_token() == "a"

    def test_empty_token_is_an_error(self, sample_settings, httpx_mock) -> None:
        httpx_mock.add_response(url=self.IMS, json={"access_token": "", "expires_in": 100})
        with pytest.raises(AuthenticationError):
            TokenManager(sample_settings).get_token()

    def test_ims_error_description_is_cut_and_redacted(self, sample_settings, httpx_mock):
        description = "client_secret=TOPSECRET " + "x" * 1000
        httpx_mock.add_response(
            url=self.IMS, status_code=400,
            json={"error": "invalid_request", "error_description": description},
        )
        with pytest.raises(AuthenticationError) as info:
            TokenManager(sample_settings).get_token()
        assert "TOPSECRET" not in str(info.value)
        assert len(str(info.value)) < 400
