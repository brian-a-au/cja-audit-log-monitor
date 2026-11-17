"""Tests for API client."""

import pytest
from pytest_httpx import HTTPXMock

from cja_audit_log_monitor.auth import TokenManager
from cja_audit_log_monitor.client import APIError, AuditLogsClient
from cja_audit_log_monitor.config import CJASettings
from cja_audit_log_monitor.models import AuditLogQuery

# Mark all tests to allow non-mocked requests (for token endpoint reuse)
pytestmark = pytest.mark.httpx_mock(can_send_already_matched_responses=True)


@pytest.fixture
def client(sample_settings: CJASettings, httpx_mock: HTTPXMock) -> AuditLogsClient:
    """Create a client with mocked auth."""
    # Mock token endpoint - allow multiple calls
    httpx_mock.add_response(
        url="https://ims-na1.adobelogin.com/ims/token/v3",
        json={
            "access_token": "test_token",
            "token_type": "bearer",
            "expires_in": 86400,
        },
    )

    token_manager = TokenManager(sample_settings)
    return AuditLogsClient(sample_settings, token_manager)


class TestAuditLogsClient:
    """Tests for AuditLogsClient."""

    def test_get_logs(
        self,
        client: AuditLogsClient,
        sample_api_response: dict,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test fetching audit logs."""
        httpx_mock.add_response(
            url="https://cja.adobe.io/auditlogs/api/v1/auditlogs",
            json=sample_api_response,
        )

        with client:
            response = client.get_logs()

        assert len(response.content) == 1
        assert response.content[0].id == "entry-1"

    def test_get_logs_with_query(
        self,
        client: AuditLogsClient,
        sample_api_response: dict,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test fetching logs with query parameters."""
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json=sample_api_response,
        )

        from cja_audit_log_monitor.models import ActionType

        query = AuditLogQuery(
            actions=[ActionType.CREATE],
            page_size=50,
        )

        with client:
            response = client.get_logs(query)

        assert response is not None

    def test_get_all_logs(
        self,
        client: AuditLogsClient,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test fetching all logs with pagination."""
        import re

        # Match any request to the audit logs endpoint
        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json={
                "content": [{"id": f"entry-{i}"} for i in range(3)],
                "first": True,
                "last": True,
                "totalElements": 3,
            },
        )

        with client:
            entries = client.get_all_logs(max_entries=10)

        assert len(entries) == 3

    def test_rate_limit_handling(
        self,
        client: AuditLogsClient,
        sample_api_response: dict,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test that rate limiting triggers retry."""
        # First request returns 429
        httpx_mock.add_response(
            url="https://cja.adobe.io/auditlogs/api/v1/auditlogs",
            status_code=429,
            headers={"Retry-After": "1"},
        )
        # Second request succeeds
        httpx_mock.add_response(
            url="https://cja.adobe.io/auditlogs/api/v1/auditlogs",
            json=sample_api_response,
        )

        with client:
            response = client.get_logs()

        assert response is not None
        assert len(httpx_mock.get_requests()) == 3  # Token + 2 API calls

    def test_api_error(
        self,
        client: AuditLogsClient,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test API error handling."""
        httpx_mock.add_response(
            url="https://cja.adobe.io/auditlogs/api/v1/auditlogs",
            status_code=500,
            json={"error": "Internal server error"},
        )

        with client:
            with pytest.raises(APIError) as exc_info:
                client.get_logs()

        assert exc_info.value.status_code == 500


class TestClientContextManager:
    """Tests for client context manager."""

    def test_context_manager(
        self,
        sample_settings: CJASettings,
        httpx_mock: HTTPXMock,
    ) -> None:
        """Test using client as context manager."""
        import re

        httpx_mock.add_response(
            url="https://ims-na1.adobelogin.com/ims/token/v3",
            json={
                "access_token": "test_token",
                "token_type": "bearer",
                "expires_in": 86400,
            },
        )
        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json={"content": [], "first": True, "last": True, "totalElements": 0},
        )

        token_manager = TokenManager(sample_settings)

        with AuditLogsClient(sample_settings, token_manager) as client:
            # Access the client property to initialize httpx client
            _ = client.get_logs()
            assert client._client is not None

        # Client should be closed after context
        assert client._client is None
