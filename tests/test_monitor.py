"""Tests for monitoring module."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from cja_audit_log_monitor.auth import AuthenticationError
from cja_audit_log_monitor.client import APIError
from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.monitor import POLL_OVERLAP, AuditLogMonitor, build_poll_query


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock audit logs client."""
    client = MagicMock()
    return client


@pytest.fixture
def monitor(mock_client: MagicMock) -> AuditLogMonitor:
    """Create a monitor instance with mock client."""
    return AuditLogMonitor(mock_client, interval=1)


class TestAuditLogMonitor:
    """Tests for AuditLogMonitor class."""

    def test_init(self, mock_client: MagicMock) -> None:
        """Test monitor initialization."""
        monitor = AuditLogMonitor(mock_client, interval=30)
        assert monitor.interval == 30
        assert monitor._running is False

    def test_init_default_interval(self, mock_client: MagicMock) -> None:
        """Test monitor initialization with default interval."""
        monitor = AuditLogMonitor(mock_client)
        assert monitor.interval == 60

    def test_get_new_entries_first_call(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test fetching entries on first call."""
        entries = [
            AuditLogEntry(
                id="entry-1",
                timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_client.get_logs.return_value = AuditLogResponse(content=entries, last=True)

        new_entries = monitor._get_new_entries()

        assert len(new_entries) == 1
        assert new_entries[0].id == "entry-1"

    def test_get_new_entries_filters_seen(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test that previously seen entries are filtered."""
        entries = [
            AuditLogEntry(
                id="entry-2",
                timestamp=datetime(2024, 1, 15, 10, 1, 0, tzinfo=UTC),
            ),
            AuditLogEntry(
                id="entry-1",
                timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_client.get_logs.return_value = AuditLogResponse(content=entries)

        # First call - see both entries
        monitor._get_new_entries()

        # Second call - same entries, should return empty
        new_entries = monitor._get_new_entries()
        assert len(new_entries) == 0

    def test_get_new_entries_empty_response(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test handling of empty response."""
        mock_client.get_logs.return_value = AuditLogResponse(content=[])

        new_entries = monitor._get_new_entries()
        assert new_entries == []

    def test_set_callback(self, monitor: AuditLogMonitor) -> None:
        """Test setting entry callback."""
        callback = MagicMock()
        monitor.set_callback(callback)
        assert monitor._on_new_entry == callback

    def test_stop(self, monitor: AuditLogMonitor) -> None:
        """Test stopping the monitor."""
        monitor._running = True
        monitor.stop()
        assert monitor._running is False

    def test_handle_entry_calls_callback(
        self,
        monitor: AuditLogMonitor,
    ) -> None:
        """Test that _handle_entry calls the callback."""
        callback = MagicMock()
        monitor.set_callback(callback)

        entry = AuditLogEntry(id="test-entry", action="CREATE")
        monitor._handle_entry(entry)

        callback.assert_called_once_with(entry)

    def test_handle_entry_without_callback(
        self,
        monitor: AuditLogMonitor,
    ) -> None:
        """Test _handle_entry works without callback."""
        entry = AuditLogEntry(id="test-entry", action="CREATE")
        # Should not raise
        monitor._handle_entry(entry)

    def test_get_new_entries_handles_exception(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test that exceptions are handled gracefully."""
        mock_client.get_logs.side_effect = Exception("Network error")

        # Should return empty list, not raise
        new_entries = monitor._get_new_entries()
        assert new_entries == []

    def test_get_new_entries_fetches_multiple_pages(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test monitor polling paginates to avoid missing burst events."""
        monitor._last_poll_time = datetime.now(UTC)  # past the first poll, which reads one page
        pages_requested: list[int] = []
        responses = [
            AuditLogResponse(
                content=[
                    AuditLogEntry(
                        id="entry-3",
                        timestamp=datetime(2024, 1, 15, 10, 2, 0, tzinfo=UTC),
                    ),
                    AuditLogEntry(
                        id="entry-2",
                        timestamp=datetime(2024, 1, 15, 10, 1, 0, tzinfo=UTC),
                    ),
                ],
                last=False,
            ),
            AuditLogResponse(
                content=[
                    AuditLogEntry(
                        id="entry-1",
                        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                    )
                ],
                last=True,
            ),
        ]

        def get_logs_side_effect(query):
            pages_requested.append(query.page)
            return responses.pop(0)

        mock_client.get_logs.side_effect = get_logs_side_effect

        new_entries = monitor._get_new_entries()

        assert pages_requested == [0, 1]
        assert [entry.id for entry in new_entries] == ["entry-1", "entry-2", "entry-3"]

    def test_handle_entry_dispatches_to_notification_manager(
        self, sample_audit_entry
    ) -> None:
        """AuditLogMonitor._handle_entry calls notify_alert for each FiredAlert."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.pop_first_failure.return_value = None

        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )

        monitor._handle_entry(sample_audit_entry)
        fake_nm.notify_alert.assert_called_once_with("r", "m", sample_audit_entry)

    def test_handle_entry_works_without_notification_manager(
        self, sample_audit_entry
    ) -> None:
        """AuditLogMonitor._handle_entry behavior unchanged when notification_manager is None."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        client = MagicMock()
        monitor = AuditLogMonitor(client=client, alert_engine=fake_engine)
        monitor._handle_entry(sample_audit_entry)  # must not raise

    def test_handle_entry_suppresses_dispatch_exceptions(
        self, sample_audit_entry
    ) -> None:
        """An exception inside notify_alert does NOT prevent _handle_entry from completing."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.notify_alert.side_effect = RuntimeError("boom")
        fake_nm.pop_first_failure.return_value = None
        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )
        # Must not raise
        monitor._handle_entry(sample_audit_entry)

    def test_handle_entry_prints_pop_first_failure_warning(self, sample_audit_entry) -> None:
        """When pop_first_failure returns a string, console.print emits a yellow-tagged warning."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.pop_first_failure.return_value = (
            "Notification delivery failed (slack);"
            " subsequent failures suppressed for this session — check logs."
        )

        fake_console = MagicMock()
        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            console=fake_console,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )

        monitor._handle_entry(sample_audit_entry)

        # Expect console.print called with a [yellow]...[/yellow] formatted warning
        warning_calls = [c for c in fake_console.print.call_args_list if "yellow" in str(c)]
        assert warning_calls, "Expected console.print to emit a yellow-tagged warning"


class TestBuildPollQuery:
    """build_poll_query overlaps the last poll and always bounds both dates."""

    def test_with_since(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        since = now - timedelta(minutes=1)
        query = build_poll_query(since, now, 100)
        assert query.start_date == since - POLL_OVERLAP
        assert query.end_date == now
        assert query.page == 0
        assert query.page_size == 100

    def test_without_since(self):
        now = datetime(2026, 1, 1, 12, 0, tzinfo=UTC)
        query = build_poll_query(None, now, 50)
        assert query.start_date == now - POLL_OVERLAP
        assert query.page_size == 50


T0 = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)


def _entry(entry_id: str, minutes: float = 0, **kwargs) -> AuditLogEntry:
    return AuditLogEntry(id=entry_id, timestamp=T0 + timedelta(minutes=minutes), **kwargs)


def _scripted(mock_client: MagicMock, responses: list) -> list:
    """Make get_logs return ``responses`` in order; return the list of queries seen."""
    queries: list = []

    def side_effect(query):
        queries.append(query.model_copy())
        return responses.pop(0)

    mock_client.get_logs.side_effect = side_effect
    return queries


class TestPollDedupe:
    """Polling dedupes by id inside an overlap window instead of by timestamp."""

    def test_first_poll_reads_one_page_and_marks_it_seen(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        queries = _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)], last=False),
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)], last=False),
            ],
        )
        first = monitor._get_new_entries()
        assert len(queries) == 1
        assert [e.id for e in first] == ["a", "b"]
        assert monitor._get_new_entries() == []

    def test_same_timestamp_new_id_is_returned(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("a", 1)], last=True),
                AuditLogResponse(content=[_entry("b", 1), _entry("a", 1)], last=True),
            ],
        )
        monitor._get_new_entries()
        assert [e.id for e in monitor._get_new_entries()] == ["b"]

    def test_late_indexed_older_entry_is_returned(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("a", 10)], last=True),
                AuditLogResponse(content=[_entry("a", 10), _entry("late", 8)], last=True),
            ],
        )
        monitor._get_new_entries()
        assert [e.id for e in monitor._get_new_entries()] == ["late"]

    def test_every_query_has_both_dates(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        queries = _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("a")], last=True),
                AuditLogResponse(content=[_entry("a")], last=True),
            ],
        )
        monitor._get_new_entries()
        monitor._get_new_entries()
        assert all(q.start_date is not None and q.end_date is not None for q in queries)

    def test_stops_paging_when_last_is_missing(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        """The API may omit `last`; paging must stop at a page with nothing new."""
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("a", 1)]),
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)]),
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)]),
                AuditLogResponse(content=[]),
            ],
        )
        monitor._get_new_entries()
        calls_before = mock_client.get_logs.call_count
        new = monitor._get_new_entries()
        assert [e.id for e in new] == ["b"]
        # page 0 has a new entry, page 1 has nothing new, so it stops there.
        assert mock_client.get_logs.call_count - calls_before == 2

    def test_entry_filter_applies_but_entries_still_marked_seen(
        self, mock_client: MagicMock
    ) -> None:
        monitor = AuditLogMonitor(
            mock_client, interval=1, entry_filter=lambda e: e.action == "DELETE"
        )
        _scripted(
            mock_client,
            [
                AuditLogResponse(
                    content=[_entry("b", 2, action="DELETE"), _entry("a", 1, action="CREATE")],
                    last=True,
                ),
            ],
        )
        assert [e.id for e in monitor._get_new_entries()] == ["b"]
        assert len(monitor._seen) == 2


class TestPollErrors:
    @pytest.fixture(autouse=True)
    def _no_sleep(self):
        ticks = iter(range(10_000))
        with (
            patch("cja_audit_log_monitor.monitor.time.sleep"),
            patch("cja_audit_log_monitor.monitor.time.monotonic", side_effect=lambda: next(ticks)),
        ):
            yield

    @pytest.mark.parametrize("status", [400, 401, 403, 404])
    def test_fatal_status_raises_from_start(self, mock_client: MagicMock, status: int) -> None:
        mock_client.get_logs.side_effect = APIError("x", status_code=status)
        monitor = AuditLogMonitor(mock_client, interval=1)
        with pytest.raises(APIError):
            monitor.start(duration=5)

    def test_authentication_error_raises_from_start(self, mock_client: MagicMock) -> None:
        mock_client.get_logs.side_effect = AuthenticationError("bad")
        monitor = AuditLogMonitor(mock_client, interval=1)
        with pytest.raises(AuthenticationError):
            monitor.start(duration=5)

    def test_transient_status_is_logged_and_loop_continues(
        self, mock_client: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        mock_client.get_logs.side_effect = APIError("down", status_code=503)
        monitor = AuditLogMonitor(mock_client, interval=1)
        monitor.start(duration=5)
        assert mock_client.get_logs.call_count > 1
        assert "down" in caplog.text

    def test_stopping_message_prints_once(self, mock_client: MagicMock) -> None:
        console = MagicMock()
        monitor = AuditLogMonitor(mock_client, console=console, interval=1)
        monitor._signal_handler(2, None)
        monitor._signal_handler(15, None)
        stops = [c for c in console.print.call_args_list if "Stopping monitor" in str(c)]
        assert len(stops) == 1
