"""Tests for API client."""

import threading
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cja_audit_log_monitor.auth import TokenManager
from cja_audit_log_monitor.client import APIError, AuditLogsClient, _retry_delay
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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test that rate limiting triggers retry."""
        sleeps: list[float] = []
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", sleeps.append)
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
        assert sleeps == [1]

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


class TestGetLogsSample:
    """get_logs_sample returns up to N entries plus the API's true total."""

    @staticmethod
    def _page(n: int, start: int, total: int, last: bool) -> dict:
        return {
            "content": [{"id": f"e{start + i}"} for i in range(n)],
            "totalElements": total,
            "last": last,
        }

    def test_returns_entries_and_true_total(self, client, httpx_mock) -> None:
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json=self._page(1000, 0, 28775, last=False),
        )
        with client:
            entries, total = client.get_logs_sample(max_entries=1000)
        assert len(entries) == 1000
        assert total == 28775

    def test_uses_largest_page_size(self, client, httpx_mock) -> None:
        import re

        url = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*")
        for start in (0, 1000, 2000):
            httpx_mock.add_response(url=url, json=self._page(1000, start, 5000, last=False))
        with client:
            entries, total = client.get_logs_sample(max_entries=3000)
        requests = [r for r in httpx_mock.get_requests() if "auditlogs" in str(r.url)]
        assert len(requests) == 3
        assert all("pageSize=1000" in str(r.url) for r in requests)
        assert len(entries) == 3000
        assert total == 5000

    def test_stops_when_a_page_adds_nothing_new(self, client, httpx_mock) -> None:
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json=self._page(10, 0, 5000, last=False),
            is_reusable=True,
        )
        with client:
            entries, _ = client.get_logs_sample(max_entries=3000)
            paged = list(client.get_logs_paginated())
        assert len(entries) == 10
        assert len(paged) == 10

    def test_small_result_stops_at_last_page(self, client, httpx_mock) -> None:
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json=self._page(3, 0, 3, last=True),
        )
        with client:
            entries, total = client.get_logs_sample(max_entries=1000)
        assert len(entries) == 3
        assert total == 3

    def test_does_not_change_callers_query(self, client, httpx_mock) -> None:
        import re

        from cja_audit_log_monitor.models import AuditLogQuery

        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json=self._page(3, 0, 3, last=True),
        )
        query = AuditLogQuery(page_size=50)
        with client:
            client.get_logs_sample(query, max_entries=1000)
        assert query.page_size == 50
        assert query.page == 0


class TestPagingStops:
    """Paging must end even if the API never reports a last page."""

    def test_paginated_stops_at_total_pages(self, client, httpx_mock) -> None:
        import re

        url = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*")
        for entry_id in ("a", "b"):
            httpx_mock.add_response(
                url=url,
                json={
                    "content": [{"id": entry_id}],
                    "totalElements": 2,
                    "totalPages": 2,
                    "last": False,
                },
            )
        with client:
            entries = list(client.get_logs_paginated())
        assert len(entries) == 2

    def test_paginated_requests_page_number(self, client, httpx_mock) -> None:
        import re

        url = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*")
        for entry_id in ("a", "b"):
            httpx_mock.add_response(
                url=url,
                json={
                    "content": [{"id": entry_id}],
                    "totalElements": 2,
                    "totalPages": 2,
                    "last": False,
                },
            )
        with client:
            list(client.get_logs_paginated())
        urls = [str(r.url) for r in httpx_mock.get_requests() if "auditlogs" in str(r.url)]
        assert "pageNumber=0" in urls[0] and "pageNumber=1" in urls[1]

    def test_sample_stops_at_total_pages(self, client, httpx_mock) -> None:
        import re

        url = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*")
        for entry_id in ("a", "b"):
            httpx_mock.add_response(
                url=url,
                json={
                    "content": [{"id": entry_id}],
                    "totalElements": 2,
                    "totalPages": 2,
                    "last": False,
                },
            )
        with client:
            entries, total = client.get_logs_sample(max_entries=1000)
        assert len(entries) == 2
        assert total == 2


class TestPagingDedup:
    """Entries repeated across a page boundary (new events arriving) are dropped."""

    def test_sample_drops_repeated_ids(self, client, httpx_mock) -> None:
        import re

        url = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*")
        httpx_mock.add_response(
            url=url,
            json={
                "content": [{"id": "a"}, {"id": "b"}],
                "totalElements": 4,
                "totalPages": 2,
                "last": False,
            },
        )
        httpx_mock.add_response(
            url=url,
            json={"content": [{"id": "b"}, {"id": "c"}], "totalElements": 4, "totalPages": 2},
        )
        with client:
            entries, _ = client.get_logs_sample(max_entries=2000)
        assert [e.id for e in entries] == ["a", "b", "c"]

    def test_paginated_drops_repeated_ids(self, client, httpx_mock) -> None:
        import re

        url = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*")
        httpx_mock.add_response(
            url=url,
            json={
                "content": [{"id": "a"}, {"id": "b"}],
                "totalElements": 4,
                "totalPages": 2,
                "last": False,
            },
        )
        httpx_mock.add_response(
            url=url,
            json={"content": [{"id": "b"}, {"id": "c"}], "totalElements": 4, "totalPages": 2},
        )
        with client:
            entries = list(client.get_logs_paginated())
        assert [e.id for e in entries] == ["a", "b", "c"]


class TestGetAllLogsPageSize:
    """get_all_logs asks for the largest page the API allows."""

    @staticmethod
    def _mock(httpx_mock):
        import re

        httpx_mock.add_response(
            url=re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"),
            json={"content": [{"id": "a"}], "totalElements": 1, "totalPages": 1, "last": True},
        )

    def _page_sizes(self, httpx_mock):
        return [
            str(r.url).split("pageSize=")[1].split("&")[0]
            for r in httpx_mock.get_requests()
            if "auditlogs" in str(r.url)
        ]

    def test_no_limit_uses_1000(self, client, httpx_mock) -> None:
        self._mock(httpx_mock)
        with client:
            client.get_all_logs()
        assert self._page_sizes(httpx_mock) == ["1000"]

    def test_small_limit_uses_the_limit(self, client, httpx_mock) -> None:
        self._mock(httpx_mock)
        with client:
            client.get_all_logs(max_entries=20)
        assert self._page_sizes(httpx_mock) == ["20"]

    def test_does_not_change_callers_query(self, client, httpx_mock) -> None:
        from cja_audit_log_monitor.models import AuditLogQuery

        self._mock(httpx_mock)
        query = AuditLogQuery(page_size=50)
        with client:
            client.get_all_logs(query)
        assert query.page_size == 50


@pytest.mark.parametrize(
    "header,attempt,expected",
    [
        ("5", 0, 5.0),
        ("1.5", 0, 1.5),
        ("3600", 0, 60.0),
        ("-3", 0, 0.0),
        (None, 2, 4.0),
        ("garbage", 1, 2.0),
    ],
)
def test_retry_delay(header, attempt, expected) -> None:
    assert _retry_delay(header, attempt) == expected


def test_retry_delay_http_date() -> None:
    when = format_datetime(datetime.now(UTC) + timedelta(seconds=10), usegmt=True)
    assert 0 < _retry_delay(when, 0) <= 10


class TestResilience:
    URL = "https://cja.adobe.io/auditlogs/api/v1/auditlogs"

    @staticmethod
    def _api_requests(httpx_mock):
        return [r for r in httpx_mock.get_requests() if "auditlogs" in str(r.url)]

    def test_retries_503_then_succeeds(
        self, client, sample_api_response, httpx_mock, monkeypatch
    ) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", sleeps.append)
        httpx_mock.add_response(url=self.URL, status_code=503)
        httpx_mock.add_response(url=self.URL, json=sample_api_response)
        with client:
            assert client.get_logs() is not None
        assert len(self._api_requests(httpx_mock)) == 2
        assert sleeps == [1.0]

    def test_persistent_503_raises_api_error(self, client, httpx_mock, monkeypatch) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_response(url=self.URL, status_code=503)
        with client, pytest.raises(APIError) as info:
            client.get_logs()
        assert info.value.status_code == 503
        assert len(self._api_requests(httpx_mock)) == 3

    def test_non_json_body_raises_api_error(self, client, httpx_mock, monkeypatch) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_response(url=self.URL, text="<html>gateway</html>")
        with client, pytest.raises(APIError) as info:
            client.get_logs()
        assert str(info.value).startswith("API returned a non-JSON response")


class TestThreadSafety:
    """The lazy HTTP client is created once even when threads race for it."""

    def test_concurrent_client_access_creates_one_client(
        self, sample_settings: CJASettings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A slow constructor widens the check-then-create window so threads overlap.
        real_client = httpx.Client

        class SlowClient(real_client):  # type: ignore[misc, valid-type]
            def __init__(self, *args, **kwargs) -> None:
                time.sleep(0.05)
                super().__init__(*args, **kwargs)

        monkeypatch.setattr("cja_audit_log_monitor.client.httpx.Client", SlowClient)
        api = AuditLogsClient(sample_settings, TokenManager(sample_settings))
        barrier = threading.Barrier(8)
        results: list[httpx.Client] = []

        def worker() -> None:
            barrier.wait()
            results.append(api.client)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(results) == 8
        assert len({id(c) for c in results}) == 1
        api.close()
