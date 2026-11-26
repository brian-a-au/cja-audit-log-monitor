"""TUI tests for paths the rest of the suite did not reach."""

import asyncio
import logging
import threading
from datetime import UTC, datetime
from types import SimpleNamespace

from textual.screen import Screen
from textual.widgets import Button, Input

from cja_audit_log_monitor.alerts import AlertEngine
from cja_audit_log_monitor.client import APIError
from cja_audit_log_monitor.models import AlertRule, AuditLogEntry, AuditLogResponse

from .test_tui import (
    _drive_poll,
    _make_app,
    _monitor_entries,
    _page_zero_batches,
    _start_monitor_without_loop,
    _wait_for,
)

SIZE = (120, 40)


async def _show(app, pilot, key: str):
    """Show a view by its key and wait for its first load."""
    await pilot.press(key)
    await pilot.pause()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return app._screens[app._current_screen]


# ---------------------------------------------------------------------------
# app.py
# ---------------------------------------------------------------------------


class TestAppShell:
    async def test_status_update_after_the_app_ended_is_dropped(self, mock_app_state):
        """A late worker result after quitting must not raise."""
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
        app.set_connection_status("connected", "late")
        assert app._connection_status == "connected"

    async def test_header_refit_after_the_app_ended_is_dropped(self, mock_app_state):
        """A resize that lands after quitting finds no header row and must not raise."""
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
        status = app._connection_status
        app._refit_status_row(80)
        assert app._connection_status == status

    async def test_click_event_without_a_widget_is_ignored(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await app.on_click(SimpleNamespace(widget=None))
            assert app._current_screen == "dashboard"


# ---------------------------------------------------------------------------
# Buttons that the suite only reached through keys
# ---------------------------------------------------------------------------


class TestButtons:
    async def test_dashboard_refresh_button_reloads(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await pilot.pause()
            await app.workers.wait_for_complete()
            before = mock_app_state.client.get_logs_sample.call_count
            await pilot.click("#refresh-button")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert mock_app_state.client.get_logs_sample.call_count == before + 1

    async def test_monitor_start_and_stop_buttons(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.screens.monitor import MonitorView

        async def _no_loop(self, stop):
            return None

        monkeypatch.setattr(MonitorView, "_monitoring_loop", _no_loop)
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await _show(app, pilot, "m")
            await pilot.click("#start-button")
            await pilot.pause()
            assert mock_app_state.monitor.is_running
            assert app.query_one("#stop-button", Button).disabled is False
            await pilot.click("#stop-button")
            await pilot.pause()
            assert not mock_app_state.monitor.is_running
            assert app.query_one("#start-button", Button).disabled is False

    async def test_settings_verify_button_checks_again(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await _show(app, pilot, "c")
            before = mock_app_state.client.verify_connection.call_count
            await pilot.click("#verify-button")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert mock_app_state.client.verify_connection.call_count == before + 1

    async def test_stats_update_button_applies_days(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await _show(app, pilot, "s")
            app.query_one("#days-input", Input).value = "3"
            await pilot.click("#update-button")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert mock_app_state.stats_days == 3

    async def test_stats_empty_days_box_falls_back_to_default(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            await _show(app, pilot, "s")
            box = app.query_one("#days-input", Input)
            box.value = ""
            await pilot.click("#update-button")
            await app.workers.wait_for_complete()
            await pilot.pause()
            default = mock_app_state.settings.default_days
            assert mock_app_state.stats_days == default
            assert box.value == str(default)


# ---------------------------------------------------------------------------
# alerts view
# ---------------------------------------------------------------------------


class TestAlertsView:
    async def test_stale_card_after_the_engine_shrank(self, mock_app_state):
        """A card from the old engine (before its refresh) does not touch the new rules."""
        mock_app_state._alert_engine = AlertEngine(
            [AlertRule(name="one"), AlertRule(name="two"), AlertRule(name="three")]
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            await _show(app, pilot, "a")
            new_engine = AlertEngine([AlertRule(name="only")])
            mock_app_state._alert_engine = new_engine
            await pilot.click("#rule-2")
            await pilot.pause()
            assert new_engine.rules[0].enabled is True
            assert not any("rule:" in n.message for n in app._notifications)

    async def test_change_from_an_unknown_checkbox_is_ignored(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            view = await _show(app, pilot, "a")
            event = SimpleNamespace(checkbox=SimpleNamespace(id="not-a-rule"), value=False)
            view.on_checkbox_changed(event)
            await pilot.pause()
            assert not app._notifications


# ---------------------------------------------------------------------------
# base.py
# ---------------------------------------------------------------------------


async def test_failure_while_showing_a_failure_is_logged(mock_app_state, caplog):
    app = _make_app(mock_app_state)
    async with app.run_test(size=SIZE) as pilot:
        view = await _show(app, pilot, "d")

        def apply(value):
            raise RuntimeError("apply broke")

        def on_error(error):
            raise RuntimeError("error view broke")

        with caplog.at_level(logging.ERROR):
            view.run_load(lambda: 1, apply, on_error)
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert "Applying loaded data failed" in caplog.text
        assert "Showing a load error failed" in caplog.text
        assert app.is_running


# ---------------------------------------------------------------------------
# export dialog
# ---------------------------------------------------------------------------


class TestExportDialog:
    async def _open(self, app, pilot, target):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        dialog = app.screen
        dialog.query_one("#output-path", Input).value = str(target)
        return dialog

    async def test_enter_while_an_export_runs_starts_no_second_one(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch
    ):
        from cja_audit_log_monitor.tui.modals import export_dialog

        release = threading.Event()
        calls = []

        def slow_export(entries, path, **kwargs):
            calls.append(path)
            release.wait(5)
            path.write_text("{}")
            return len(entries)

        monkeypatch.setattr(export_dialog, "export_entries", slow_export)
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        target = tmp_path / "out.json"
        async with app.run_test(size=SIZE) as pilot:
            dialog = await self._open(app, pilot, target)
            await pilot.click("#export-button")
            assert await _wait_for(lambda: calls, pilot)
            dialog.query_one("#output-path", Input).focus()
            await pilot.press("enter")
            await pilot.pause()
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert len(calls) == 1

    async def test_file_appearing_after_the_dialog_closed(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch
    ):
        from cja_audit_log_monitor.tui.modals import export_dialog
        from cja_audit_log_monitor.tui.modals.export_dialog import ExportDialog

        release = threading.Event()
        started = threading.Event()
        asked = []

        def racing_export(entries, path, **kwargs):
            started.set()
            release.wait(5)
            raise FileExistsError(str(path))

        original = ExportDialog._ask_overwrite

        def record(self, app, key):
            asked.append(key)
            original(self, app, key)

        monkeypatch.setattr(export_dialog, "export_entries", racing_export)
        monkeypatch.setattr(ExportDialog, "_ask_overwrite", record)
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        target = tmp_path / "out.json"
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            dialog = await self._open(app, pilot, target)
            await pilot.click("#export-button")
            assert await _wait_for(started.is_set, pilot)
            await pilot.click("#cancel-button")
            await pilot.pause()
            assert app.screen is not dialog
            release.set()
            assert await _wait_for(lambda: asked, pilot)
            assert dialog._overwrite_pending is None
            messages = [n.message for n in app._notifications]
            assert messages.count("export cancelled") == 1
            assert app.is_running

    async def test_auto_close_leaves_a_screen_opened_on_top(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        target = tmp_path / "out.json"
        async with app.run_test(size=SIZE) as pilot:
            dialog = await self._open(app, pilot, target)
            await pilot.click("#export-button")
            assert await _wait_for(target.exists, pilot, timeout=5.0)
            await app.workers.wait_for_complete()
            await pilot.pause()
            top = Screen()
            await app.push_screen(top)
            await pilot.pause()
            dialog._close_if_open()
            await pilot.pause()
            assert app.screen is top
            assert dialog in app.screen_stack


# ---------------------------------------------------------------------------
# log browser and log table
# ---------------------------------------------------------------------------


class TestLogBrowser:
    def test_panel_lookups_before_the_view_is_built(self, mock_app_state):
        """Textual can ask about bindings or post table events before compose."""
        from cja_audit_log_monitor.tui.screens.log_browser import LogBrowserView

        view = LogBrowserView(mock_app_state)
        assert view.check_action("dismiss_details", ()) is False
        view.on_data_table_row_highlighted(None)
        view.action_dismiss_details()

    async def test_highlight_on_an_empty_table_keeps_the_open_panel(self, mock_app_state):
        from cja_audit_log_monitor.tui.modals.entry_detail import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            view = await _show(app, pilot, "l")
            table = view.query_one("#log-table", LogTable)
            table.focus()
            await pilot.press("enter")
            await pilot.pause()
            panel = view.query_one("#entry-detail-panel", EntryDetailPanel)
            assert panel.is_visible()
            shown = panel._entry
            table.load_entries([])
            await pilot.pause()
            view.on_data_table_row_highlighted(None)
            assert panel.is_visible()
            assert panel._entry is shown

    async def test_entries_without_an_id_are_listed(self, mock_app_state):
        from cja_audit_log_monitor.tui.widgets import LogTable

        base = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
        entries = [
            AuditLogEntry(timestamp=base, user_id="u1", action="EDIT"),
            AuditLogEntry(timestamp=base, user_id="u2", action="DELETE"),
        ]
        mock_app_state.client.get_logs.return_value = AuditLogResponse(
            content=entries, total_elements=2, total_pages=1
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            view = await _show(app, pilot, "l")
            table = view.query_one("#log-table", LogTable)
            assert table.row_count == 2


async def test_monitor_keeps_the_cursor_when_new_rows_arrive(mock_app_state, monkeypatch):
    """Scrolled up in the stream, a new row is added below without moving the cursor."""
    from cja_audit_log_monitor.tui.widgets import LogTable

    mock_app_state.client.get_logs.side_effect = _page_zero_batches(
        [_monitor_entries(0, 3), _monitor_entries(3, 1)]
    )
    app = _make_app(mock_app_state)
    async with app.run_test(size=SIZE) as pilot:
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        await _drive_poll(screen, pilot)
        table = screen.query_one("#monitor-log", LogTable)
        assert table.row_count == 3
        table.move_cursor(row=0)
        await pilot.pause()
        await _drive_poll(screen, pilot)
        assert table.row_count == 4
        assert table.cursor_row == 0


# ---------------------------------------------------------------------------
# monitor view: polls that race a stop
# ---------------------------------------------------------------------------


class TestMonitorStopRaces:
    async def test_poll_error_after_stop_is_dropped(self, mock_app_state, monkeypatch):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            stop = threading.Event()

            def boom(stop_event):
                stop_event.set()
                raise RuntimeError("app is shutting down")

            monkeypatch.setattr(screen, "_poll_for_new_entries", boom)
            await asyncio.to_thread(screen._guarded_poll, stop)
            await pilot.pause()
            assert mock_app_state.monitor.last_error is None

    async def test_poll_error_that_cannot_be_shown_is_logged(
        self, mock_app_state, monkeypatch, caplog
    ):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)

            def boom(stop_event):
                raise RuntimeError("local bug")

            def gone(*args, **kwargs):
                raise RuntimeError("app is not running")

            monkeypatch.setattr(screen, "_poll_for_new_entries", boom)
            monkeypatch.setattr(app, "call_from_thread", gone)
            with caplog.at_level(logging.ERROR):
                await asyncio.to_thread(screen._guarded_poll, threading.Event())
            assert "Could not show the monitor poll failure" in caplog.text

    async def test_poll_from_a_stopped_session_fetches_nothing(self, mock_app_state, monkeypatch):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            mock_app_state.client.get_logs.reset_mock()
            stop = threading.Event()
            stop.set()
            await asyncio.to_thread(screen._poll_for_new_entries, stop)
            mock_app_state.client.get_logs.assert_not_called()

    async def test_fetch_error_after_stop_is_not_shown(self, mock_app_state, monkeypatch):
        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE, notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            stop = threading.Event()

            def fail(query):
                stop.set()
                raise APIError("connection reset", network=True)

            mock_app_state.client.get_logs.side_effect = fail
            await asyncio.to_thread(screen._poll_for_new_entries, stop)
            await pilot.pause()
            assert mock_app_state.monitor.last_error is None

    async def test_stop_during_a_first_poll_shows_no_context(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            stop = threading.Event()

            def fetch(query):
                stop.set()
                return AuditLogResponse(content=_monitor_entries(0, 2), last=True)

            mock_app_state.client.get_logs.side_effect = fetch
            await asyncio.to_thread(screen._poll_for_new_entries, stop)
            await pilot.pause()
            assert screen.query_one("#monitor-log", LogTable).row_count == 0
            assert screen._last_poll_time is None

    async def test_results_for_an_ended_session_are_dropped(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=SIZE) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            stop = threading.Event()
            stop.set()
            screen._apply_poll(stop, datetime.now(UTC), _monitor_entries(0, 2), [], [])
            screen._apply_poll_error(stop, APIError("late failure"))
            await pilot.pause()
            assert screen.query_one("#monitor-log", LogTable).row_count == 0
            assert screen._last_poll_time is None
            assert mock_app_state.monitor.last_error is None
