"""Tests for API client."""

import re
import threading
import time
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import patch

import httpx
import pytest
from pytest_httpx import HTTPXMock

from cja_audit_log_monitor.auth import TokenManager
from cja_audit_log_monitor.client import APIError, AuditLogsClient, RateLimitError, _retry_delay
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
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Test API error handling."""
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
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

    def test_non_dict_json_raises_api_error(self, client, httpx_mock, monkeypatch) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_response(url=self.URL, json=[])
        with client, pytest.raises(APIError) as info:
            client.get_logs()
        assert str(info.value).startswith("API returned an unexpected response")

    def test_null_json_raises_api_error(self, client, httpx_mock, monkeypatch) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_response(url=self.URL, text="null")
        with client, pytest.raises(APIError) as info:
            client.get_logs()
        assert str(info.value).startswith("API returned an unexpected response")

    def test_final_429_reports_clamped_retry_after(self, client, httpx_mock, monkeypatch) -> None:
        sleeps: list[float] = []
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", sleeps.append)
        httpx_mock.add_response(url=self.URL, status_code=429, headers={"Retry-After": "3600"})
        with client, pytest.raises(RateLimitError) as info:
            client.get_logs()
        assert sleeps == [60.0, 60.0]
        assert info.value.retry_after == 60

    def test_final_429_with_zero_retry_after_stays_zero(
        self, client, httpx_mock, monkeypatch
    ) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_response(url=self.URL, status_code=429, headers={"Retry-After": "0"})
        with client, pytest.raises(RateLimitError) as info:
            client.get_logs()
        assert info.value.retry_after == 0


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


class TestPagedQueryIsCopied:
    """Paging works on a copy of the caller's query and validates max_pages."""

    URL = r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs.*"

    def test_paginated_leaves_callers_query_alone(self, client, httpx_mock) -> None:
        import re

        url = re.compile(self.URL)
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
        query = AuditLogQuery(page_size=50)
        with client:
            assert len(list(client.get_logs_paginated(query))) == 2
        assert query.page == 0

    def test_stops_on_empty_page_without_last_key(self, client, httpx_mock) -> None:
        import re

        url = re.compile(self.URL)
        for content in ([{"id": "a"}], [{"id": "b"}], []):
            httpx_mock.add_response(url=url, json={"content": content, "totalPages": 5})
        with client:
            entries = list(client.get_logs_paginated())
        assert [e.id for e in entries] == ["a", "b"]


class TestRetryAndRefresh:
    """The retry paths that a long-running monitor depends on (G50)."""

    URL = "https://cja.adobe.io/auditlogs/api/v1/auditlogs"

    def test_401_refreshes_the_token_and_retries(
        self, client: AuditLogsClient, sample_api_response: dict, httpx_mock: HTTPXMock
    ) -> None:
        httpx_mock.add_response(url=self.URL, status_code=401, json={"error": "expired"})
        httpx_mock.add_response(url=self.URL, json=sample_api_response)
        with client:
            response = client.get_logs()
        assert len(response.content) == 1
        token_calls = [r for r in httpx_mock.get_requests() if "/ims/token" in str(r.url)]
        assert len(token_calls) == 2

    def test_network_error_is_retried(
        self,
        client: AuditLogsClient,
        sample_api_response: dict,
        httpx_mock: HTTPXMock,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_exception(httpx.ConnectError("down"), url=self.URL)
        httpx_mock.add_response(url=self.URL, json=sample_api_response)
        with client:
            response = client.get_logs()
        assert len(response.content) == 1

    def test_verify_connection_reports_a_failed_call(
        self, client: AuditLogsClient, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        httpx_mock.add_response(
            url=re.compile(re.escape(self.URL) + r"\?.*"), status_code=403,
            json={"error": "no access"},
        )
        with client:
            result = client.verify_connection()
        assert result["connected"] is False
        assert "403" in result["error"]


def test_401_after_429s_still_refreshes_the_token(
    client: AuditLogsClient,
    sample_api_response: dict,
    httpx_mock: HTTPXMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
    url = "https://cja.adobe.io/auditlogs/api/v1/auditlogs"
    httpx_mock.add_response(url=url, status_code=429)
    httpx_mock.add_response(url=url, status_code=429)
    httpx_mock.add_response(url=url, status_code=401)
    httpx_mock.add_response(url=url, json=sample_api_response)
    with client:
        response = client.get_logs()
    assert len(response.content) == 1


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
class TestClose:
    """After close() the client sends nothing more (G5, G46)."""

    def test_no_request_after_close(self, client: AuditLogsClient, httpx_mock: HTTPXMock) -> None:
        from cja_audit_log_monitor.client import ClientClosedError

        client.close()
        with pytest.raises(ClientClosedError):
            client.get_logs()
        api_calls = [r for r in httpx_mock.get_requests() if "/auditlogs" in str(r.url)]
        assert api_calls == []

    def test_close_during_send_is_a_clean_error(
        self, client: AuditLogsClient, httpx_mock: HTTPXMock
    ) -> None:
        from cja_audit_log_monitor.client import ClientClosedError

        http = client.client  # the lookup a worker thread did before close()
        http.close()

        def stale_lookup(self):
            return http

        with (
            patch.object(type(client), "client", property(stale_lookup)),
            pytest.raises(ClientClosedError),
        ):
            client.get_logs()

    def test_close_without_waiting_leaves_the_connection_to_the_last_request(
        self, client: AuditLogsClient
    ) -> None:
        from unittest.mock import MagicMock

        http = MagicMock()
        client._client = http
        client._in_flight = 1  # a worker thread is reading a response
        client.close(wait=False)
        http.close.assert_not_called()  # closing it would not wake the reader
        client._request_done()
        http.close.assert_called_once()

    def test_response_after_close_is_not_retried(
        self, client: AuditLogsClient, httpx_mock: HTTPXMock, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cja_audit_log_monitor.client import ClientClosedError

        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda s: None)
        url = "https://cja.adobe.io/auditlogs/api/v1/auditlogs"

        def close_then_fail(request):
            client.close(wait=False)
            return httpx.Response(503)

        httpx_mock.add_callback(close_then_fail, url=url)
        with pytest.raises(ClientClosedError):
            client.get_logs()
        api_calls = [r for r in httpx_mock.get_requests() if "/auditlogs" in str(r.url)]
        assert len(api_calls) == 1


class TestOddResponses:
    """Odd API answers are skipped or reported, never a traceback (G27, G46)."""

    URL = "https://cja.adobe.io/auditlogs/api/v1/auditlogs"

    @pytest.mark.parametrize(
        "bad", [{"id": 5, "action": "CREATE"}, {"id": "x", "dateCreated": "not a date"}, None],
        ids=["int-id", "bad-date", "null"],
    )
    def test_bad_entry_is_skipped(self, client, httpx_mock, caplog, bad) -> None:
        good = {"id": "good", "action": "CREATE", "dateCreated": "2026-01-01T00:00:00Z"}
        httpx_mock.add_response(url=self.URL, json={"content": [bad, good], "last": True})
        with client:
            response = client.get_logs()
        assert [e.id for e in response.content] == ["good"]
        assert "skipped 1 entry" in caplog.text

    def test_missing_content_is_an_api_error(self, client, httpx_mock) -> None:
        httpx_mock.add_response(url=self.URL, json={"error_code": "500"})
        with client, pytest.raises(APIError, match="unexpected response"):
            client.get_logs()

    def test_5xx_honors_retry_after(self, client, httpx_mock, monkeypatch, sample_api_response):
        sleeps: list[float] = []
        monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", sleeps.append)
        httpx_mock.add_response(url=self.URL, status_code=503, headers={"Retry-After": "7"})
        httpx_mock.add_response(url=self.URL, json=sample_api_response)
        with client:
            client.get_logs()
        assert sleeps == [7]

    def test_paging_continues_past_a_page_of_seen_ids(self, client, httpx_mock) -> None:
        def page(entries, number):
            return {"content": entries, "totalPages": 3, "number": number, "last": number == 2}

        a = {"id": "a", "action": "CREATE"}
        b = {"id": "b", "action": "CREATE"}
        for number, entries in enumerate([[a], [a], [b]]):
            httpx_mock.add_response(
                url=re.compile(re.escape(self.URL) + rf".*pageNumber={number}\b.*"),
                json=page(entries, number),
            )
        with client:
            ids = [e.id for e in client.get_logs_paginated(AuditLogQuery(page_size=1))]
        assert ids == ["a", "b"]


@pytest.mark.parametrize("size", [0, 1001])
def test_page_size_is_bounded(size) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        AuditLogQuery(page_size=size)
