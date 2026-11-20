"""Two things at once: workers that overlap, reloads during loads, and quitting mid-work.

Every test here also checks the threading rule: worker threads touch the UI only
through ``app.call_from_thread``. The ``ui_thread_guard`` fixture records any call to a
UI method made from another thread.
"""

import asyncio
import json
import threading
from unittest.mock import MagicMock

import pytest
from textual.app import App
from textual.widget import Widget
from textual.widgets import Static

from .test_tui import (
    _drive_poll,
    _make_app,
    _monitor_entries,
    _page_zero_batches,
    _start_monitor_without_loop,
    _wait_for,
)

_UI_METHODS = [
    (Widget, "refresh"),
    (Widget, "mount"),
    (Widget, "remove"),
    (Widget, "add_class"),
    (Widget, "remove_class"),
    (Static, "update"),
    (App, "notify"),
]


@pytest.fixture(autouse=True)
def ui_thread_guard(monkeypatch):
    """Record every UI call made off the main (UI) thread, and fail the test on any."""
    ui_thread = threading.main_thread()
    violations: list[str] = []

    for cls, name in _UI_METHODS:
        real = getattr(cls, name)

        def guarded(self, *args, _real=real, _name=f"{cls.__name__}.{name}", **kwargs):
            if threading.current_thread() is not ui_thread:
                violations.append(f"{_name} on {threading.current_thread().name}")
            return _real(self, *args, **kwargs)

        monkeypatch.setattr(cls, name, guarded)
    yield violations
    assert violations == [], violations


class _Gate:
    """Hold a worker inside a call until the test lets it go."""

    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.done: list[threading.Event] = []
        self.threads: list[str] = []

    def wrap(self, real):
        def held(*args, **kwargs):
            done = threading.Event()
            self.done.append(done)
            self.threads.append(threading.current_thread().name)
            self.entered.set()
            try:
                assert self.release.wait(10), "the test never released the gate"
                return real(*args, **kwargs)
            finally:
                done.set()

        return held

    async def wait_entered(self) -> None:
        assert await asyncio.to_thread(self.entered.wait, 10)

    async def finish(self) -> None:
        """Release the held calls and wait until each has returned."""
        self.release.set()
        for done in self.done:
            assert await asyncio.to_thread(done.wait, 10)
        await asyncio.sleep(0.2)  # let the worker's last call_from_thread run or fail


async def test_the_guard_catches_a_ui_call_from_a_thread(ui_thread_guard) -> None:
    widget = Static()
    await asyncio.to_thread(widget.add_class, "x")
    assert len(ui_thread_guard) == 1
    assert ui_thread_guard[0].startswith("Widget.add_class on ")
    ui_thread_guard.clear()  # this one was on purpose


# ---------------------------------------------------------------------------
# Every view's worker, with the guard on


async def test_every_view_loads_without_touching_the_ui_from_a_thread(mock_app_state) -> None:
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 42), notifications=True) as pilot:
        for key in "dlsac":
            await pilot.press(key)
            await pilot.pause()
            view = app._screens[app._current_screen]
            view.refresh_data()
            await app.workers.wait_for_complete()
            await pilot.pause()
    assert app._exception is None


# ---------------------------------------------------------------------------
# An export running while the monitor polls


async def test_an_export_and_monitor_polls_run_side_by_side(
    mock_app_state, sample_audit_entries, tmp_path, monkeypatch
) -> None:
    import cja_audit_log_monitor.tui.modals.export_dialog as dialog_module
    from cja_audit_log_monitor.tui.widgets import LogTable

    gate = _Gate()
    monkeypatch.setattr(dialog_module, "export_entries", gate.wrap(dialog_module.export_entries))
    mock_app_state.page_loaded = True
    mock_app_state.entries = sample_audit_entries
    mock_app_state.client.get_logs.side_effect = _page_zero_batches(
        [_monitor_entries(0, 3), _monitor_entries(3, 2), _monitor_entries(5, 2)]
    )
    app = _make_app(mock_app_state)
    target = tmp_path / "side.json"
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        await _drive_poll(screen, pilot)  # the first poll seeds the seen keys
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#output-path").value = str(target)
        await pilot.click("#export-button")
        await gate.wait_entered()
        # The export is mid-write. Two polls run and land in the table meanwhile.
        await _drive_poll(screen, pilot)
        await _drive_poll(screen, pilot)
        assert screen._state.monitor.entries_since_start == 4
        await gate.finish()
        assert await _wait_for(
            lambda: any("exported" in n.message for n in app._notifications), pilot
        )
        await pilot.press("escape")
        await pilot.pause()
        table = screen.query_one("#monitor-log", LogTable)
        assert table.row_count == 7
        screen._stop_monitoring()
    assert json.loads(target.read_text())["count"] == len(sample_audit_entries)
    assert app._exception is None


# ---------------------------------------------------------------------------
# A settings reload during a load


async def test_a_load_sent_before_a_reload_does_not_land_after_it(
    mock_app_state, monkeypatch
) -> None:
    """The dashboard's old load is dropped; the load after the reload is shown."""
    from cja_audit_log_monitor.tui.screens.dashboard import DashboardView

    monkeypatch.setattr(mock_app_state, "refresh_client", lambda: None)  # keep the mock
    config_reads: list[int] = []
    monkeypatch.setattr(
        "cja_audit_log_monitor.tui.state.load_config",
        lambda path: config_reads.append(1) or mock_app_state.settings,
    )
    gate = _Gate()
    calls = {"n": 0}
    real_fetch = DashboardView._fetch

    def fetch(self):
        calls["n"] += 1
        if calls["n"] == 1:
            return gate.wrap(real_fetch)(self)  # the old load: held until after the reload
        return real_fetch(self)

    monkeypatch.setattr(DashboardView, "_fetch", fetch)
    mock_app_state.verify_connection = MagicMock(return_value={"connected": True, "org_id": "o"})
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 42), notifications=True) as pilot:
        await pilot.pause()
        dash = app._screens["dashboard"]
        dash.refresh_data()
        await gate.wait_entered()
        await pilot.press("c")
        await pilot.pause()
        app.query_one("#reload-button").press()
        assert await _wait_for(
            lambda: any("settings reloaded" in n.message for n in app._notifications), pilot
        )
        applied: list[object] = []
        real_update = dash._update_stats
        monkeypatch.setattr(
            dash, "_update_stats", lambda *a, **k: applied.append(a) or real_update(*a, **k)
        )
        await gate.finish()
        await app.workers.wait_for_complete()
        await pilot.pause()
        # The reload started a fresh dashboard load; only that one is shown.
        assert calls["n"] == 2
        assert len(applied) == 1
        assert config_reads == [1]
    assert app._exception is None


# ---------------------------------------------------------------------------
# Quitting during each kind of worker


async def _quit_and_release(app, pilot, gate: _Gate) -> None:
    await gate.wait_entered()
    await pilot.press("q")
    await pilot.pause()


@pytest.mark.parametrize("view", ["dashboard", "logs", "stats", "settings"])
async def test_quitting_during_a_view_load(mock_app_state, monkeypatch, view) -> None:
    gate = _Gate()
    client = mock_app_state.client
    for name in ("get_logs_sample", "get_logs", "verify_connection"):
        monkeypatch.setattr(client, name, gate.wrap(getattr(client, name)))
    monkeypatch.setattr(
        mock_app_state, "verify_connection", gate.wrap(mock_app_state.verify_connection)
    )
    app = _make_app(mock_app_state)
    keys = {"dashboard": "d", "logs": "l", "stats": "s", "settings": "c"}
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.press(keys[view])
        await pilot.pause()
        app._screens[app._current_screen].refresh_data()
        await _quit_and_release(app, pilot, gate)
    await gate.finish()
    assert app._exception is None


async def test_quitting_during_a_monitor_poll(mock_app_state, monkeypatch) -> None:
    gate = _Gate()
    mock_app_state.client.get_logs.side_effect = _page_zero_batches(
        [_monitor_entries(0, 2), _monitor_entries(2, 2)]
    )
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        await _drive_poll(screen, pilot)
        monkeypatch.setattr(
            mock_app_state.client, "get_logs", gate.wrap(mock_app_state.client.get_logs)
        )
        poll = asyncio.create_task(asyncio.to_thread(screen._guarded_poll, screen._stop_event))
        await _quit_and_release(app, pilot, gate)
    await gate.finish()
    await poll
    assert app._exception is None


@pytest.mark.parametrize("scope_all", [False, True])
async def test_quitting_during_an_export(
    mock_app_state, sample_audit_entries, tmp_path, monkeypatch, scope_all
) -> None:
    import cja_audit_log_monitor.tui.modals.export_dialog as dialog_module

    gate = _Gate()
    if scope_all:
        client = mock_app_state.client
        monkeypatch.setattr(client, "get_logs_sample", gate.wrap(client.get_logs_sample))
    else:
        monkeypatch.setattr(
            dialog_module, "export_entries", gate.wrap(dialog_module.export_entries)
        )
    mock_app_state.page_loaded = True
    mock_app_state.entries = sample_audit_entries
    app = _make_app(mock_app_state)
    target = tmp_path / "quit.json"
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("e")
        await pilot.pause()
        if scope_all:
            app.screen.query_one("#scope-all").value = True
            await pilot.pause()
        app.screen.query_one("#output-path").value = str(target)
        await pilot.click("#export-button")
        await _quit_and_release(app, pilot, gate)
    await gate.finish()
    assert app._exception is None


async def test_quitting_while_alert_rules_load(mock_app_state, monkeypatch) -> None:
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 42)) as pilot:
        await pilot.press("a")
        await pilot.press("q")
        await pilot.pause()
    assert app._exception is None


# ---------------------------------------------------------------------------
# Closing the export dialog while it fetches cancels the export


@pytest.mark.parametrize("outcome", ["succeeds", "fails"])
async def test_closing_the_dialog_during_the_fetch_cancels_the_export(
    mock_app_state, sample_audit_entries, tmp_path, monkeypatch, outcome
) -> None:
    """Whether the fetch then works or fails, nothing is written and one toast says so."""
    from cja_audit_log_monitor.tui.modals import ExportDialog

    gate = _Gate()
    client = mock_app_state.client

    def fetch(*args, **kwargs):
        if outcome == "fails":
            raise RuntimeError("connection reset")
        return sample_audit_entries, len(sample_audit_entries)

    monkeypatch.setattr(client, "get_logs_sample", gate.wrap(fetch))
    mock_app_state.page_loaded = True
    mock_app_state.entries = sample_audit_entries
    app = _make_app(mock_app_state)
    target = tmp_path / "x.json"
    async with app.run_test(size=(120, 40), notifications=True) as pilot:
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#scope-all").value = True
        await pilot.pause()
        app.screen.query_one("#output-path").value = str(target)
        await pilot.click("#export-button")
        await gate.wait_entered()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ExportDialog)
        await gate.finish()

        def cancelled() -> list[str]:
            return [n.message for n in app._notifications if n.message == "export cancelled"]

        assert await _wait_for(lambda: len(cancelled()) >= 1, pilot)
        assert len(cancelled()) == 1
        assert [n for n in app._notifications if n.severity == "error"] == []
        assert app.is_running
    assert not target.exists()
    assert app._exception is None


async def test_closing_the_dialog_during_the_write_still_writes_the_file(
    mock_app_state, sample_audit_entries, tmp_path, monkeypatch
) -> None:
    """Once the write has started it finishes, and the toast says where, not "cancelled"."""
    from cja_audit_log_monitor.tui.modals import ExportDialog, export_dialog

    gate = _Gate()
    monkeypatch.setattr(export_dialog, "export_entries", gate.wrap(export_dialog.export_entries))
    mock_app_state.page_loaded = True
    mock_app_state.entries = sample_audit_entries
    app = _make_app(mock_app_state)
    target = tmp_path / "x.json"
    async with app.run_test(size=(120, 40), notifications=True) as pilot:
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#scope-all").value = True
        await pilot.pause()
        app.screen.query_one("#output-path").value = str(target)
        await pilot.click("#export-button")
        await gate.wait_entered()
        await pilot.press("escape")
        await pilot.pause()
        assert not isinstance(app.screen, ExportDialog)
        await gate.finish()
        messages = lambda: [n.message for n in app._notifications]  # noqa: E731
        assert await _wait_for(lambda: any(m.startswith("exported") for m in messages()), pilot)
        assert "export cancelled" not in messages()
    assert target.exists()
    assert app._exception is None


def test_the_cancelled_toast_is_dropped_once_the_app_has_quit() -> None:
    from cja_audit_log_monitor.tui.modals.export_dialog import _say_cancelled

    app = MagicMock()
    app.call_from_thread.side_effect = RuntimeError("App is not running")
    _say_cancelled(app)  # no error
    app.call_from_thread.assert_called_once()
