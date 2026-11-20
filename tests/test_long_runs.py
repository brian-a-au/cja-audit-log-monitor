"""Scale and long runs: big exports, many polls, and a simulated day on a fake clock."""

import bisect
import json
import threading
import time
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from cja_audit_log_monitor.alerts import AlertEngine
from cja_audit_log_monitor.export import export_entries
from cja_audit_log_monitor.models import AlertRule, AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.monitor import POLL_OVERLAP, AuditLogMonitor

from .test_tui import _drive_poll, _make_app, _start_monitor_without_loop, _wait_for

START = datetime(2026, 11, 1, tzinfo=UTC)


class FakeClock:
    """A ``datetime`` stand-in whose ``now`` is moved by the test, not by real time."""

    def __init__(self, start: datetime) -> None:
        self.current = start
        clock = self

        class _Datetime(datetime):
            @classmethod
            def now(cls, tz=None):  # noqa: D102
                return clock.current if tz else clock.current.replace(tzinfo=None)

        self.datetime = _Datetime

    def advance(self, seconds: float) -> None:
        self.current += timedelta(seconds=seconds)


class FakeStream:
    """An audit log API with ``per_minute`` events a minute, from START for ``minutes``.

    ``get_logs`` returns the events inside the query window, newest first and paged, as
    the real API does.
    """

    def __init__(self, per_minute: int, minutes: int, users: int | None = None) -> None:
        step = 60 / per_minute
        self.events = [
            AuditLogEntry(
                id=f"e{i}",
                timestamp=START + timedelta(seconds=i * step),
                action="EDIT",
                component_type="PROJECT",
                user_id=f"u{i % users}" if users else "u0",
            )
            for i in range(per_minute * minutes)
        ]
        self._times = [e.timestamp for e in self.events]
        self.calls = 0

    def get_logs(self, query) -> AuditLogResponse:
        self.calls += 1
        lo = bisect.bisect_left(self._times, query.start_date)
        hi = bisect.bisect_right(self._times, query.end_date)
        window = self.events[lo:hi][::-1]
        size = query.page_size
        page = window[query.page * size : (query.page + 1) * size]
        pages = max(1, -(-len(window) // size))
        return AuditLogResponse(
            content=page,
            total_elements=len(window),
            total_pages=pages,
            last=query.page >= pages - 1,
        )


def _cli_monitor(stream: FakeStream) -> AuditLogMonitor:
    client = MagicMock()
    client.get_logs.side_effect = stream.get_logs
    return AuditLogMonitor(client, console=MagicMock(), err_console=MagicMock(), interval=60)


def _run_cli_polls(
    monitor: AuditLogMonitor, clock: FakeClock, polls: int, interval: int
) -> list[str]:
    delivered: list[str] = []
    with patch("cja_audit_log_monitor.monitor.datetime", clock.datetime):
        for _ in range(polls):
            clock.advance(interval)
            delivered.extend(e.id for e in monitor._get_new_entries())
    return delivered


# ---------------------------------------------------------------------------
# The monitor's seen keys


class TestSeenKeys:
    def test_a_busy_overlap_window_gives_no_duplicates(self) -> None:
        """1,500 events a minute: one poll re-reads more events than the old 5,000 key cap."""
        stream = FakeStream(per_minute=1500, minutes=12)
        clock = FakeClock(START + timedelta(minutes=1))
        monitor = _cli_monitor(stream)
        delivered = _run_cli_polls(monitor, clock, polls=10, interval=60)
        assert len(delivered) == len(set(delivered)), "an event was delivered twice"
        # Every event after the first poll's window start arrived exactly once.
        first_start = START + timedelta(minutes=2) - POLL_OVERLAP
        expected = {e.id for e in stream.events if first_start <= e.timestamp <= clock.current}
        assert set(delivered) == expected

    def test_a_simulated_day_keeps_only_the_overlap_window(self) -> None:
        """24 hours of polls each minute: memory follows the window, not the run time."""
        per_minute = 10
        stream = FakeStream(per_minute=per_minute, minutes=24 * 60 + 10)
        clock = FakeClock(START + timedelta(minutes=5))
        monitor = _cli_monitor(stream)
        delivered = _run_cli_polls(monitor, clock, polls=24 * 60, interval=60)
        assert len(delivered) == len(set(delivered))
        window_minutes = POLL_OVERLAP.total_seconds() / 60 + 1  # overlap plus one interval
        assert len(monitor._seen) <= per_minute * window_minutes + per_minute

    @pytest.mark.parametrize("ts", [START - timedelta(days=365), None])
    def test_an_entry_the_api_keeps_returning_is_delivered_once(self, ts) -> None:
        """An entry from before the window, or with no time, must not come back as new."""
        stray = AuditLogEntry(id="stray", timestamp=ts, action="EDIT")
        client = MagicMock()
        client.get_logs.return_value = AuditLogResponse(content=[stray], last=True)
        monitor = AuditLogMonitor(client, console=MagicMock(), err_console=MagicMock())
        clock = FakeClock(START)
        delivered = _run_cli_polls(monitor, clock, polls=20, interval=60)
        assert delivered == ["stray"]

    def test_entries_without_a_time_are_still_remembered(self) -> None:
        from cja_audit_log_monitor.utils import RecentIds

        seen = RecentIds(3)
        seen.add("untimed")
        seen.add("old", START)
        seen.forget_before(START + timedelta(minutes=1))
        assert "untimed" in seen
        assert "old" not in seen
        # The count cap still bounds what has no time.
        for key in "abcd":
            seen.add(key)
        assert len(seen) == 3

    async def test_tui_monitor_busy_window_gives_no_duplicates(
        self, mock_app_state, monkeypatch
    ) -> None:
        from cja_audit_log_monitor.tui.widgets import LogTable

        stream = FakeStream(per_minute=1500, minutes=10)
        mock_app_state.client.get_logs.side_effect = stream.get_logs
        clock = FakeClock(START + timedelta(minutes=1))
        monkeypatch.setattr("cja_audit_log_monitor.tui.screens.monitor.datetime", clock.datetime)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            batches: list[list[AuditLogEntry]] = []
            real_check = mock_app_state.check_alerts

            def record(entries):
                batches.append(list(entries))
                return real_check(entries)

            monkeypatch.setattr(mock_app_state, "check_alerts", record)
            for _ in range(6):
                clock.advance(60)
                await _drive_poll(screen, pilot)
            ids = [e.id for batch in batches for e in batch]
            assert len(ids) == len(set(ids)), "an event was alerted on twice"
            assert screen._state.monitor.entries_since_start == len(ids)
            assert screen.query_one("#monitor-log", LogTable).row_count == 1000
            screen._stop_monitoring()


# ---------------------------------------------------------------------------
# The TUI monitor's table after many polls


async def test_monitor_table_stays_at_1000_rows_after_many_polls(
    mock_app_state, monkeypatch
) -> None:
    from cja_audit_log_monitor.tui.screens.monitor import MONITOR_MAX_ROWS
    from cja_audit_log_monitor.tui.widgets import LogTable

    stream = FakeStream(per_minute=120, minutes=70)
    mock_app_state.client.get_logs.side_effect = stream.get_logs
    clock = FakeClock(START + timedelta(minutes=1))
    monkeypatch.setattr("cja_audit_log_monitor.tui.screens.monitor.datetime", clock.datetime)
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        for _ in range(60):
            clock.advance(60)
            await _drive_poll(screen, pilot)
        table = screen.query_one("#monitor-log", LogTable)
        assert table.row_count == MONITOR_MAX_ROWS
        assert len(table._entries) == MONITOR_MAX_ROWS  # no rows kept behind the table
        # The newest event is the last row, and the cursor follows it.
        assert table.get_selected_entry().timestamp == max(
            e.timestamp for e in table._entries.values()
        )
        screen._stop_monitoring()


# ---------------------------------------------------------------------------
# The alert engine's history over a simulated day


class TestAlertHistory:
    def test_a_day_of_many_users_keeps_only_the_window(self) -> None:
        """Per-user rules keep one history per user; old users must not stay forever."""
        rule = AlertRule(
            name="edits",
            actions=["EDIT"],
            threshold_count=50,
            threshold_window_minutes=60,
            per_user=True,
        )
        engine = AlertEngine([rule])
        per_minute = 10
        stream = FakeStream(per_minute=per_minute, minutes=24 * 60, users=10_000)
        clock = FakeClock(START)
        with patch("cja_audit_log_monitor.alerts.datetime", clock.datetime):
            for entry in stream.events:
                clock.current = entry.timestamp
                engine.check_entry(entry)
            in_window = per_minute * 60
            pending = sum(len(events) for events in engine._event_history.values())
            assert pending <= in_window + per_minute
            assert len(engine._event_history) <= in_window + per_minute
            status = engine.get_rule_status()[0]
            assert status["pending_events"] == pending

    def test_events_inside_the_window_still_count(self) -> None:
        rule = AlertRule(
            name="deletes",
            actions=["DELETE"],
            threshold_count=3,
            threshold_window_minutes=60,
        )
        engine = AlertEngine([rule])
        clock = FakeClock(START)
        fired = []
        with patch("cja_audit_log_monitor.alerts.datetime", clock.datetime):
            for minute in (0, 20, 59):
                clock.current = START + timedelta(minutes=minute)
                entry = AuditLogEntry(id=f"d{minute}", timestamp=clock.current, action="DELETE")
                fired += engine.check_entry(entry)
            # A busy hour for other users in between must not sweep these away.
        assert len(fired) == 1

    def test_a_replay_of_old_events_is_judged_by_event_time(self) -> None:
        """`alerts test` replays history: the sweep must follow event time, not the clock."""
        rule = AlertRule(
            name="deletes",
            actions=["DELETE"],
            threshold_count=3,
            threshold_window_minutes=10,
        )
        engine = AlertEngine([rule])
        old = START - timedelta(days=30)
        entries = [
            AuditLogEntry(id=f"d{i}", timestamp=old + timedelta(minutes=i), action="DELETE")
            for i in range(3)
        ]
        assert len(engine.check_batch(entries)) == 1


# ---------------------------------------------------------------------------
# Exporting 10,000 entries


def _many(count: int) -> list[AuditLogEntry]:
    return [
        AuditLogEntry(
            id=f"x{i}",
            timestamp=START + timedelta(seconds=i),
            user_email=f"user{i % 50}@example.com",
            action="EDIT",
            component_type="PROJECT",
            component_name=f"Project {i} =SUM(A1)",
            description="Edited a project " * 5,
            changes={"before": {"name": "a"}, "after": {"name": "b"}},
        )
        for i in range(count)
    ]


@pytest.mark.parametrize("fmt", ["json", "csv", "tsv"])
def test_export_of_10000_entries_is_quick(tmp_path, fmt) -> None:
    entries = _many(10_000)
    target = tmp_path / f"big.{fmt}"
    started = time.perf_counter()
    assert export_entries(entries, target, fmt) == 10_000
    took = time.perf_counter() - started
    # A generous bound for a slow CI runner; it takes well under a second on a laptop.
    assert took < 10, f"{fmt} export of 10,000 entries took {took:.2f}s"
    if fmt == "json":
        assert json.loads(target.read_text())["count"] == 10_000
    else:
        assert len(target.read_text(encoding="utf-8").splitlines()) == 10_001


async def test_tui_export_of_10000_entries_keeps_the_ui_responsive(
    mock_app_state, tmp_path, monkeypatch
) -> None:
    """The write runs on a worker thread; keys still work while it runs."""
    import cja_audit_log_monitor.tui.modals.export_dialog as dialog_module

    entries = _many(10_000)
    mock_app_state.page_loaded = True
    mock_app_state.entries = entries
    release = threading.Event()
    threads: list[str] = []
    real_export = dialog_module.export_entries

    def slow_export(*args, **kwargs):
        threads.append(threading.current_thread().name)
        release.wait(10)  # hold the write until the test has used the UI
        return real_export(*args, **kwargs)

    monkeypatch.setattr(dialog_module, "export_entries", slow_export)
    app = _make_app(mock_app_state)
    target = tmp_path / "big.json"
    async with app.run_test(size=(120, 40), notifications=True) as pilot:
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        dialog = app.screen
        dialog.query_one("#output-path").value = str(target)
        await pilot.click("#export-button")
        assert await _wait_for(lambda: bool(threads), pilot)
        assert threads[0] != threading.main_thread().name
        # While the file is being written, the UI still answers: focus moves with tab.
        before = app.focused
        await pilot.press("tab")
        await pilot.pause()
        assert app.focused is not before
        release.set()
        assert await _wait_for(
            lambda: any("exported 10,000 entries" in n.message for n in app._notifications),
            pilot,
            timeout=15,
        )
    assert json.loads(target.read_text())["count"] == 10_000
