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
        fake_err_console = MagicMock()
        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            console=fake_console,
            err_console=fake_err_console,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )

        monitor._handle_entry(sample_audit_entry)

        # The warning goes to the error console, never to the entries console.
        warning_calls = [c for c in fake_err_console.print.call_args_list if "yellow" in str(c)]
        assert warning_calls, "Expected err_console.print to emit a yellow-tagged warning"
        assert not [c for c in fake_console.print.call_args_list if "delivery failed" in str(c)]


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


def _window(count: int) -> list[AuditLogEntry]:
    """``count`` entries, newest first like the API."""
    return [_entry(f"w{i}", -i / 100) for i in range(count)]


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

    def test_first_poll_calls_get_logs_once_when_page_0_is_last(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        queries = _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)], last=True),
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)], last=True),
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
        """The API may omit `last`; an empty page still ends the poll."""
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("a", 1)]),
                AuditLogResponse(content=[]),
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)]),
                AuditLogResponse(content=[_entry("b", 2), _entry("a", 1)]),
                AuditLogResponse(content=[]),
            ],
        )
        monitor._get_new_entries()
        calls_before = mock_client.get_logs.call_count
        new = monitor._get_new_entries()
        assert [e.id for e in new] == ["b"]
        # Page 1 has nothing new but is read anyway; the empty page 2 ends the poll.
        assert mock_client.get_logs.call_count - calls_before == 3

    def test_stops_paging_at_the_api_page_count(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        """Without `last`, the page count from the API also ends the poll."""
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=[_entry("b", 2)], total_pages=2),
                AuditLogResponse(content=[_entry("a", 1)], total_pages=2),
            ],
        )
        assert [e.id for e in monitor._get_new_entries()] == ["a", "b"]
        assert mock_client.get_logs.call_count == 2

    def test_late_entry_behind_a_seen_page_is_reported(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        """A full page of seen entries must not stop the poll before a late entry."""
        window = _window(100)
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=window, last=True),
                AuditLogResponse(content=window, last=False),
                AuditLogResponse(content=[_entry("late", -1)], last=True),
            ],
        )
        monitor._get_new_entries()
        assert [e.id for e in monitor._get_new_entries()] == ["late"]

    def test_full_window_is_seeded_at_start(
        self, monitor: AuditLogMonitor, mock_client: MagicMock
    ) -> None:
        """250 entries before start are all seen, so one new entry later reports only it."""
        window = _window(250)
        new_window = [_entry("new", 999), *window]
        _scripted(
            mock_client,
            [
                AuditLogResponse(content=window[:100], last=False),
                AuditLogResponse(content=window[100:200], last=False),
                AuditLogResponse(content=window[200:], last=True),
                AuditLogResponse(content=new_window[:100], last=False),
                AuditLogResponse(content=new_window[100:200], last=False),
                AuditLogResponse(content=new_window[200:], last=True),
            ],
        )
        first = monitor._get_new_entries()
        assert len(first) == 250
        assert [e.id for e in monitor._get_new_entries()] == ["new"]

    def test_page_cap_ends_the_poll_and_warns(
        self, monitor: AuditLogMonitor, mock_client: MagicMock, caplog: pytest.LogCaptureFixture
    ) -> None:
        from cja_audit_log_monitor.monitor import _MAX_POLL_PAGES

        counter = iter(range(100_000))

        def endless(query):
            return AuditLogResponse(content=[_entry(f"e{next(counter)}")])

        monitor._last_poll_time = datetime.now(UTC)
        mock_client.get_logs.side_effect = endless
        monitor._get_new_entries()
        assert mock_client.get_logs.call_count == _MAX_POLL_PAGES
        assert "reached" in caplog.text

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

    def test_failed_poll_shows_in_status(self, mock_client: MagicMock) -> None:
        """A transient failure must not read as a good poll with nothing new."""
        mock_client.get_logs.side_effect = APIError("[bold]down[/bold]", status_code=503)
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=7)
        status = MagicMock()
        monitor._last_poll_time = datetime.now(UTC)
        monitor._run_poll(status)
        text = status.update.call_args.args[0]
        assert "failed" in text
        assert "0 new" not in text
        assert "retry" in text.lower()
        # The error text is escaped so Rich shows it as written.
        assert "\\[bold]down" in text

    def test_good_poll_after_failure_shows_new_count(self, mock_client: MagicMock) -> None:
        mock_client.get_logs.side_effect = [
            APIError("down", status_code=503),
            AuditLogResponse(content=[_entry("a")], last=True),
        ]
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=7)
        status = MagicMock()
        monitor._last_poll_time = datetime.now(UTC)
        monitor._run_poll(status)
        monitor._run_poll(status)
        text = status.update.call_args.args[0]
        assert "1 new" in text
        assert "failed" not in text

    def test_baseline_poll_status_does_not_count_entries_as_new(
        self, mock_client: MagicMock
    ) -> None:
        mock_client.get_logs.return_value = AuditLogResponse(
            content=[_entry("a"), _entry("b")], last=True
        )
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=7)
        status = MagicMock()
        monitor._run_poll(status)
        first = status.update.call_args.args[0]
        assert "new" not in first
        assert "Baseline" in first
        assert "2 existing entries" in first
        monitor._run_poll(status)
        assert "0 new" in status.update.call_args.args[0]

    def test_stopping_message_prints_once(self, mock_client: MagicMock) -> None:
        console = MagicMock()
        monitor = AuditLogMonitor(mock_client, console=console, interval=1)
        monitor._signal_handler(2, None)
        monitor._signal_handler(15, None)
        stops = [c for c in console.print.call_args_list if "Stopping monitor" in str(c)]
        assert len(stops) == 1


class TestFetchUnseen:
    """The one paging helper that the CLI and the TUI share."""

    def test_returns_unseen_oldest_first(self) -> None:
        from cja_audit_log_monitor.monitor import fetch_unseen
        from cja_audit_log_monitor.utils import RecentIds

        seen = RecentIds(10)
        seen.add("b")
        pages = [
            AuditLogResponse(content=[_entry("c", 3), _entry("b", 2)]),
            AuditLogResponse(content=[_entry("a", 1)], last=True),
        ]
        fresh, hit_cap = fetch_unseen(
            lambda q: pages[q.page], build_poll_query(None, T0, 2), seen, max_pages=5
        )
        assert [e.id for e in fresh] == ["a", "c"]
        assert hit_cap is False
        assert "a" not in seen  # the caller decides when to remember them

    def test_reports_hitting_the_page_cap(self) -> None:
        from cja_audit_log_monitor.monitor import fetch_unseen
        from cja_audit_log_monitor.utils import RecentIds

        fresh, hit_cap = fetch_unseen(
            lambda q: AuditLogResponse(content=[_entry(f"p{q.page}")]),
            build_poll_query(None, T0, 1),
            RecentIds(10),
            max_pages=3,
        )
        assert len(fresh) == 3
        assert hit_cap is True

    def test_stop_ends_paging(self) -> None:
        import threading

        from cja_audit_log_monitor.monitor import fetch_unseen
        from cja_audit_log_monitor.utils import RecentIds

        stop = threading.Event()
        pages: list[int] = []

        def get_logs(query):
            pages.append(query.page)
            stop.set()
            return AuditLogResponse(content=[_entry(f"p{query.page}")])

        fetch_unseen(get_logs, build_poll_query(None, T0, 1), RecentIds(10), 5, stop=stop)
        assert pages == [0]


class TestMonitorOutputIsLiteral:
    """Entry text and delivery warnings are data, not Rich markup."""

    def test_entry_and_warning_with_brackets_print_literally(self, mock_client: MagicMock) -> None:
        import io

        from rich.console import Console

        buf = io.StringIO()
        err_buf = io.StringIO()
        notifier = MagicMock()
        notifier.is_configured.return_value = False
        notifier.pop_first_failure.return_value = "Slack failed [/oops]"
        engine = MagicMock()
        engine.check_entry.return_value = []
        mon = AuditLogMonitor(
            mock_client,
            console=Console(file=buf, width=200),
            err_console=Console(file=err_buf, width=200),
            alert_engine=engine,
            notification_manager=notifier,
        )
        entry = AuditLogEntry(
            id="e1",
            timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            action="CREATE",
            component_name="Q3 [/final] report",
        )

        mon._handle_entry(entry)

        out = buf.getvalue()
        assert "Q3 [/final] report" in out
        assert "Slack failed [/oops]" in err_buf.getvalue()
        assert "Slack failed" not in out


class TestPollOrdering:
    """Late-indexed events arrive newest first; the engine must still see event time order."""

    def test_newest_first_poll_fires_like_sorted(self, mock_client: MagicMock) -> None:
        from cja_audit_log_monitor.alerts import AlertEngine
        from cja_audit_log_monitor.models import ActionType, AlertRule

        base = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)
        # API order is newest first, so fetch_unseen hands back the reverse of this list.
        minutes = [100, 40, 30, 20, 10, 0]
        api_order = [
            AuditLogEntry(
                id=f"e{m}", action="DELETE", user_id="u1",
                timestamp=base + timedelta(minutes=m),
            )
            for m in minutes
        ]
        # Reverse so the monitor's own reversal yields newest first (late-indexed worst case).
        mock_client.get_logs.return_value = AuditLogResponse(
            content=list(reversed(api_order)), last=True
        )
        rule = AlertRule(
            name="five", actions=[ActionType.DELETE],
            threshold_count=5, threshold_window_minutes=60,
        )
        monitor = AuditLogMonitor(
            mock_client, console=MagicMock(), interval=7, alert_engine=AlertEngine(rules=[rule])
        )
        monitor._last_poll_time = datetime.now(UTC)
        panels = []
        monitor.console.print.side_effect = panels.append
        monitor._run_poll(MagicMock())
        from rich.panel import Panel

        assert sum(isinstance(p, Panel) for p in panels) == 1
