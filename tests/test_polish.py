"""Polish: text fits its row, no home folder path in the UI, and one wording style."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.cells import cell_len
from textual.widgets import Static

from .test_tui import _make_app, _wait_for

# ---------------------------------------------------------------------------
# Text fits its row


async def test_recent_alerts_are_cut_by_cells_not_characters(mock_app_state) -> None:
    """A CJK or emoji summary takes two cells a character; it must not wrap."""
    from cja_audit_log_monitor.tui.widgets import AlertSummary

    app = _make_app(mock_app_state)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.press("m")
        await pilot.pause()
        summary = app.query_one("#alert-summary", AlertSummary)
        summary.add_alert("bulk delete: 12 by " + "山田太郎" * 20)
        summary.add_alert("export: 3 by " + "\U0001f680" * 40)
        summary.add_alert("plain ascii line " + "x" * 100)
        await pilot.pause()
        width = summary.content_region.width
        lines = str(summary.render()).splitlines()
        assert len(lines) == 4  # the heading and one row for each alert
        for line in lines:
            assert cell_len(line) <= width, line


async def test_a_long_error_in_the_header_stays_on_one_row(mock_app_state) -> None:
    app = _make_app(mock_app_state)
    async with app.run_test(size=(80, 24)) as pilot:
        await pilot.pause()
        app.set_connection_status("disconnected", "connection refused " * 10)
        await pilot.pause()
        row = app.query_one("#status-row", Static)
        assert row.size.height == 1
        assert str(row.render()).rstrip().endswith("…")
        # A wider window shows more of the error again.
        await pilot.resize_terminal(200, 40)
        await pilot.pause()
        assert len(str(row.render())) > 100


# ---------------------------------------------------------------------------
# No home folder path in the UI


async def test_export_toast_shows_the_home_folder_as_a_tilde(
    mock_app_state, sample_audit_entries, monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    mock_app_state.page_loaded = True
    mock_app_state.entries = sample_audit_entries
    app = _make_app(mock_app_state)
    async with app.run_test(size=(120, 40), notifications=True) as pilot:
        await pilot.press("e")
        await pilot.pause()
        app.screen.query_one("#output-path").value = str(tmp_path / "out.json")
        await pilot.click("#export-button")
        assert await _wait_for(
            lambda: any("exported" in n.message for n in app._notifications), pilot
        )
        message = next(n.message for n in app._notifications if "exported" in n.message)
    assert message.endswith("to ~/out.json")
    assert str(tmp_path) not in message


def test_export_path_problems_show_the_home_folder_as_a_tilde(monkeypatch, tmp_path) -> None:
    from cja_audit_log_monitor.export import check_export_path

    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    _, problem, _ = check_export_path(str(tmp_path / "missing" / "x.json"))
    assert problem == "folder does not exist: ~/missing"


# ---------------------------------------------------------------------------
# One wording style: lowercase, "·" between a headline and its detail


def test_settings_card_handles_a_missing_log_count(mock_app_state) -> None:
    """Formatting 'N/A' with a thousands separator used to raise ValueError."""
    from cja_audit_log_monitor.tui.screens.settings import SettingsView

    view = SettingsView(mock_app_state)
    status = MagicMock()
    view.query_one = MagicMock(return_value=status)
    view._app = MagicMock()
    monkey_app = MagicMock()
    type(view).app = property(lambda self: monkey_app)
    try:
        view._update_connection_status({"connected": True, "authenticated": True})
    finally:
        del type(view).app
    assert "total logs available: -" in status.update.call_args.args[0]


async def test_settings_card_says_not_connected_like_the_views(mock_app_state) -> None:
    mock_app_state.verify_connection = MagicMock(
        return_value={"connected": False, "error": "offline"}
    )
    app = _make_app(mock_app_state)
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.press("c")
        await pilot.pause()
        app._screens["settings"].refresh_data()
        await app.workers.wait_for_complete()
        await pilot.pause()
        text = str(app.query_one("#connection-status", Static).render())
    assert "not connected · offline" in text
    assert "error:" not in text


async def test_monitor_texts_use_the_shared_style(mock_app_state, monkeypatch) -> None:
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        await pilot.press("m")
        await pilot.pause()
        screen = app._screens["monitor"]
        info = str(app.query_one("#stats-info", Static).render())
        assert "—" not in info  # no em dash for "no check yet"
        assert screen.refresh_data() is False
        screen.query_one("#interval-input").value = "1"
        screen._show_error("boom")
        await pilot.pause()
        messages = [n.message for n in app._notifications]
    assert "the monitor is stopped · press space to start it" in messages
    assert "monitor error · boom" in messages


@pytest.mark.parametrize("enabled,word", [(True, "on"), (False, "off")])
async def test_rule_toggle_toast_is_lowercase(mock_app_state, enabled, word) -> None:
    from cja_audit_log_monitor.alerts import AlertEngine
    from cja_audit_log_monitor.models import AlertRule

    mock_app_state._alert_engine = AlertEngine([AlertRule(name="deletes", enabled=not enabled)])
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 42), notifications=True) as pilot:
        await pilot.press("a")
        await pilot.pause()
        app._screens["alerts"].refresh_data()
        await app.workers.wait_for_complete()
        await pilot.pause()
        app.query_one("#rule-0").value = enabled
        await pilot.pause()
        messages = [n.message for n in app._notifications]
    assert f"rule deletes {word}" in messages


async def test_a_failed_alert_test_toast_names_the_test(mock_app_state) -> None:
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 42), notifications=True) as pilot:
        await pilot.press("a")
        await pilot.pause()
        app._screens["alerts"].show_load_error(RuntimeError("timed out"))
        await pilot.pause()
        messages = [n.message for n in app._notifications]
    assert "test failed · timed out" in messages
