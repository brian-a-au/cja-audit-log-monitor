"""Tests for monitoring module."""

import io
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from rich.console import Console

from cja_audit_log_monitor.auth import AuthenticationError
from cja_audit_log_monitor.client import APIError
from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.monitor import POLL_OVERLAP, AuditLogMonitor, build_poll_query


@pytest.fixture(autouse=True)
def _quiet_consoles(monkeypatch):
    """Monitors built without a console print into a buffer, not the test output."""
    monkeypatch.setattr(
        "cja_audit_log_monitor.monitor.Console",
        lambda *args, **kwargs: Console(*args, file=io.StringIO(), **kwargs),
    )


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock audit logs client."""
    client = MagicMock()
    return client


@pytest.fixture
def monitor(mock_client: MagicMock) -> AuditLogMonitor:
    """Create a monitor instance with mock client."""
    return AuditLogMonitor(mock_client, console=Console(file=io.StringIO()), interval=1)


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
        fake_nm.pop_failures.return_value = []

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
        fake_nm.pop_failures.return_value = []
        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )
        # Must not raise
        monitor._handle_entry(sample_audit_entry)

    def test_handle_entry_prints_a_delivery_failure_warning(self, sample_audit_entry) -> None:
        """A queued delivery failure is printed as a yellow-tagged warning."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.pop_failures.return_value = [
            "Notification delivery failed (slack (hooks.slack.com/…))."
        ]

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
        from cja_audit_log_monitor.monitor import MAX_POLL_PAGES

        counter = iter(range(100_000))

        def endless(query):
            return AuditLogResponse(content=[_entry(f"e{next(counter)}")])

        monitor._last_poll_time = datetime.now(UTC)
        mock_client.get_logs.side_effect = endless
        monitor.err_console = MagicMock()
        monitor._run_poll(MagicMock())
        assert mock_client.get_logs.call_count == MAX_POLL_PAGES
        assert "older events were skipped" in str(monitor.err_console.print.call_args)

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
        import itertools

        mock_client.get_logs.side_effect = APIError("down", status_code=503)
        err_console = MagicMock()
        monitor = AuditLogMonitor(mock_client, interval=1, err_console=err_console)
        ticks = itertools.count(0, 1)
        with (
            patch("cja_audit_log_monitor.monitor.time.monotonic", lambda: next(ticks)),
            patch("cja_audit_log_monitor.monitor.time.sleep"),
        ):
            monitor.start(duration=5)
        assert mock_client.get_logs.call_count > 1
        assert "down" in str(err_console.print.call_args_list)

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

    def test_warning_pauses_the_live_status_while_printing(self, mock_client: MagicMock) -> None:
        events: list[str] = []
        status = MagicMock()
        status.stop.side_effect = lambda: events.append("stop")
        status.start.side_effect = lambda: events.append("start")
        err_console = MagicMock()
        err_console.print.side_effect = lambda *a, **k: events.append("print")
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), err_console=err_console)
        monitor._status = status
        monitor._print_warning("Slack failed")
        assert events == ["stop", "print", "start"]

    def test_warning_without_a_status_just_prints(self, mock_client: MagicMock) -> None:
        err_console = MagicMock()
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), err_console=err_console)
        monitor._print_warning("Slack failed")
        err_console.print.assert_called_once()

    def test_stopping_message_prints_once(self, mock_client: MagicMock) -> None:
        console = MagicMock()
        monitor = AuditLogMonitor(mock_client, console=console, interval=1)
        monitor._signal_handler(2, None)
        monitor._signal_handler(15, None)
        stops = [c for c in console.print.call_args_list if "Monitor stopped" in str(c)]
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
        fresh, skipped = fetch_unseen(
            lambda q: pages[q.page], build_poll_query(None, T0, 2), seen, max_pages=5
        )
        assert [e.id for e in fresh] == ["a", "c"]
        assert skipped == 0
        assert "a" not in seen  # the caller decides when to remember them

    def test_reports_hitting_the_page_cap(self) -> None:
        from cja_audit_log_monitor.monitor import fetch_unseen
        from cja_audit_log_monitor.utils import RecentIds

        fresh, skipped = fetch_unseen(
            lambda q: AuditLogResponse(content=[_entry(f"p{q.page}")]),
            build_poll_query(None, T0, 1),
            RecentIds(10),
            max_pages=3,
        )
        assert len(fresh) == 3
        assert skipped is None  # the cap was hit and the API gave no total

    def test_counts_what_the_page_cap_skipped(self) -> None:
        from cja_audit_log_monitor.monitor import fetch_unseen
        from cja_audit_log_monitor.utils import RecentIds

        _, skipped = fetch_unseen(
            lambda q: AuditLogResponse(content=[_entry(f"p{q.page}")], total_elements=10),
            build_poll_query(None, T0, 1),
            RecentIds(10),
            max_pages=3,
        )
        assert skipped == 7

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
        notifier.pop_failures.return_value = ["Slack failed [/oops]"]
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


class TestPollGuards:
    """Guards for the poll window, the baseline and stopping (G38)."""

    def test_failed_poll_keeps_the_poll_window(self, mock_client: MagicMock) -> None:
        last_good = datetime.now(UTC) - timedelta(minutes=3)
        mock_client.get_logs.side_effect = [
            APIError("down", status_code=503),
            AuditLogResponse(content=[], last=True),
        ]
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=5)
        monitor._last_poll_time = last_good
        monitor._get_new_entries()
        monitor._get_new_entries()
        query = mock_client.get_logs.call_args_list[1].args[0]
        assert query.start_date == last_good - POLL_OVERLAP

    def test_baseline_poll_raises_no_alert(self, mock_client: MagicMock) -> None:
        mock_client.get_logs.return_value = AuditLogResponse(
            content=[_entry(f"d{i}", -i, action="DELETE") for i in range(10)], last=True
        )
        engine = MagicMock()
        monitor = AuditLogMonitor(
            mock_client, console=MagicMock(), interval=5, alert_engine=engine
        )
        monitor._run_poll(MagicMock())
        engine.check_entry.assert_not_called()

    def test_sigint_stops_the_loop(self, mock_client: MagicMock) -> None:
        import signal

        mock_client.get_logs.return_value = AuditLogResponse(content=[], last=True)
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=5)
        sleeps: list[float] = []

        def sleep(seconds: float) -> None:
            sleeps.append(seconds)
            if len(sleeps) > 5:
                raise AssertionError("the loop kept running after SIGINT")
            monitor._signal_handler(signal.SIGINT, None)

        with patch("cja_audit_log_monitor.monitor.time.sleep", sleep):
            monitor.start()
        assert len(sleeps) == 1


class TestTransientTokenFailure:
    """One failed token refresh does not end a monitor (G2)."""

    def test_monitor_survives_transient_token_failure(self, mock_client: MagicMock) -> None:
        mock_client.get_logs.side_effect = [
            AuditLogResponse(content=[], last=True),
            AuthenticationError("OAuth authentication failed: 503", transient=True),
            AuditLogResponse(content=[], last=True),
        ]
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=5)
        status = MagicMock()
        for _ in range(3):
            monitor._run_poll(status)
        assert monitor.successful_polls == 2

    def test_monitor_stops_on_bad_credentials(self, mock_client: MagicMock) -> None:
        mock_client.get_logs.side_effect = AuthenticationError("invalid_client")
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=5)
        with pytest.raises(AuthenticationError):
            monitor._run_poll(MagicMock())


class _FakeAuditApi:
    """Answers get_logs from a list of entries by date window and page, newest first."""

    def __init__(self, entries: list[AuditLogEntry]) -> None:
        self.entries = sorted(entries, key=lambda e: e.timestamp, reverse=True)
        self.fail_next: list[Exception] = []
        self.calls = 0

    def get_logs(self, query):
        self.calls += 1
        if self.fail_next:
            raise self.fail_next.pop(0)
        hits = [
            e for e in self.entries
            if query.start_date <= e.timestamp <= query.end_date
        ]
        size = query.page_size
        chunk = hits[query.page * size:(query.page + 1) * size]
        pages = max(1, -(-len(hits) // size))
        return AuditLogResponse(
            content=chunk, total_elements=len(hits), total_pages=pages,
            last=query.page >= pages - 1,
        )


class _Clock:
    """A stand-in for the monitor module's datetime, with a settable now()."""

    now_value = T0

    @classmethod
    def now(cls, tz=None):
        return cls.now_value


@pytest.fixture
def clock(monkeypatch):
    import cja_audit_log_monitor.monitor as monitor_module

    class FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return _Clock.now_value

    monkeypatch.setattr(monitor_module, "datetime", FakeDatetime)
    _Clock.now_value = T0
    return _Clock


def _stream(start: datetime, minutes: int, per_minute: int, prefix: str = "e"):
    return [
        AuditLogEntry(
            id=f"{prefix}{m}-{k}",
            timestamp=start + timedelta(minutes=m, seconds=k * (60 / per_minute)),
            action="CREATE",
            user_email=f"u{k}@example.com",
        )
        for m in range(minutes)
        for k in range(per_minute)
    ]


class TestBacklog:
    """After a gap the monitor reads the whole backlog, or says what it skipped (G3)."""

    def test_gap_backlog_is_read_in_full(self, clock) -> None:
        gap = _stream(T0 + timedelta(seconds=1), 480, 5)
        api = _FakeAuditApi(gap)
        seen: list[AuditLogEntry] = []
        monitor = AuditLogMonitor(MagicMock(get_logs=api.get_logs), console=MagicMock())
        monitor._on_new_entry = seen.append
        monitor._run_poll(MagicMock())  # baseline at T0
        clock.now_value = T0 + timedelta(minutes=481)
        monitor._run_poll(MagicMock())
        assert len(seen) == len(gap) == 2400

    def test_backlog_over_limit_reports_skipped_count(self, clock, monkeypatch) -> None:
        import cja_audit_log_monitor.monitor as monitor_module

        monkeypatch.setattr(monitor_module, "POLL_PAGE_SIZE", 10)
        monkeypatch.setattr(monitor_module, "MAX_POLL_PAGES", 3)
        api = _FakeAuditApi(_stream(T0 + timedelta(seconds=1), 10, 5))  # 50 events
        err_console = MagicMock()
        status = MagicMock()
        monitor = AuditLogMonitor(
            MagicMock(get_logs=api.get_logs), console=MagicMock(), err_console=err_console
        )
        monitor._run_poll(status)
        clock.now_value = T0 + timedelta(minutes=11)
        monitor._run_poll(status)
        printed = " ".join(str(c) for c in err_console.print.call_args_list)
        assert "20 older events in this gap were skipped" in printed
        assert "20 skipped" in status.update.call_args.args[0]

    def test_monitor_survives_sleep_and_ims_blip(self, clock) -> None:
        """Review Focus 1: a long sleep, then one failed token refresh, then recovery."""
        from cja_audit_log_monitor.alerts import AlertEngine

        gap = _stream(T0 + timedelta(seconds=1), 480, 5)
        deletes = [
            AuditLogEntry(
                id=f"del-{i}", timestamp=T0 + timedelta(minutes=200, seconds=i),
                action="DELETE", user_email="mallory@example.com",
            )
            for i in range(6)
        ]
        api = _FakeAuditApi(gap + deletes)
        seen: list[AuditLogEntry] = []
        engine = AlertEngine()
        fired: list[str] = []
        check = engine.check_entry

        def recording_check(entry):
            alerts = check(entry)
            fired.extend(a.rule_name for a in alerts)
            return alerts

        engine.check_entry = recording_check
        monitor = AuditLogMonitor(
            MagicMock(get_logs=api.get_logs), console=MagicMock(), alert_engine=engine
        )
        monitor._on_new_entry = seen.append
        monitor._run_poll(MagicMock())  # baseline
        clock.now_value = T0 + timedelta(minutes=481)
        api.fail_next = [AuthenticationError("IMS 503", transient=True)]
        monitor._run_poll(MagicMock())
        clock.now_value = T0 + timedelta(minutes=482)
        monitor._run_poll(MagicMock())
        ids = [e.id for e in seen]
        assert len(ids) == len(set(ids)) == len(gap) + len(deletes)
        assert "bulk_delete" in fired


class TestCtrlC:
    """Ctrl+C stops at once, even while a poll or a webhook send is blocked (G4)."""

    def test_signal_during_a_poll_stops_at_once(self, mock_client: MagicMock) -> None:
        import signal

        console = MagicMock()
        monitor = AuditLogMonitor(mock_client, console=console, interval=5)

        def blocked_poll(query):
            monitor._signal_handler(signal.SIGINT, None)
            raise AssertionError("the poll went on after Ctrl+C")

        mock_client.get_logs.side_effect = blocked_poll
        monitor.start()
        printed = " ".join(str(c) for c in console.print.call_args_list)
        assert "Monitor stopped." in printed
        assert monitor.stopped_by_user is True

    def test_ctrl_c_stops_during_a_blocked_poll(self, fake_api, tmp_path) -> None:
        import signal
        import subprocess
        import time

        from .fakeapi import command

        fake_api.block.set()
        proc = subprocess.Popen(
            [*command(), "cli", "monitor", "-i", "5", "--no-alerts"],
            env=fake_api.env(tmp_path / "missing.yaml"),
            cwd=tmp_path,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            assert fake_api.blocked.wait(30), "the monitor never reached the API"
            sent = time.monotonic()
            proc.send_signal(signal.SIGINT)
            out, err = proc.communicate(timeout=10)
            elapsed = time.monotonic() - sent
        finally:
            fake_api.block.clear()
            if proc.poll() is None:
                proc.kill()
        assert elapsed < 2, f"took {elapsed:.1f}s after Ctrl+C"
        assert proc.returncode == 0, err
        assert "Monitor stopped." in out + err

    def test_signal_during_a_webhook_send_stops_at_once(self, mock_client: MagicMock) -> None:
        import itertools
        import signal

        from cja_audit_log_monitor.alerts import AlertEngine
        from cja_audit_log_monitor.models import ActionType, AlertRule

        deletes = [_entry(f"d{i}", i / 10, action="DELETE") for i in range(3)]
        mock_client.get_logs.side_effect = [
            AuditLogResponse(content=[], last=True),
            AuditLogResponse(content=list(reversed(deletes)), last=True),
        ]
        nm = MagicMock()
        nm.is_configured.return_value = True
        nm.pop_failures.return_value = []
        monitor = AuditLogMonitor(
            mock_client, console=MagicMock(), interval=5,
            alert_engine=AlertEngine([AlertRule(name="any", actions=[ActionType.DELETE])]),
            notification_manager=nm,
        )
        nm.notify_alert.side_effect = lambda *a: monitor._signal_handler(signal.SIGINT, None)
        shown: list[str] = []
        monitor._display_entry = lambda entry: shown.append(entry.id)
        ticks = itertools.count(0, 10)
        with patch("cja_audit_log_monitor.monitor.time.monotonic", lambda: next(ticks)):
            with patch("cja_audit_log_monitor.monitor.time.sleep"):
                monitor.start()
        assert nm.notify_alert.call_count == 1
        assert monitor.stopped_by_user is True


class TestLogLinesAndStatus:
    """Log records pause the live status line instead of breaking it (G6)."""

    def test_log_record_pauses_the_status_line(self, mock_client: MagicMock) -> None:
        import itertools
        import logging

        events: list[str] = []
        err_console = MagicMock()
        err_console.print.side_effect = lambda *a, **k: events.append("print")

        def failing_poll(query):
            raise APIError("down", status_code=503)

        mock_client.get_logs.side_effect = failing_poll
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), err_console=err_console)

        class FakeStatus:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def update(self, text):
                pass

            def stop(self):
                events.append("stop")

            def start(self):
                events.append("start")

        monitor.console.status = lambda *a, **k: FakeStatus()
        ticks = itertools.count(0, 10)
        with (
            patch("cja_audit_log_monitor.monitor.time.monotonic", lambda: next(ticks)),
            patch("cja_audit_log_monitor.monitor.time.sleep"),
        ):
            monitor.start(duration=5)
        assert events[:3] == ["stop", "print", "start"]
        assert logging.getLogger("cja_audit_log_monitor").propagate is True

    def test_alert_is_logged_at_info(self, caplog) -> None:
        import logging

        from cja_audit_log_monitor.alerts import AlertEngine
        from cja_audit_log_monitor.models import ActionType, AlertRule

        engine = AlertEngine([AlertRule(name="any", actions=[ActionType.DELETE])])
        with caplog.at_level(logging.DEBUG):
            engine.check_entry(_entry("x", action="DELETE"))
        records = [r for r in caplog.records if "Alert triggered" in r.getMessage()]
        assert [r.levelno for r in records] == [logging.INFO]


class TestMonitorDetails:
    """Clock labels, duration, a failed first poll (G42)."""

    def test_clock_label_names_utc(self, mock_client: MagicMock) -> None:
        mock_client.get_logs.return_value = AuditLogResponse(content=[], last=True)
        console = MagicMock()
        monitor = AuditLogMonitor(mock_client, console=console, interval=5)
        status = MagicMock()
        monitor._run_poll(status)
        assert "UTC" in status.update.call_args.args[0]
        monitor._display_entry(_entry("a"))
        assert "UTC" in str(console.print.call_args)

    def test_duration_counts_the_first_poll(self, mock_client: MagicMock) -> None:
        clock = {"t": 0.0}

        def slow_poll(query):
            clock["t"] += 6  # each poll takes 6 seconds
            return AuditLogResponse(content=[], last=True)

        def sleep(seconds):
            clock["t"] += seconds

        mock_client.get_logs.side_effect = slow_poll
        monitor = AuditLogMonitor(mock_client, console=MagicMock(), interval=5)
        with (
            patch("cja_audit_log_monitor.monitor.time.monotonic", lambda: clock["t"]),
            patch("cja_audit_log_monitor.monitor.time.sleep", sleep),
        ):
            monitor.start(duration=10)
        assert clock["t"] <= 13  # the 10 seconds include the first poll

    def test_first_poll_fails_later_entries_still_alert(self, mock_client: MagicMock) -> None:
        later = AuditLogEntry(
            id="late", action="DELETE", timestamp=datetime.now(UTC) + timedelta(seconds=30)
        )
        mock_client.get_logs.side_effect = [
            APIError("down", status_code=503),
            AuditLogResponse(content=[later], last=True),
        ]
        engine = MagicMock()
        engine.check_entry.return_value = []
        monitor = AuditLogMonitor(
            mock_client, console=MagicMock(), interval=5, alert_engine=engine
        )
        monitor._run_poll(MagicMock())
        with patch("cja_audit_log_monitor.monitor.datetime") as fake_dt:
            fake_dt.now.return_value = datetime.now(UTC) + timedelta(minutes=1)
            monitor._run_poll(MagicMock())
        engine.check_entry.assert_called_once_with(later)


def test_cli_monitor_shows_every_channel_failure(mock_client: MagicMock) -> None:
    from cja_audit_log_monitor.alerts import AlertEngine
    from cja_audit_log_monitor.models import ActionType, AlertRule

    nm = MagicMock()
    nm.is_configured.return_value = True
    nm.pop_failures.return_value = ["webhook 1 failed", "webhook 2 failed"]
    err_console = MagicMock()
    monitor = AuditLogMonitor(
        mock_client, console=MagicMock(), err_console=err_console,
        alert_engine=AlertEngine([AlertRule(name="any", actions=[ActionType.DELETE])]),
        notification_manager=nm,
    )
    monitor._handle_entry(_entry("d", action="DELETE"))
    printed = str(err_console.print.call_args_list)
    assert "webhook 1 failed" in printed and "webhook 2 failed" in printed
