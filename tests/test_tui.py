"""Tests for the TUI module."""

import io
import os
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from textual.color import Color
from textual.widgets import Button, Checkbox, Static

from cja_audit_log_monitor.alerts import FiredAlert
from cja_audit_log_monitor.config import ConfigError
from cja_audit_log_monitor.models import AlertRule, AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.notifications import NotificationManager
from cja_audit_log_monitor.tui.app import CJAAuditApp, HelpScreen
from cja_audit_log_monitor.tui.state import AppState

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_app(mock_app_state) -> CJAAuditApp:
    """Create a CJAAuditApp with mocked state (bypasses real config/client)."""
    app = CJAAuditApp()
    app.state = mock_app_state
    return app


# Patch on_content_mounted on views that launch data-loading workers, so tests that only
# check layout/navigation don't race background threads. Tests that need real workers
# run them explicitly.
_SCREEN_WORKER_PATCHES = [
    "cja_audit_log_monitor.tui.screens.dashboard.DashboardScreen.on_content_mounted",
    "cja_audit_log_monitor.tui.screens.log_browser.LogBrowserScreen.on_content_mounted",
    "cja_audit_log_monitor.tui.screens.settings.SettingsScreen.on_content_mounted",
    "cja_audit_log_monitor.tui.screens.stats.StatsScreen.on_content_mounted",
]


def _noop(*args, **kwargs):
    """No-op replacement for on_content_mounted to suppress workers."""
    pass


@pytest.fixture(autouse=True)
def _patch_screen_workers(request):
    """Patch screen on_content_mounted workers for all TUI tests.

    A test marked ``real_mount`` keeps the real hooks, so views load as in the real app.
    """
    if request.node.get_closest_marker("real_mount"):
        yield
        return
    patchers = [patch(p, _noop) for p in _SCREEN_WORKER_PATCHES]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# TestNotificationDispatch
# ---------------------------------------------------------------------------


class TestLazyClientCreation:
    """AppState.client is built once even when worker threads race for it."""

    def test_concurrent_access_builds_one_client(self, monkeypatch):
        import threading
        import time

        created: list[object] = []

        class SlowClient:
            def __init__(self, settings, token_manager):
                time.sleep(0.05)
                created.append(self)

            def close(self):
                pass

        monkeypatch.setattr("cja_audit_log_monitor.tui.state.AuditLogsClient", SlowClient)
        monkeypatch.setattr(
            "cja_audit_log_monitor.tui.state.TokenManager", lambda settings: object()
        )
        state = AppState()
        state._settings = MagicMock()
        barrier = threading.Barrier(8)
        seen: list[object] = []

        def grab():
            barrier.wait()
            seen.append(state.client)

        threads = [threading.Thread(target=grab) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(created) == 1
        assert len({id(c) for c in seen}) == 1


class TestNotificationDispatch:
    """Tests for AppState notification_manager wiring and dispatch."""

    def test_notification_manager_lazy_property(self, tmp_path):
        """notification_manager is constructed once and reused."""
        state = AppState(config_path=tmp_path / "config.yaml")
        nm1 = state.notification_manager
        nm2 = state.notification_manager
        assert isinstance(nm1, NotificationManager)
        assert nm1 is nm2

    def test_check_alerts_dispatches_when_configured(self, sample_audit_entry):
        """state.check_alerts calls notify_alert per FiredAlert when channels configured."""
        state = AppState()
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.pop_failures.return_value = []
        state._notification_manager = fake_nm

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        state._alert_engine = MagicMock()
        state._alert_engine.check_batch.return_value = [fa]

        state.check_alerts([sample_audit_entry])
        fake_nm.notify_alert.assert_called_once_with("r", "m", sample_audit_entry)

    def test_check_alerts_skips_dispatch_when_unconfigured(self, sample_audit_entry):
        """state.check_alerts does NOT call notify_alert when no channels configured."""
        state = AppState()
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = False
        state._notification_manager = fake_nm

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        state._alert_engine = MagicMock()
        state._alert_engine.check_batch.return_value = [fa]

        state.check_alerts([sample_audit_entry])
        fake_nm.notify_alert.assert_not_called()

    def test_check_alerts_suppresses_dispatch_exceptions(self, sample_audit_entry):
        """An exception inside notify_alert does NOT prevent check_alerts from returning."""
        state = AppState()
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.notify_alert.side_effect = RuntimeError("boom")
        fake_nm.pop_failures.return_value = []
        state._notification_manager = fake_nm

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        state._alert_engine = MagicMock()
        state._alert_engine.check_batch.return_value = [fa]

        fired = state.check_alerts([sample_audit_entry])
        assert len(fired) == 1  # check_alerts still returns despite the exception


# ---------------------------------------------------------------------------
# TestAppLifecycle
# ---------------------------------------------------------------------------


class TestAppLifecycle:
    """Test basic application lifecycle."""

    async def test_app_launches(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as _pilot:
            assert app.title == "CJA Audit Log Monitor"

    async def test_dashboard_shown_by_default(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app._current_screen == "dashboard"

    async def test_sidebar_has_six_nav_items(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as _pilot:
            nav_items = app.query("#sidebar .nav-item")
            assert len(nav_items) == 6

    async def test_main_content_shows_dashboard_view(self, mock_app_state):
        from textual.widgets import ContentSwitcher

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            switcher = app.query_one("#main-content", ContentSwitcher)
            assert switcher.current == "view-dashboard"

    async def test_quit_calls_state_close(self, mock_app_state):
        mock_app_state.close = MagicMock()
        app = _make_app(mock_app_state)
        async with app.run_test() as _pilot:
            app.action_quit()
            mock_app_state.close.assert_called_once()


# ---------------------------------------------------------------------------
# TestViewRendering — regression for blank main pane (views had zero region)
# ---------------------------------------------------------------------------


class TestViewRendering:
    """Views must be laid out with a real, nonzero region."""

    @pytest.mark.parametrize(
        "key,name",
        [
            ("d", "dashboard"),
            ("l", "logs"),
            ("m", "monitor"),
            ("s", "stats"),
            ("a", "alerts"),
            ("c", "settings"),
        ],
    )
    async def test_each_view_has_nonzero_region(self, mock_app_state, key, name):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press(key)
            await pilot.pause()
            assert app._screens[name].region.area > 0

    async def test_revisit_keeps_same_instance_no_remount(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            for key in ("l", "d", "l"):
                await pilot.press(key)
                await pilot.pause()
            views = app.query("#main-content > #view-logs")
            assert len(views) == 1
            assert views.first() is app._screens["logs"]

    async def test_on_content_mounted_called_once_per_view(self, mock_app_state):
        hook = MagicMock()
        with patch(
            "cja_audit_log_monitor.tui.screens.log_browser.LogBrowserScreen.on_content_mounted",
            hook,
        ):
            app = _make_app(mock_app_state)
            async with app.run_test() as pilot:
                for key in ("l", "d", "l"):
                    await pilot.press(key)
                    await pilot.pause()
        assert hook.call_count == 1

    async def test_slash_from_dashboard_focuses_logs_search(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            assert app._current_screen == "logs"
            assert app.focused is not None and app.focused.id == "filter-search"


# ---------------------------------------------------------------------------
# TestConnectionHeader
# ---------------------------------------------------------------------------


def _status_text(app) -> str:
    return str(app.query_one("#status-row", Static).render())


class TestConnectionHeader:
    """The header reports the real connection state."""

    async def test_header_starts_connecting(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as _pilot:
            assert "connecting" in _status_text(app)

    async def test_set_connection_status_disconnected_shows_error(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            app.set_connection_status("disconnected", "invalid_client")
            await pilot.pause()
            text = _status_text(app)
            assert "disconnected" in text
            assert "invalid_client" in text
            assert "● connected" not in text

    async def test_dashboard_has_no_duplicate_status(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert len(app.query("#connection-status")) == 0


# ---------------------------------------------------------------------------
# TestCharts
# ---------------------------------------------------------------------------


class TestCharts:
    """Chart widgets render colored, compact output."""

    async def test_hourly_chart_has_axis_and_six_rows(self, mock_app_state):
        from cja_audit_log_monitor.tui.widgets import HourlyChart

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            chart = HourlyChart()
            await app.query_one("#sidebar").mount(chart)
            chart.update_data({h: h + 1 for h in range(24)})
            await pilot.pause()
            lines = str(chart.render()).splitlines()
            assert len(lines) == 7
            assert lines[-1].lstrip().startswith("00")

    def test_action_chart_bar_uses_action_color(self):
        from cja_audit_log_monitor.formatters import TCSS_TOKEN_HEX
        from cja_audit_log_monitor.tui.widgets import ActionBarChart

        chart = ActionBarChart()
        markup = chart.build_markup({"DELETE": 4, "EDIT": 8}, width=10)
        danger = TCSS_TOKEN_HEX["$danger"]
        delete_line = next(line for line in markup.splitlines() if "DELETE" in line)
        assert f"[{danger}]█" in delete_line


# ---------------------------------------------------------------------------
# TestCompactControls
# ---------------------------------------------------------------------------


class TestCompactControls:
    """Buttons, inputs and the filter bar take one row each."""

    async def test_filter_bar_single_row(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            row = app.query_one("#filter-bar Horizontal")
            children = list(row.children)
            assert children
            assert all(c.region.height == 1 for c in children)
            assert len({c.region.y for c in children}) == 1

    @pytest.mark.parametrize(
        "key,selector",
        [
            ("d", "#refresh-button"),
            ("m", "#start-button"),
            ("a", "#test-rules"),
            ("c", "#verify-button"),
            ("s", "#update-button"),
        ],
    )
    async def test_toolbar_buttons_height_one(self, mock_app_state, key, selector):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press(key)
            await pilot.pause()
            view = app._screens[app._current_screen]
            assert view.query_one(selector).region.height == 1

    async def test_pagination_single_row(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            assert app.query_one("#pagination").region.height == 1


# ---------------------------------------------------------------------------
# TestEmptyStatesAndLayout — these run the views' real data workers
# ---------------------------------------------------------------------------


async def _show_and_load(app, pilot, key: str):
    """Navigate to a view and run its data worker to completion."""
    await pilot.press(key)
    await pilot.pause()
    view = app._screens[app._current_screen]
    view.refresh_data()
    await app.workers.wait_for_complete()
    await pilot.pause()
    return view


def _plain(widget) -> str:
    """A Static's content as plain text, whether it holds markup or a Rich renderable."""
    from rich.console import Console

    console = Console(file=io.StringIO(), width=200, record=True, color_system=None)
    console.print(widget.content)
    return console.export_text()


def _empty_text(view) -> str:
    return str(view.query_one("#empty-state", Static).render())


class TestEmptyStatesAndLayout:
    """Views explain missing data instead of showing blank space."""

    async def test_dashboard_empty_state_when_disconnected(self, mock_app_state):
        mock_app_state.client.verify_connection.return_value = {
            "connected": False,
            "authenticated": False,
            "error": "invalid_client",
        }
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            empty = view.query_one("#empty-state", Static)
            assert empty.display
            assert not view.query_one("#view-body").display
            assert "invalid_client" in _empty_text(view)
            assert "press c" in _empty_text(view)

    async def test_dashboard_empty_state_zero_entries(self, mock_app_state):
        mock_app_state.client.get_logs_sample.return_value = ([], len([]))
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            assert view.query_one("#empty-state", Static).display
            assert "no audit activity in the last 7 days" in _empty_text(view)

    async def test_dashboard_with_data_hides_empty_state(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            assert not view.query_one("#empty-state", Static).display
            assert view.query_one("#view-body").display

    async def test_dashboard_two_columns(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            left = view.query_one("#dash-left").region
            right = view.query_one("#dash-right").region
            assert left.y == right.y
            assert right.x > left.x

    async def test_top_users_fit_column_at_100_cols(self, mock_app_state, sample_audit_entry):
        entries = [
            sample_audit_entry.model_copy(
                update={"id": f"e{i}", "user_email": f"someone.with.long.name{i}@example.com"}
            )
            for i in range(5)
        ]
        mock_app_state.client.get_logs_sample.return_value = (entries, len(entries))
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            top = view.query_one("#top-users", Static)
            lines = str(top.render()).splitlines()
            assert lines
            assert all(len(line) <= top.content_region.width for line in lines)

    async def test_stats_empty_state_zero_entries(self, mock_app_state):
        mock_app_state.client.get_logs_sample.return_value = ([], len([]))
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "s")
            assert view.query_one("#empty-state", Static).display
            assert "no audit activity in the last 7 days" in _empty_text(view)

    @pytest.mark.parametrize("key", ["m", "a"])
    async def test_idle_views_show_no_spinner(self, mock_app_state, key):
        from textual.widgets import LoadingIndicator

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press(key)
            await pilot.pause()
            view = app._screens[app._current_screen]
            spinners = view.query(LoadingIndicator)
            assert all(not s.display for s in spinners)


# ---------------------------------------------------------------------------
# TestTableFit
# ---------------------------------------------------------------------------


class TestTableFit:
    """Log tables fill the width without horizontal scrolling."""

    @pytest.mark.parametrize("size", [(100, 30), (140, 42)])
    async def test_log_table_has_no_horizontal_overflow(
        self, mock_app_state, sample_audit_entries, size
    ):
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=size) as pilot:
            await pilot.press("l")
            await pilot.pause()
            table = app.query_one("#log-table", LogTable)
            table.load_entries(sample_audit_entries)
            await pilot.pause()
            assert table.virtual_size.width <= table.scrollable_content_region.width

    @pytest.mark.parametrize("size", [(100, 30), (140, 42)])
    async def test_no_horizontal_scrollbar_when_rows_overflow(
        self, mock_app_state, sample_audit_entry, size
    ):
        from cja_audit_log_monitor.tui.widgets import LogTable

        many = [sample_audit_entry.model_copy(update={"id": f"e{i}"}) for i in range(80)]
        app = _make_app(mock_app_state)
        async with app.run_test(size=size) as pilot:
            await pilot.press("l")
            await pilot.pause()
            table = app.query_one("#log-table", LogTable)
            table.load_entries(many)
            await pilot.pause()
            await pilot.pause()
            assert table.show_vertical_scrollbar
            assert not table.show_horizontal_scrollbar

    async def test_filter_bar_search_usable_at_100_cols(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            search = app.query_one("#filter-search")
            reset = app.query_one("#filter-reset")
            bar = app.query_one("#filter-bar")
            assert search.region.width >= 12
            assert reset.region.right <= bar.region.right

    async def test_name_column_takes_remaining_width(self, mock_app_state, sample_audit_entries):
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=(160, 40)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            table = app.query_one("#log-table", LogTable)
            table.load_entries(sample_audit_entries)
            await pilot.pause()
            assert table.columns["name"].width > 30

    @pytest.mark.parametrize("size", [(80, 24), (100, 30)])
    async def test_log_browser_fits_small_terminals(
        self, mock_app_state, sample_audit_entries, size
    ):
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=size) as pilot:
            await pilot.press("l")
            await pilot.pause()
            view = app._screens["logs"]
            view._update_table(sample_audit_entries, 150)
            await pilot.pause()
            await pilot.pause()
            assert app.query_one("#filter-search").region.width >= 12
            assert app.query_one("#filter-user").region.width >= 12
            bar = app.query_one("#filter-bar")
            assert app.query_one("#filter-reset").region.right <= bar.region.right
            table = app.query_one("#log-table", LogTable)
            assert table.virtual_size.width <= table.scrollable_content_region.width
            count = app.query_one("#entry-count", Static)
            assert "150 entries" in _plain(count)
            assert count.region.right <= app.query_one("#pagination").region.right

    async def test_detail_panel_covers_table_at_80_cols(self, mock_app_state, sample_audit_entries):
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            app._screens["logs"]._update_table(sample_audit_entries, 10)
            await pilot.pause()
            app.query_one("#log-table", LogTable).focus()
            await pilot.press("enter")
            await pilot.pause()
            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
            assert panel.is_visible()
            assert panel.region.width >= 60
            table = app.query_one("#log-table", LogTable)
            assert table.virtual_size.width <= table.scrollable_content_region.width
            assert table.scrollable_content_region.width >= 60

    async def test_detail_panel_open_at_100_cols_keeps_table_readable(
        self, mock_app_state, sample_audit_entry
    ):
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        entries = [
            sample_audit_entry.model_copy(
                update={"id": f"e{i}", "user_email": f"someone.with.long.name{i}@example.com"}
            )
            for i in range(5)
        ]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            app._screens["logs"]._update_table(entries, 5)
            await pilot.pause()
            table = app.query_one("#log-table", LogTable)
            table.focus()
            await pilot.press("enter")
            await pilot.pause()
            await pilot.pause()
            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
            assert panel.is_visible()
            assert panel.region.contains_region(table.region)
            assert table.virtual_size.width <= table.scrollable_content_region.width
            users = [str(table.get_row_at(i)[1]) for i in range(table.row_count)]
            assert all(u.endswith("…") for u in users)
            assert all(len(u) <= table.columns["user"].width for u in users)
            await pilot.press("tab")
            await pilot.pause()
            await pilot.press("escape")
            assert await _wait_for(lambda: not panel.is_visible(), pilot)
            assert await _wait_for(lambda: app.focused is table, pilot)
            assert table.region.width > 0 and table.display

    def test_fit_columns_hides_component_name_then_type(self):
        from cja_audit_log_monitor.tui.widgets import LogTable

        table = LogTable()
        assert table._visible_columns(100) == ["timestamp", "user", "action", "component", "name"]
        narrow = table._visible_columns(70)
        assert "name" not in narrow and "component" in narrow
        assert table._visible_columns(45) == ["timestamp", "user", "action"]

    def test_truncate_uses_width_and_is_plain(self):
        from cja_audit_log_monitor.tui.widgets import LogTable

        assert LogTable._truncate("abcdefghij", 5) == "abcd…"
        assert LogTable._truncate("abc", 5) == "abc"
        assert LogTable._truncate("[bold]x[/bold]yyyy", 6) == "[bold…"

    async def test_monitor_stream_fits_80_cols(self, mock_app_state, sample_audit_entries):
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            table = app.query_one("#monitor-log", LogTable)
            table.append_entries(sample_audit_entries, 100)
            await pilot.pause()
            await pilot.pause()
            assert table.row_count == len(sample_audit_entries)
            assert table.virtual_size.width <= table.scrollable_content_region.width

    def test_long_user_truncated_with_ellipsis(self, sample_audit_entry):
        from cja_audit_log_monitor.tui.widgets import LogTable

        entry = sample_audit_entry.model_copy(
            update={"user_email": "a.very.long.user.name.for.testing@example.com"}
        )
        row = LogTable()._build_row(entry)
        user_cell = str(row[1])
        assert user_cell.endswith("…")
        assert len(user_cell) == LogTable.COLUMN_WIDTHS["user"]


# ---------------------------------------------------------------------------
# TestViewLayouts
# ---------------------------------------------------------------------------


class TestViewLayouts:
    """Stats, alerts and settings layouts use space well."""

    async def test_settings_shows_tilde_path(self, mock_app_state):
        from pathlib import Path

        mock_app_state._config_path = Path.home() / ".cja-audit-log-monitor" / "config.yaml"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("c")
            await pilot.pause()
            view = app._screens["settings"]
            texts = [str(w.render()) for w in view.query(Static)]
            assert not any(str(Path.home()) in t for t in texts)
            assert any("~/.cja-audit-log-monitor/config.yaml" in t for t in texts)

    async def test_stats_charts_side_by_side(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "s")
            action = view.query_one("#stats-action-chart").region
            hourly = view.query_one("#stats-hourly-chart").region
            assert action.y == hourly.y
            assert hourly.x > action.x

    async def test_rule_card_height_at_most_4(self, mock_app_state):
        from cja_audit_log_monitor.models import ActionType

        mock_app_state._alert_engine.rules = [
            AlertRule(
                name="bulk_delete",
                description="Alert on multiple delete operations",
                enabled=True,
                actions=[ActionType.DELETE],
                threshold_count=5,
                threshold_window_minutes=60,
            )
        ]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("a")
            await pilot.pause()
            card = app._screens["alerts"].query_one("#card-0")
            assert 0 < card.region.height <= 4

    async def test_monitor_stream_fills_space(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            assert app._screens["monitor"].query_one("#monitor-log").region.height >= 15


# ---------------------------------------------------------------------------
# TestViewFocusAndScroll — regressions from moving views off textual Screen
# ---------------------------------------------------------------------------


class TestViewFocusAndScroll:
    """Views scroll when short, own their keys, and never leave focus hidden."""

    @pytest.mark.parametrize("key", ["s", "c"])
    async def test_tall_view_body_scrolls_at_100x30(self, mock_app_state, key):
        # 20 rows: shorter than either view's content, so the body must scroll.
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 20)) as pilot:
            view = await _show_and_load(app, pilot, key)
            body = view.query_one("#view-body")
            assert body.max_scroll_y > 0

    @pytest.mark.parametrize("key", ["s", "d"])
    async def test_charts_do_not_wrap_at_100_cols(self, mock_app_state, sample_audit_entry, key):
        from datetime import UTC, datetime

        from cja_audit_log_monitor.tui.widgets import ActionBarChart, HourlyChart

        entries = [
            sample_audit_entry.model_copy(
                update={
                    "id": f"e{i}",
                    "action": ["CREATE", "DELETE", "APPROVE"][i % 3],
                    "timestamp": datetime(2025, 1, 20, i % 24, 0, tzinfo=UTC),
                }
            )
            for i in range(48)
        ]
        mock_app_state.client.get_logs_sample.return_value = (entries, len(entries))
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            view = await _show_and_load(app, pilot, key)
            for chart in (view.query_one(ActionBarChart), view.query_one(HourlyChart)):
                width = chart.content_region.width
                lines = str(chart.render()).splitlines()
                assert lines
                assert all(len(line.rstrip()) <= width for line in lines), (chart.id, width)

    async def test_switching_view_does_not_leave_focus_in_hidden_input(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("slash")
            await pilot.pause()
            await app._show_screen("dashboard")
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            assert app._current_screen == "stats"
            assert app._screens["logs"].query_one("#filter-user").value == ""

    async def test_n_pages_logs_right_after_l(self, mock_app_state):
        mock_app_state.client.get_logs.return_value.total_elements = 120  # 3 pages
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            await pilot.press("n")
            await pilot.pause()
            assert mock_app_state.filters.page == 1

    async def test_space_starts_monitor_right_after_m(self, mock_app_state):
        from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

        async def _no_loop(self, stop):
            return None

        app = _make_app(mock_app_state)
        with patch.object(MonitorScreen, "_monitoring_loop", _no_loop):
            async with app.run_test(size=(140, 40)) as pilot:
                await pilot.press("m")
                await pilot.pause()
                await pilot.press("space")
                await pilot.pause()
                assert mock_app_state.monitor.is_running
                app._screens["monitor"]._stop_monitoring()


# ---------------------------------------------------------------------------
# TestNavigation
# ---------------------------------------------------------------------------


class TestNavigation:
    """Test keyboard and button navigation."""

    @pytest.mark.parametrize(
        "key,expected_screen",
        [
            ("l", "logs"),
            ("m", "monitor"),
            ("s", "stats"),
            ("a", "alerts"),
            ("c", "settings"),
        ],
    )
    async def test_key_switches_screen(self, mock_app_state, key, expected_screen):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press(key)
            await pilot.pause()
            assert app._current_screen == expected_screen

    async def test_key_d_returns_to_dashboard(self, mock_app_state):
        """Navigate away, then press d to return to dashboard."""
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            assert app._current_screen == "logs"
            await pilot.press("d")
            await pilot.pause()
            assert app._current_screen == "dashboard"

    async def test_nav_item_updates_active_class(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            logs_item = app.query_one("#nav-logs", Static)
            assert "active" in logs_item.classes
            dash_item = app.query_one("#nav-dashboard", Static)
            assert "active" not in dash_item.classes

    async def test_sidebar_item_click_navigates(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.click("#nav-stats")
            await pilot.pause()
            assert app._current_screen == "stats"

    async def test_help_screen_opens_on_question_mark(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)

    async def test_help_screen_dismisses_on_escape(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("question_mark")
            await pilot.pause()
            assert isinstance(app.screen, HelpScreen)
            await pilot.press("escape")
            await pilot.pause()
            assert not isinstance(app.screen, HelpScreen)

    async def test_refresh_key_calls_current_screen_refresh(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            log_screen = app._screens["logs"]
            log_screen.refresh_data = MagicMock()
            await pilot.press("r")
            await pilot.pause()
            log_screen.refresh_data.assert_called_once()


# ---------------------------------------------------------------------------
# TestDashboardScreen
# ---------------------------------------------------------------------------


class TestDashboardScreen:
    """Test the Dashboard screen."""

    async def test_dashboard_widgets_exist(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert app.query_one("#stat-total", Static)
            assert app.query_one("#stat-users", Static)
            assert app.query_one("#stat-range", Static)
            assert app.query_one("#stat-alerts", Static)

    async def test_refresh_button_exists(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            btn = app.query_one("#refresh-button", Button)
            assert btn is not None

    async def test_dashboard_title_exists(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            title = app.query_one("#dashboard-title", Static)
            assert title is not None


# ---------------------------------------------------------------------------
# TestLogBrowserScreen
# ---------------------------------------------------------------------------


class TestLogBrowserScreen:
    """Test the Log Browser screen."""

    async def test_log_browser_has_table_and_filter(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            filter_bar = app.query("FilterBar")
            log_table = app.query("LogTable")
            assert len(filter_bar) == 1
            assert len(log_table) == 1

    async def test_pagination_buttons_exist(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            prev_btn = app.query_one("#prev-page", Button)
            next_btn = app.query_one("#next-page", Button)
            assert prev_btn is not None
            assert next_btn is not None

    async def test_log_table_exists_with_cursor_type(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            log_table = app.query_one("LogTable")
            assert log_table.cursor_type == "row"
            assert log_table.zebra_stripes is False

    async def test_loading_indicator_exists(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()
            loading = app.query_one("#logs-loading")
            assert loading is not None


def _track_monitor_loops(monkeypatch):
    """Wrap MonitorScreen._monitoring_loop to record when each loop starts and ends.

    Returns (started, ended): lists that get a threading.Event per loop. The default
    interval of 60 seconds stays in place, so a loop that only notices a stop after its
    sleep takes far longer to end than these tests allow.
    """
    import threading

    from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

    original = MonitorScreen._monitoring_loop
    started: list[threading.Event] = []
    ended: list[threading.Event] = []

    async def tracked(self, *args, **kwargs):
        done = threading.Event()
        ended.append(done)
        started.append(threading.Event())
        started[-1].set()
        try:
            await original(self, *args, **kwargs)
        finally:
            done.set()

    monkeypatch.setattr(MonitorScreen, "_monitoring_loop", tracked)
    return started, ended


async def _wait_for(condition, pilot, timeout: float = 3.0) -> bool:
    """Pause the app until ``condition()`` is true, or ``timeout`` seconds pass."""
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        await pilot.pause(0.05)
    return condition()


def _reloaded(app, times: int = 1) -> bool:
    """True once the config view's reload handler has run to its end ``times`` times."""
    return sum("settings reloaded" in n.message for n in app._notifications) >= times


class TestMonitorScreen:
    """Test the Monitor screen."""

    async def test_stop_ends_the_loop_without_waiting_for_the_interval(
        self, mock_app_state, monkeypatch
    ):
        _started, ended = _track_monitor_loops(monkeypatch)
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app._screens["monitor"]
            screen._start_monitoring()
            assert await _wait_for(lambda: mock_app_state.client.get_logs.called, pilot)
            screen._stop_monitoring()
            assert await _wait_for(lambda: ended[0].is_set(), pilot), (
                "the monitor loop kept sleeping after stop"
            )

    async def test_quitting_ends_the_loop(self, mock_app_state, monkeypatch):
        _started, ended = _track_monitor_loops(monkeypatch)
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            app._screens["monitor"]._start_monitoring()
            assert await _wait_for(lambda: mock_app_state.client.get_logs.called, pilot)
            await pilot.press("q")
        # Python waits for the worker thread before the program can exit.
        assert ended[0].wait(3), "the monitor loop kept running after the app quit"

    async def test_stop_then_start_leaves_one_loop(self, mock_app_state, monkeypatch):
        _started, ended = _track_monitor_loops(monkeypatch)
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app._screens["monitor"]
            screen._start_monitoring()
            assert await _wait_for(lambda: mock_app_state.client.get_logs.called, pilot)
            screen._stop_monitoring()
            screen._start_monitoring()
            assert await _wait_for(lambda: len(ended) == 2, pilot)
            assert await _wait_for(lambda: ended[0].is_set(), pilot), (
                "the first loop resumed after the second start"
            )
            assert not ended[1].is_set()
            screen._stop_monitoring()
            assert await _wait_for(lambda: ended[1].is_set(), pilot)

    async def test_refresh_does_not_start_parallel_poll(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            monitor_screen = app._screens["monitor"]
            monitor_screen._state.monitor.is_running = True
            monitor_screen.run_worker = MagicMock()
            monitor_screen._poll_lock.acquire()
            try:
                monitor_screen.refresh_data()
            finally:
                monitor_screen._poll_lock.release()

            monitor_screen.run_worker.assert_not_called()

    async def test_stop_monitoring_cancels_refresh_worker(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            monitor_screen = app._screens["monitor"]
            monitor_screen._state.monitor.is_running = True
            monitor_worker = MagicMock()
            refresh_worker = MagicMock()
            monitor_screen._monitor_worker = monitor_worker
            monitor_screen._refresh_worker = refresh_worker

            monitor_screen._stop_monitoring()

            monitor_worker.cancel.assert_called_once()
            refresh_worker.cancel.assert_called_once()
            assert monitor_screen._monitor_worker is None
            assert monitor_screen._refresh_worker is None
            assert monitor_screen._state.monitor.is_running is False

    async def test_poll_once_skips_when_stopped(self, mock_app_state):
        import threading

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            monitor_screen = app._screens["monitor"]
            monitor_screen._state.monitor.is_running = False
            polls: list[object] = []
            monitor_screen._guarded_poll = polls.append

            await monitor_screen._poll_once(threading.Event())

            assert polls == []

    async def test_tui_monitor_shows_every_channel_failure(self, mock_app_state, monkeypatch):
        nm = MagicMock()
        nm.pop_failures.side_effect = [[], ["webhook 1 failed", "webhook 2 failed"], [], []]
        nm.is_configured.return_value = False
        mock_app_state._notification_manager = nm
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)  # baseline
            await _drive_poll(screen, pilot)
            messages = lambda: [n.message for n in app._notifications]  # noqa: E731
            assert await _wait_for(
                lambda: "webhook 1 failed" in messages() and "webhook 2 failed" in messages(),
                pilot,
            )
            screen._stop_monitoring()

    async def test_monitor_shows_a_delivery_failure_warning(self, mock_app_state, monkeypatch):
        """A queued delivery failure is drained after a poll and shown as a toast."""
        expected = "Notification delivery failed (slack, hooks.slack.com/...)"
        nm = MagicMock()
        nm.pop_failures.side_effect = [[], [expected], [], []]
        nm.is_configured.return_value = False
        mock_app_state._notification_manager = nm
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)  # baseline
            await _drive_poll(screen, pilot)
            assert await _wait_for(
                lambda: any(expected in n.message for n in app._notifications), pilot
            )
            screen._stop_monitoring()

    async def test_monitor_alert_names_the_user_and_does_not_repeat_the_rule_name(
        self, mock_app_state, monkeypatch
    ):
        from cja_audit_log_monitor.alerts import AlertEngine
        from cja_audit_log_monitor.models import ActionType

        rule = AlertRule(name="any delete", actions=[ActionType.DELETE])
        mock_app_state._alert_engine = AlertEngine([rule])
        delete = AuditLogEntry(
            id="d1",
            action="DELETE",
            user_email="mallory@example.com",
            timestamp=datetime.now(UTC),
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)  # baseline
            mock_app_state.client.get_logs.return_value = _logs_response([delete])
            await _drive_poll(screen, pilot)
            expected = "any delete: any delete by mallory@example.com"
            assert await _wait_for(
                lambda: any(n.message == expected for n in app._notifications), pilot
            )
            assert expected in _plain(screen.query_one("#alert-summary", Static))
            screen._stop_monitoring()


# ---------------------------------------------------------------------------
# TestMonitorStream — the live stream is bounded, ordered and restart-safe
# ---------------------------------------------------------------------------


def _monitor_entries(start: int, count: int) -> list:
    """``count`` entries one second apart, newest first like the API, ids from ``start``."""
    from datetime import UTC, datetime, timedelta

    from cja_audit_log_monitor.models import AuditLogEntry

    base = datetime(2026, 11, 18, 9, 0, tzinfo=UTC)
    entries = [
        AuditLogEntry(
            id=f"m-{i}",
            timestamp=base + timedelta(seconds=i),
            user_id="user-1",
            action="EDIT",
            component_type="PROJECT",
            component_id=f"comp-{i}",
            component_name=f"Component {i}",
        )
        for i in range(start, start + count)
    ]
    return list(reversed(entries))


def _logs_response(entries, **kwargs):
    """An API page. ``last`` is left out unless given, as the live API may do."""
    from cja_audit_log_monitor.models import AuditLogResponse

    return AuditLogResponse(content=entries, **kwargs)


def _page_zero_batches(batches, pages_seen: list | None = None):
    """get_logs side effect: page 0 gives the next batch, later pages are empty."""
    remaining = iter(batches)

    def get_logs(query):
        if pages_seen is not None:
            pages_seen.append(query.page)
        if query.page == 0:
            return _logs_response(next(remaining, []))
        return _logs_response([])

    return get_logs


async def _start_monitor_without_loop(app, pilot, monkeypatch):
    """Show the monitor and start a session whose loop does nothing; tests drive polls."""
    from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

    async def _no_loop(self, stop):
        return None

    monkeypatch.setattr(MonitorScreen, "_monitoring_loop", _no_loop)
    await pilot.press("m")
    await pilot.pause()
    screen = app._screens["monitor"]
    screen._start_monitoring()
    await pilot.pause()
    return screen


async def _drive_poll(screen, pilot) -> None:
    """Run one poll on a worker thread, as the monitor loop does, then let the UI catch up."""
    import asyncio

    await asyncio.to_thread(screen._poll_for_new_entries, screen._stop_event)
    await pilot.pause()


def _status_indicator(screen) -> str:
    return str(screen.query_one("#status-indicator", Static).render())


class TestMonitorStream:
    """The live stream stays bounded and ordered, and its status tells the truth."""

    async def test_tui_failed_poll_keeps_the_poll_window(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.monitor import POLL_OVERLAP

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)  # baseline
            last_good = screen._last_poll_time
            assert last_good is not None
            mock_app_state.client.get_logs.side_effect = [
                RuntimeError("network down"),
                mock_app_state.client.get_logs.return_value,
            ]
            await _drive_poll(screen, pilot)
            await _drive_poll(screen, pilot)
            query = mock_app_state.client.get_logs.call_args.args[0]
            assert query.start_date == last_good - POLL_OVERLAP
            screen._stop_monitoring()

    async def test_tui_backlog_over_limit_reports_skipped_count(self, mock_app_state, monkeypatch):
        import cja_audit_log_monitor.monitor as monitor_module

        monkeypatch.setattr(monitor_module, "MAX_POLL_PAGES", 2)
        page = _monitor_entries(0, 5)
        mock_app_state.client.get_logs.side_effect = None
        mock_app_state.client.get_logs.return_value = AuditLogResponse(
            content=page, total_elements=30, total_pages=6, last=False
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            assert await _wait_for(
                lambda: any(
                    "20 older events in this gap were skipped" in n.message
                    for n in app._notifications
                ),
                pilot,
            )
            screen._stop_monitoring()

    async def test_monitor_query_has_end_date(self, mock_app_state, monkeypatch):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            query = mock_app_state.client.get_logs.call_args.args[0]
            assert query.end_date is not None
            assert query.start_date is not None
            assert query.start_date < query.end_date
            screen._stop_monitoring()

    async def test_monitor_stream_capped(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.screens.monitor import MONITOR_MAX_ROWS
        from cja_audit_log_monitor.tui.widgets import LogTable

        pages_seen: list[int] = []
        mock_app_state.client.get_logs.side_effect = _page_zero_batches(
            [_monitor_entries(n * 100, 100) for n in range(12)], pages_seen
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            for _ in range(12):
                await _drive_poll(screen, pilot)
            table = screen.query_one("#monitor-log", LogTable)
            assert MONITOR_MAX_ROWS == 1000
            assert table.row_count == 1000
            assert len(table._entries) == 1000
            # The first poll is context only, so it is not counted as new.
            assert mock_app_state.monitor.entries_since_start == 1100
            # The oldest rows were the ones dropped.
            assert table.ordered_rows[0].key.value == "m-200"
            assert table.ordered_rows[-1].key.value == "m-1199"
            # Pages carry no `last` flag: after the first poll, a full page of new
            # entries asks for the next page, and the empty page ends the poll.
            assert 1 in pages_seen
            screen._stop_monitoring()

    async def test_monitor_newest_row_last(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.widgets import LogTable

        mock_app_state.client.get_logs.side_effect = _page_zero_batches(
            [_monitor_entries(0, 5), _monitor_entries(3, 5)]
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            table = screen.query_one("#monitor-log", LogTable)
            await _drive_poll(screen, pilot)
            keys = [row.key.value for row in table.ordered_rows]
            assert keys == ["m-0", "m-1", "m-2", "m-3", "m-4"]
            assert table.cursor_row == table.row_count - 1
            # The next poll overlaps the last one: repeats are dropped, the view follows.
            await _drive_poll(screen, pilot)
            keys = [row.key.value for row in table.ordered_rows]
            assert keys == [f"m-{i}" for i in range(8)]
            assert table.cursor_row == table.row_count - 1
            assert mock_app_state.monitor.entries_since_start == 3
            screen._stop_monitoring()

    async def test_restart_during_poll_discards_old_results(self, mock_app_state):
        import threading

        from cja_audit_log_monitor.tui.widgets import LogTable

        release = threading.Event()
        calls: list[int] = []

        def get_logs(query):
            calls.append(query.page)
            if len(calls) == 1:
                release.wait(5)
                return _logs_response(_monitor_entries(0, 5), last=True)
            return _logs_response([], last=True)

        mock_app_state.client.get_logs.side_effect = get_logs
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app._screens["monitor"]
            await pilot.press("space")  # start; the first poll blocks
            assert await _wait_for(lambda: len(calls) == 1, pilot)
            await pilot.press("space")  # stop
            await pilot.press("space")  # start again
            await pilot.pause()
            release.set()
            # The new session polls once the old poll lets go.
            assert await _wait_for(lambda: mock_app_state.monitor.last_check is not None, pilot)
            await pilot.pause()
            assert screen.query_one("#monitor-log", LogTable).row_count == 0
            assert mock_app_state.monitor.entries_since_start == 0
            screen._stop_monitoring()

    async def test_monitor_recovers_connection(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.client import APIError

        good = _logs_response(_monitor_entries(0, 3), last=True)
        mock_app_state.client.get_logs.side_effect = [
            APIError("Connection failed: network unreachable"),
            good,
        ]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            assert "disconnected" in _status_text(app)
            assert "error" in _status_indicator(screen)
            await _drive_poll(screen, pilot)
            header = _status_text(app)
            assert "connected" in header
            assert "disconnected" not in header
            assert "error" not in _status_indicator(screen)
            assert mock_app_state.monitor.last_error is None
            screen._stop_monitoring()

    async def test_monitor_error_state(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.client import APIError

        mock_app_state.client.get_logs.side_effect = [
            _logs_response(_monitor_entries(0, 3), last=True),
            APIError("Server error", status_code=500),
            APIError("Server error", status_code=500),
        ]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            last_check = mock_app_state.monitor.last_check
            assert last_check is not None
            app.notify = MagicMock()
            await _drive_poll(screen, pilot)
            await _drive_poll(screen, pilot)
            assert "error" in _status_indicator(screen)
            assert mock_app_state.monitor.last_check == last_check
            assert mock_app_state.monitor.last_error is not None
            error_toasts = [
                c for c in app.notify.call_args_list if c.kwargs.get("severity") == "error"
            ]
            assert len(error_toasts) == 1
            screen._stop_monitoring()

    async def test_refresh_while_stopped_one_toast(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            app.notify = MagicMock()
            await pilot.press("r")
            await pilot.pause()
            assert app.notify.call_count == 1
            assert "stopped" in app.notify.call_args.args[0].lower()

    async def test_bad_interval_keeps_previous(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            interval_input = app._screens["monitor"].query_one("#interval-input", Input)
            interval_input.focus()
            interval_input.value = ""
            await pilot.pause()
            await pilot.press("enter")
            await pilot.pause()
            assert mock_app_state.monitor.interval == 60
            assert interval_input.has_class("-invalid")
            # Starting with a bad box says which interval it uses instead of hiding it.
            screen = app._screens["monitor"]
            app.notify = MagicMock()
            screen._start_monitoring()
            await pilot.pause()
            assert mock_app_state.monitor.interval == 60
            calls = app.notify.call_args_list
            warnings = [c.args[0] for c in calls if c.kwargs.get("severity") == "warning"]
            assert len(warnings) == 1 and "60" in warnings[0]
            screen._stop_monitoring()

    async def test_huge_interval_is_refused(self, mock_app_state, monkeypatch):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            screen._stop_monitoring()
            await pilot.pause()
            box = screen.query_one("#interval-input", Input)
            box.value = "9999999999"
            await pilot.pause()
            screen._start_monitoring()
            await pilot.pause()
            assert mock_app_state.monitor.interval == 60
            assert any("86,400" in n.message for n in app._notifications)
            screen._stop_monitoring()

    async def test_good_interval_applies_on_enter(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            interval_input = app._screens["monitor"].query_one("#interval-input", Input)
            interval_input.focus()
            interval_input.value = "4"
            await pilot.press("enter")
            await pilot.pause()
            assert mock_app_state.monitor.interval == 60  # below 5 is rejected
            interval_input.value = "30"
            await pilot.press("enter")
            await pilot.pause()
            assert mock_app_state.monitor.interval == 30
            assert not interval_input.has_class("-invalid")

    async def test_interval_box_accepts_values_above_an_hour(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app._screens["monitor"]
            interval_input = screen.query_one("#interval-input", Input)
            interval_input.value = "7200"
            interval_input.validate(interval_input.value)
            assert interval_input.is_valid
            assert screen._apply_interval()
            assert not interval_input.has_class("-invalid")
            assert mock_app_state.monitor.interval == 7200

    async def test_space_in_interval_input_starts_monitor(self, mock_app_state, monkeypatch):
        from textual.widgets import Input

        from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

        async def _no_loop(self, stop):
            return None

        monkeypatch.setattr(MonitorScreen, "_monitoring_loop", _no_loop)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app._screens["monitor"]
            screen.query_one("#interval-input", Input).focus()
            await pilot.pause()
            await pilot.press("space")
            await pilot.pause()
            assert mock_app_state.monitor.is_running
            screen._stop_monitoring()


class TestMonitorPolling:
    """The TUI pages like the CLI, treats the first poll as context, and survives errors."""

    async def test_late_entry_behind_a_seen_page_is_shown(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.widgets import LogTable

        window = _monitor_entries(0, 100)
        late = _monitor_entries(500, 1)
        mock_app_state.client.get_logs.side_effect = [
            _logs_response(window, last=True),
            _logs_response(window),
            _logs_response(late, last=True),
        ]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            await _drive_poll(screen, pilot)
            table = screen.query_one("#monitor-log", LogTable)
            assert table.ordered_rows[-1].key.value == "m-500"
            assert mock_app_state.monitor.entries_since_start == 1
            screen._stop_monitoring()

    async def test_full_window_seeded_then_one_new(self, mock_app_state, monkeypatch):
        window = _monitor_entries(0, 250)
        new_window = _monitor_entries(250, 1) + window
        mock_app_state.client.get_logs.side_effect = [
            _logs_response(window[:100]),
            _logs_response(window[100:200]),
            _logs_response(window[200:], last=True),
            _logs_response(new_window[:100]),
            _logs_response(new_window[100:200]),
            _logs_response(new_window[200:], last=True),
        ]
        engine = mock_app_state.alert_engine
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            await _drive_poll(screen, pilot)
            assert mock_app_state.monitor.entries_since_start == 1
            engine.check_batch.assert_called_once()
            assert [e.id for e in engine.check_batch.call_args.args[0]] == ["m-250"]
            screen._stop_monitoring()

    async def test_first_poll_is_context_only(self, mock_app_state, monkeypatch):
        """Each start shows recent rows but neither alerts nor counts them."""
        from cja_audit_log_monitor.tui.widgets import LogTable

        mock_app_state.client.get_logs.side_effect = _page_zero_batches(
            [_monitor_entries(0, 5), _monitor_entries(0, 5)]
        )
        engine = mock_app_state.alert_engine
        engine.check_batch.return_value = [FiredAlert("bulk_delete", "old", None, None)]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            assert screen.query_one("#monitor-log", LogTable).row_count == 5
            engine.check_batch.assert_not_called()
            assert mock_app_state.monitor.entries_since_start == 0
            assert mock_app_state.monitor.alerts_triggered == 0
            # A stop and start begins a new session, whose first poll is context again.
            screen._stop_monitoring()
            screen._start_monitoring()
            await pilot.pause()
            await _drive_poll(screen, pilot)
            engine.check_batch.assert_not_called()
            assert mock_app_state.monitor.entries_since_start == 0
            screen._stop_monitoring()

    async def test_stop_during_fetch_sends_no_alerts(self, mock_app_state, monkeypatch):
        calls: list[int] = []

        def get_logs(query):
            calls.append(query.page)
            if len(calls) == 2:  # the second poll: the user stops while it fetches
                screen._stop_event.set()
            return _logs_response(_monitor_entries(len(calls) * 10, 3), last=True)

        mock_app_state.client.get_logs.side_effect = get_logs
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            await _drive_poll(screen, pilot)
            mock_app_state.alert_engine.check_batch.assert_not_called()
            screen._stop_monitoring()

    async def test_ui_error_in_a_poll_does_not_crash_the_app(self, mock_app_state, monkeypatch):
        """A bug while showing one poll leaves the app and the monitor loop running."""
        from textual.worker import WorkerState

        from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen
        from cja_audit_log_monitor.tui.widgets import LogTable

        original = MonitorScreen._apply_poll
        raised: list[bool] = []

        def flaky(self, *args, **kwargs):
            if not raised:
                raised.append(True)
                raise RuntimeError("ui bug")
            return original(self, *args, **kwargs)

        monkeypatch.setattr(MonitorScreen, "_apply_poll", flaky)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            screen = app._screens["monitor"]
            app.notify = MagicMock()
            screen._start_monitoring()  # the real loop; it then waits the 60 s interval
            assert await _wait_for(lambda: raised and app.notify.called, pilot)
            await pilot.pause()
            assert app.is_running
            assert screen._monitor_worker.state == WorkerState.RUNNING
            assert mock_app_state.monitor.is_running
            assert "ui bug" in app.notify.call_args.args[0]
            # The next poll works.
            assert screen.refresh_data() is True
            assert await _wait_for(
                lambda: screen.query_one("#monitor-log", LogTable).row_count > 0, pilot
            )
            screen._stop_monitoring()

    async def test_alert_error_is_local_not_disconnect(self, mock_app_state, monkeypatch):
        """A bug in alert code is shown as a local error; the poll itself still counts."""
        from cja_audit_log_monitor.tui.widgets import LogTable

        mock_app_state.client.get_logs.side_effect = _page_zero_batches(
            [_monitor_entries(0, 3), _monitor_entries(0, 5)]
        )
        mock_app_state.alert_engine.check_batch.side_effect = RuntimeError("rule bug")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            app.note_api_error = MagicMock()
            app.notify = MagicMock()
            await _drive_poll(screen, pilot)
            app.note_api_error.assert_not_called()
            assert "error" not in _status_indicator(screen)
            assert mock_app_state.monitor.last_error is None
            assert screen.query_one("#monitor-log", LogTable).row_count == 5
            assert mock_app_state.monitor.entries_since_start == 2
            toasts = [c.args[0] for c in app.notify.call_args_list]
            assert any("rule bug" in t for t in toasts)
            screen._stop_monitoring()


# ---------------------------------------------------------------------------
# TestAlertsScreen
# ---------------------------------------------------------------------------


class TestAlertsScreen:
    """Test the Alerts screen."""

    async def test_refresh_on_alerts_screen_rebuilds_rule_cards_safely(self, mock_app_state):
        mock_app_state._alert_engine.rules = [
            AlertRule(name="rule_one"),
            AlertRule(name="rule_two"),
        ]

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            assert len(app.query("#rules-list .rule-card")) == 2

            # Repeated refreshes should not raise DuplicateIds or duplicate rows.
            await pilot.press("r")
            await pilot.pause()
            await pilot.press("r")
            await pilot.pause()
            assert len(app.query("#rules-list .rule-card")) == 2

    async def test_reset_rules_rebuilds_rule_cards_safely(self, mock_app_state):
        mock_app_state._alert_engine.rules = [AlertRule(name="rule_one")]

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            await pilot.click("#reset-rules")
            await pilot.pause()
            # Reset should rebuild to default rules without crashing.
            assert len(app.query("#rules-list .rule-card")) > 0


class TestAlertsViewRealEngine:
    """The alerts view against a real engine built from settings."""

    @staticmethod
    def _state(mock_app_state, rules):
        mock_app_state.settings.alert_rules = rules
        mock_app_state._alert_engine = None
        return mock_app_state

    async def test_rule_name_with_space_and_markup_mounts(self, mock_app_state):
        state = self._state(
            mock_app_state,
            [AlertRule(name="Bulk delete"), AlertRule(name="[red]odd[/red] name")],
        )
        app = _make_app(state)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            assert len(app.query("#rules-list .rule-card")) == 2
            assert app.query_one("#rule-0", Checkbox)

    async def test_toggle_is_session_only_and_reset_restores(self, mock_app_state):
        state = self._state(mock_app_state, [AlertRule(name="bulk_delete", enabled=True)])
        app = _make_app(state)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            await pilot.click("#rule-0")
            await pilot.pause()
            assert state.alert_engine.rules[0].enabled is False
            assert state.settings.alert_rules[0].enabled is True
            await pilot.click("#reset-rules")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert state.alert_engine.rules[0].enabled is True
            assert app.query_one("#rule-0", Checkbox).value is True

    async def test_reload_settings_rebuilds_rule_cards(self, mock_app_state, tmp_path):
        from unittest.mock import MagicMock

        def write_rules(*names):
            config = tmp_path / "config.yaml"
            config.write_text(
                "alert_rules:\n" + "".join(f"  - name: {n}\n    enabled: true\n" for n in names)
            )
            config.chmod(0o600)

        write_rules("rule_a", "rule_b")
        mock_app_state._settings = None
        mock_app_state._alert_engine = None
        mock_app_state.verify_connection = MagicMock(
            return_value={"connected": False, "error": "offline"}
        )
        app = _make_app(mock_app_state)

        def labels():
            return [str(c.label) for c in app.query("#rules-list Checkbox")]

        async with app.run_test() as pilot:
            await pilot.press("a")
            assert await _wait_for(lambda: labels() == ["rule_a", "rule_b"], pilot), labels()
            write_rules("rule_c", "rule_d", "rule_e")
            await pilot.press("c")
            await pilot.pause()
            app.query_one("#reload-button", Button).press()
            assert await _wait_for(
                lambda: any("settings reloaded" in n.message for n in app._notifications), pilot
            )
            await pilot.press("a")
            assert await _wait_for(lambda: labels() == ["rule_c", "rule_d", "rule_e"], pilot)
            app.query_one("#rule-0", Checkbox).toggle()
            assert await _wait_for(
                lambda: mock_app_state.alert_engine.rules[0].enabled is False, pilot
            )
            rules = mock_app_state.alert_engine.rules
            assert [r.name for r in rules] == ["rule_c", "rule_d", "rule_e"]
            assert [r.enabled for r in rules] == [False, True, True]

    async def test_test_rules_does_not_touch_live_history(self, mock_app_state):
        state = self._state(mock_app_state, [AlertRule(name="any")])
        app = _make_app(state)
        with patch.object(type(state.notification_manager), "notify_alert") as notify:
            async with app.run_test() as pilot:
                await pilot.press("a")
                await pilot.pause()
                await pilot.click("#test-rules")
                await app.workers.wait_for_complete()
                await pilot.pause()
                assert len(state.alert_engine._event_history) == 0
                assert state._client.get_all_logs.called
                assert not notify.called

    async def test_failed_test_rules_shows_error_in_results(self, mock_app_state):
        state = self._state(mock_app_state, [AlertRule(name="any")])
        state._client.get_all_logs.side_effect = RuntimeError("boom [x]")
        app = _make_app(state)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            await pilot.click("#test-rules")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert "boom [x]" in _plain(app.query_one("#test-results", Static))

    async def test_refresh_keeps_focus_on_same_rule(self, mock_app_state):
        state = self._state(mock_app_state, [AlertRule(name="a"), AlertRule(name="b")])
        app = _make_app(state)
        async with app.run_test() as pilot:
            await pilot.press("a")
            await pilot.pause()
            app.query_one("#rule-1", Checkbox).focus()
            await pilot.pause()
            await pilot.press("r")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.focused is not None and app.focused.id == "rule-1"


# ---------------------------------------------------------------------------
# TestSettingsScreen
# ---------------------------------------------------------------------------


class TestSettingsScreen:
    """Test the Settings screen."""

    async def test_config_sections_displayed(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            sections = app.query(".settings-section")
            # Connection, API, Auth, Defaults, Alerts sections
            assert len(sections) >= 4

    async def test_settings_labels_present(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            labels = app.query(".settings-label")
            assert len(labels) > 0

    async def test_verify_button_exists(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            btn = app.query_one("#verify-button", Button)
            assert btn is not None

    async def test_reload_settings_rereads_the_config_file(self, mock_app_state, tmp_path):
        from unittest.mock import MagicMock

        config = tmp_path / "config.yaml"
        config.write_text("monitor_interval: 30\n")
        mock_app_state.verify_connection = MagicMock(
            return_value={"connected": False, "error": "offline"}
        )
        app = _make_app(mock_app_state)

        def shown_values():
            return [str(s.render()) for s in app.query(".settings-value")]

        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            app.query_one("#reload-button", Button).press()
            assert await _wait_for(lambda: "30 seconds" in shown_values(), pilot)
            config.write_text("monitor_interval: 45\n")
            app.query_one("#reload-button", Button).press()
            assert await _wait_for(lambda: "45 seconds" in shown_values(), pilot)
            assert "30 seconds" not in shown_values()
            assert await _wait_for(lambda: _reloaded(app, 2), pilot)

    async def test_reload_settings_is_refused_while_monitoring(self, mock_app_state):
        client = mock_app_state.client
        mock_app_state.monitor.is_running = True
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("c")
            await pilot.pause()
            app.query_one("#reload-button", Button).press()
            assert await _wait_for(
                lambda: any("stop the monitor first" in n.message for n in app._notifications),
                pilot,
            )
            client.close.assert_not_called()
            assert mock_app_state._client is client

    def test_reload_settings_resets_cached_state(self, tmp_path):
        from unittest.mock import MagicMock

        from cja_audit_log_monitor.tui.state import AppState

        config = tmp_path / "config.yaml"
        config.write_text("monitor_interval: 30\n")
        config.chmod(0o600)
        state = AppState()
        assert state.settings.monitor_interval == 30
        old_engine = state.alert_engine
        client = state._client = MagicMock()
        config.write_text("monitor_interval: 45\n")
        state.reload_settings()
        assert state.settings.monitor_interval == 45
        assert state.alert_engine is not old_engine
        assert state._client is None
        client.close.assert_called_once()

    def test_reload_settings_picks_up_a_bad_file_as_a_warning(self, tmp_path):
        from cja_audit_log_monitor.tui.state import AppState

        config = tmp_path / "config.yaml"
        config.write_text("monitor_interval: 30\n")
        config.chmod(0o600)
        state = AppState()
        state.settings
        assert state.config_error_summary is None
        config.write_text("monitor_interval: [unclosed\n")
        with pytest.raises(ConfigError):
            state.reload_settings()
        assert state.config_error_summary
        assert state.settings.monitor_interval == 30
        config.write_text("monitor_interval: 45\n")
        state.reload_settings()
        assert state.config_error_summary is None

    def test_settings_screen_renders_notifications_section(self):
        """Settings screen includes a Notifications section showing channel presence."""
        from unittest.mock import MagicMock

        from cja_audit_log_monitor.models import NotificationConfig, WebhookConfig
        from cja_audit_log_monitor.tui.screens.settings import SettingsScreen

        state = MagicMock()
        state.settings.notifications = NotificationConfig(
            slack_webhook_url="https://hooks.slack.com/x",
            webhooks=[WebhookConfig(url="https://h1.example.com")],
        )
        state.settings.org_id = "test@AdobeOrg"
        state.settings.client_id = "abc"
        state.settings.is_oauth_configured.return_value = True
        state.settings.api_base_url = "https://cja.adobe.io"
        state.settings.ims_base_url = "https://ims-na1.adobelogin.com"
        state.settings.default_page_size = 100
        state.settings.default_days = 7
        state.settings.monitor_interval = 60
        state.settings.alert_rules = []
        state.config_path = "/tmp/config"

        screen = SettingsScreen(state=state)
        # Iterate compose_content to ensure no exception is raised when building the widget tree
        widgets = list(screen.compose_content())

        # Walk the pending widget tree and collect rendered text from all Static nodes
        def collect_text(node):
            from textual.widgets import Static

            parts = []
            if isinstance(node, Static):
                parts.append(str(node.render()))
            for child in getattr(node, "_pending_children", []):
                parts.extend(collect_text(child))
            return parts

        all_text = " ".join(t for w in widgets for t in collect_text(w))
        # The new section should reference NOTIFICATIONS as a heading
        assert "NOTIFICATIONS" in all_text or "Notifications" in all_text
        # Slack should show "configured" (not the URL itself)
        assert "configured" in all_text
        assert "hooks.slack.com" not in all_text


# ---------------------------------------------------------------------------
# TestModals
# ---------------------------------------------------------------------------


class TestModals:
    """Test modal dialogs."""

    async def test_entry_detail_panel_shows_when_toggled(self, mock_app_state, sample_audit_entry):
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            # Load a row so the table has a selectable entry.
            table = app.query_one("#log-table", LogTable)
            table.load_entries([sample_audit_entry])
            await pilot.pause()

            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
            assert not panel.is_visible()

            panel.show_entry(sample_audit_entry)
            await pilot.pause()
            assert panel.is_visible()
            # Detail body must contain the entry id.
            body_text = _plain(panel.query_one("#detail-body", Static))
            assert sample_audit_entry.id in body_text

    async def test_entry_detail_panel_dismisses_on_escape(self, mock_app_state, sample_audit_entry):
        """Pressing Esc (via `action_dismiss_details`) hides the panel.

        Note: We invoke `action_dismiss_details()` directly rather than
        `pilot.press("escape")` because LogBrowserScreen is mounted as a
        widget (not pushed onto Textual's screen stack), so its BINDINGS
        never enter the headless test's key-dispatch chain. This asserts
        the contract that the action method hides the panel — which is
        what the Esc binding is wired to. An end-to-end key test would
        require lifting the screen onto the screen stack, which would
        diverge from how the app actually mounts it.
        """
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.screens import LogBrowserScreen
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            table = app.query_one("#log-table", LogTable)
            table.load_entries([sample_audit_entry])
            await pilot.pause()

            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
            panel.show_entry(sample_audit_entry)
            await pilot.pause()
            assert panel.is_visible()

            log_screen = app.query_one(LogBrowserScreen)
            log_screen.action_dismiss_details()
            await pilot.pause()
            assert not panel.is_visible()

    async def test_entry_detail_panel_toggle_semantics(self, mock_app_state, sample_audit_entries):
        """toggle(): same entry hides; different entry stays visible and re-renders.

        Note: toggle() calls show_entry() → _render_entry() → query_one(), so we need
        a mounted context. We wrap in app.run_test() and load the log browser
        so the panel is properly composed into the DOM before exercising it.
        """
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        entry_a, entry_b = sample_audit_entries[0], sample_audit_entries[1]
        assert entry_a.id != entry_b.id

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            table = app.query_one("#log-table", LogTable)
            table.load_entries([entry_a, entry_b])
            await pilot.pause()

            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
            assert not panel.is_visible()

            # Different-entry toggle from hidden state → visible.
            panel.toggle(entry_a)
            await pilot.pause()
            assert panel.is_visible()
            assert panel._entry is entry_a

            # Same-entry toggle while visible → hidden.
            panel.toggle(entry_a)
            await pilot.pause()
            assert not panel.is_visible()

            # Toggle to the panel that's hidden but already has the entry → visible again.
            panel.toggle(entry_a)
            await pilot.pause()
            assert panel.is_visible()

            # Different-entry toggle while visible → stays visible, swaps content.
            panel.toggle(entry_b)
            await pilot.pause()
            assert panel.is_visible()
            assert panel._entry is entry_b

    async def test_entry_detail_panel_updates_on_row_highlighted(
        self, mock_app_state, sample_audit_entries
    ):
        """When the panel is visible, advancing the cursor updates its content live."""
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        # Use two distinct entries so we can assert the panel content changes.
        entry_a, entry_b = sample_audit_entries[0], sample_audit_entries[1]
        assert entry_a.id != entry_b.id

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            log_screen = app._screens["logs"]
            table = app.query_one("#log-table", LogTable)
            table.load_entries([entry_a, entry_b])
            await pilot.pause()

            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)

            # Open panel on first row.
            panel.show_entry(entry_a)
            await pilot.pause()
            body = panel.query_one("#detail-body", Static)
            body_text_a = _plain(body)
            assert entry_a.id in body_text_a

            # Move cursor to second row and fire the highlighted handler directly.
            # (pilot key dispatch doesn't reach LogBrowserScreen BINDINGS in this
            # widget-mounted test setup; calling the handler is equivalent.)
            table.move_cursor(row=1)
            log_screen.on_data_table_row_highlighted(event=None)
            await pilot.pause()

            body_text_b = _plain(body)
            assert entry_b.id in body_text_b
            assert panel.is_visible()

    async def test_entry_detail_panel_no_update_when_hidden(
        self, mock_app_state, sample_audit_entry
    ):
        """When the panel is hidden, RowHighlighted handler is a no-op."""
        from cja_audit_log_monitor.tui.modals import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("l")
            await pilot.pause()

            log_screen = app._screens["logs"]
            table = app.query_one("#log-table", LogTable)
            table.load_entries([sample_audit_entry])
            await pilot.pause()

            panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
            assert not panel.is_visible()

            log_screen.on_data_table_row_highlighted(event=None)
            await pilot.pause()
            assert not panel.is_visible()

    async def test_export_dialog_opens_on_e_key(self, mock_app_state):
        from cja_audit_log_monitor.tui.modals import ExportDialog

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ExportDialog)

    async def test_export_dialog_has_format_radio_buttons(self, mock_app_state):
        from cja_audit_log_monitor.tui.modals import ExportDialog

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ExportDialog)
            radio_buttons = app.screen.query("#format-select RadioButton")
            assert len(radio_buttons) == 3  # JSON, CSV, TSV

    async def test_export_dialog_has_export_button(self, mock_app_state):
        from cja_audit_log_monitor.tui.modals import ExportDialog

        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("e")
            await pilot.pause()
            assert isinstance(app.screen, ExportDialog)
            export_btn = app.screen.query_one("#export-button", Button)
            assert export_btn is not None


class TestSampledTotals:
    """Dashboard and stats show the API's true total, and say when charts use a sample."""

    @pytest.mark.parametrize(("key", "total_id"), [("d", "#stat-total"), ("s", "#stats-total")])
    async def test_total_is_true_api_total(
        self, mock_app_state, sample_audit_entries, key, total_id
    ):
        mock_app_state.client.get_logs_sample.return_value = (sample_audit_entries, 28775)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, key)
            assert str(view.query_one(total_id, Static).render()) == "28,775"

    @pytest.mark.parametrize("key", ["d", "s"])
    async def test_sample_note_when_capped(self, mock_app_state, sample_audit_entries, key):
        mock_app_state.client.get_logs_sample.return_value = (sample_audit_entries, 28775)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, key)
            note = view.query_one(".sample-note", Static)
            assert note.display
            n = len(sample_audit_entries)
            assert f"newest {n:,} of 28,775 entries" in str(note.render())

    @pytest.mark.parametrize("key", ["d", "s"])
    async def test_no_sample_note_when_complete(self, mock_app_state, key):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, key)
            assert not view.query_one(".sample-note", Static).display


class TestExportScope:
    """Export can save the current page or every matching entry."""

    async def _open(self, app, pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        return app.screen

    async def test_scope_options_show_counts(self, mock_app_state, sample_audit_entries):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        mock_app_state.total_entries = 28775
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            page = str(dialog.query_one("#scope-page").label)
            every = str(dialog.query_one("#scope-all").label)
            assert f"this page · {len(sample_audit_entries)} entries" in page
            assert "all matching · 28,775 entries" in every
            assert "up to 10,000" in every

    async def test_page_scope_is_default_and_writes_page(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        target = tmp_path / "page.json"
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            assert await _wait_for(target.exists, pilot, timeout=5.0)
            await app.workers.wait_for_complete()
        import json

        assert len(json.loads(target.read_text())["entries"]) == len(sample_audit_entries)
        mock_app_state.client.get_logs_sample.assert_not_called()

    async def test_all_scope_fetches_every_matching_entry(
        self, mock_app_state, sample_audit_entries, sample_audit_entry, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries[:1]
        mock_app_state.total_entries = 30
        many = [sample_audit_entry.model_copy(update={"id": f"m{i}"}) for i in range(30)]
        mock_app_state.client.get_logs_sample.return_value = (many, 30)
        app = _make_app(mock_app_state)
        target = tmp_path / "all.json"
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#scope-all").value = True
            await pilot.pause()
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            assert await _wait_for(target.exists, pilot, timeout=5.0)
            await app.workers.wait_for_complete()
        import json

        assert len(json.loads(target.read_text())["entries"]) == 30
        _, kwargs = mock_app_state.client.get_logs_sample.call_args
        assert kwargs["max_entries"] == 10_000

    async def test_dialog_closes_itself_after_export_without_crashing(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch
    ):
        from cja_audit_log_monitor.tui.modals import ExportDialog

        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        monkeypatch.setattr(ExportDialog, "AUTO_CLOSE_SECONDS", 0.05)
        target = tmp_path / "x.json"
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            assert await _wait_for(target.exists, pilot, timeout=5.0)
            assert await _wait_for(
                lambda: not isinstance(app.screen, ExportDialog), pilot, timeout=5.0
            )
        assert app._exception is None

    async def test_closing_before_auto_close_does_not_crash(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch
    ):
        from cja_audit_log_monitor.tui.modals import ExportDialog

        # Wide margin so Escape lands before the timer even on a heavily loaded machine.
        monkeypatch.setattr(ExportDialog, "AUTO_CLOSE_SECONDS", 2.0)
        closes: list[bool] = []
        done: list[bool] = []
        real_close = ExportDialog._close_if_open
        real_done = ExportDialog._done

        def done_spy(self, *args, **kwargs):
            real_done(self, *args, **kwargs)
            done.append(True)  # the auto-close timer is now armed

        monkeypatch.setattr(ExportDialog, "_done", done_spy)

        def spy(self):
            closes.append(self.app.screen is self)
            real_close(self)

        monkeypatch.setattr(ExportDialog, "_close_if_open", spy)
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        target = tmp_path / "x.json"
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            # Wait for the export worker and for _done (which starts the timer) to run.
            assert await _wait_for(lambda: bool(done), pilot, timeout=5.0)
            assert target.exists()
            assert not closes  # timer has not fired yet
            await pilot.press("escape")
            assert await _wait_for(
                lambda: not isinstance(app.screen, ExportDialog), pilot, timeout=5.0
            )
            await pilot.pause(0.1)  # let any stray timer callback run; the margin is 2 s
            # Textual stops a screen's timers when it is removed, so the callback never
            # runs on a closed dialog; if that ever changes, it must still be a no-op.
            assert closes in ([], [False])
            assert app.is_running
        assert app._exception is None

    async def test_dialog_uses_lowercase_labels(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            assert str(dialog.query_one("#export-button").label) == "export"
            assert str(dialog.query_one("#cancel-button").label) == "cancel"
            assert str(dialog.query_one("#export-title").render()) == "export audit logs"

    async def test_pilot_clearing_path_and_changing_format_does_not_crash(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = ""
            await pilot.pause()
            dialog.query_one("#format-csv").value = True
            await pilot.pause()
            assert app.is_running
            assert dialog.query_one("#output-path").value == ""
        assert app._exception is None

    async def test_existing_file_needs_a_second_press(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        target = tmp_path / "out.json"
        target.write_text("old")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            await pilot.pause()
            status = dialog.query_one("#export-status").render().plain
            assert "file exists · press export again to overwrite" in status
            assert target.read_text() == "old"
            # A click within the button's 0.2 s "active" flash is ignored; press directly.
            dialog.query_one("#export-button").press()
            assert await _wait_for(lambda: target.read_text() != "old", pilot, timeout=5.0)
            await app.workers.wait_for_complete()

    async def test_changing_path_or_format_resets_overwrite_confirmation(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        first = tmp_path / "a.json"
        first.write_text("old")
        second = tmp_path / "a.csv"
        second.write_text("old")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            path = dialog.query_one("#output-path")
            path.value = str(first)
            await pilot.click("#export-button")
            await pilot.pause()
            dialog.query_one("#format-csv").value = True  # path becomes a.csv
            await pilot.pause()
            dialog.query_one("#export-button").press()
            await pilot.pause()
            assert second.read_text() == "old"  # asked again instead of writing
            assert "press export again" in dialog.query_one("#export-status").render().plain

    async def test_missing_parent_folder_shows_error_without_crashing(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(tmp_path / "nope" / "x.json")
            await pilot.click("#export-button")
            await pilot.pause()
            status = dialog.query_one("#export-status").render().plain
            assert "folder does not exist" in status
            assert "\n" not in status
            assert not dialog.query_one("#export-button").disabled
        assert app._exception is None

    async def test_enter_in_path_input_exports(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        target = tmp_path / "enter.json"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            path = dialog.query_one("#output-path")
            path.value = str(target)
            path.focus()
            await pilot.pause()
            await pilot.press("enter")
            assert await _wait_for(target.exists, pilot, timeout=5.0)
            await app.workers.wait_for_complete()

    async def test_limit_reached_is_reported_with_absolute_path(
        self, mock_app_state, sample_audit_entry, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = [sample_audit_entry]
        mock_app_state.total_entries = 12345
        many = [sample_audit_entry.model_copy(update={"id": f"m{i}"}) for i in range(10_000)]
        mock_app_state.client.get_logs_sample.return_value = (many, 12345)
        target = tmp_path / "big.csv"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#scope-all").value = True
            await pilot.pause()
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            assert await _wait_for(
                lambda: "limit reached" in dialog.query_one("#export-status").render().plain,
                pilot,
                timeout=10.0,
            )
            status = dialog.query_one("#export-status").render().plain
            assert "exported 10,000 of 12,345 (limit reached)" in status
            assert str(target.resolve()) in status.replace("\n", "")

    async def test_path_with_markup_is_shown_literally(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        target = tmp_path / "[red]x.json"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            assert await _wait_for(target.exists, pilot, timeout=5.0)
            assert await _wait_for(
                lambda: "exported" in dialog.query_one("#export-status").render().plain,
                pilot,
            )
            assert "[red]x.json" in dialog.query_one("#export-status").render().plain
            await app.workers.wait_for_complete()
        assert app._exception is None

    async def test_before_log_browser_loads_page_scope_is_disabled_and_no_counts(
        self, mock_app_state
    ):
        assert mock_app_state.page_loaded is False
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            page = dialog.query_one("#scope-page")
            every = dialog.query_one("#scope-all")
            assert page.disabled
            assert every.value
            assert "0" not in str(page.label)
            assert "entries" not in str(page.label)
            assert "entries" not in str(every.label)
            assert "up to 10,000" in str(every.label)


class TestExportPathsNeverCrash:
    """A typo in the path box never ends the app (G22, G25)."""

    async def _open(self, app, pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        return app.screen

    @pytest.mark.parametrize(
        "raw", ["~backup.json", "~no-such-user-zz/x.json", "x" * 300 + ".json"]
    )
    async def test_typed_path_never_crashes(self, mock_app_state, sample_audit_entries, raw):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = raw
            await pilot.click("#export-button")
            await pilot.pause()
            assert app.is_running
            assert _plain(dialog.query_one("#export-status", Static)).strip()

    async def test_lone_tilde_then_format_change(self, mock_app_state, sample_audit_entries):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = "~"
            dialog.query_one("#format-csv").value = True
            await pilot.pause()
            await pilot.click("#export-button")
            await pilot.pause()
            assert app.is_running

    async def test_dangling_symlink_needs_one_confirm(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        link = tmp_path / "out.json"
        link.symlink_to(tmp_path / "gone.json")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(link)
            await pilot.pause()  # let the input's Changed event pass first
            await pilot.click("#export-button")
            await pilot.pause()
            assert "press export again" in _plain(dialog.query_one("#export-status", Static))
            # A click within the button's 0.2 s "active" flash is ignored; press directly.
            dialog.query_one("#export-button").press()
            assert await _wait_for(lambda: link.exists() and not link.is_symlink(), pilot)
            await app.workers.wait_for_complete()


class TestExportRobustness:
    """The dialog survives being closed mid-export and never clobbers a late file."""

    async def _open(self, app, pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        return app.screen

    @pytest.mark.parametrize("failure", ["fetch", "empty", "write"])
    async def test_escape_during_export_does_not_crash(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch, failure
    ):
        import threading

        started = threading.Event()
        release = threading.Event()

        def blocked_fetch(*args, **kwargs):
            started.set()
            assert release.wait(timeout=5)
            if failure == "fetch":
                raise RuntimeError("api down")
            if failure == "empty":
                return [], 0
            return sample_audit_entries, len(sample_audit_entries)

        mock_app_state.page_loaded = True
        mock_app_state.client.get_logs_sample.side_effect = blocked_fetch
        if failure == "write":

            def broken_export(*args, **kwargs):
                raise OSError("disk full")

            monkeypatch.setattr(
                "cja_audit_log_monitor.tui.modals.export_dialog.export_entries", broken_export
            )
        from cja_audit_log_monitor.tui.modals.export_dialog import ExportDialog

        # The worker's callbacks reach the closed dialog. Record that they ran, whether
        # they raised, and whether they touched the status line.
        reached: list[str] = []
        raised: list[Exception] = []
        status_calls: list[str] = []
        real_set_status = ExportDialog._set_status

        def spy_set_status(self, message, token="$text-muted"):
            status_calls.append(message)
            return real_set_status(self, message, token)

        monkeypatch.setattr(ExportDialog, "_set_status", spy_set_status)
        for name in ("_fail", "_done", "_ask_overwrite"):

            def make(real, label):
                def wrapper(self, *args, **kwargs):
                    reached.append(label)
                    try:
                        return real(self, *args, **kwargs)
                    except Exception as error:
                        raised.append(error)
                        raise

                return wrapper

            monkeypatch.setattr(ExportDialog, name, make(getattr(ExportDialog, name), name))

        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#scope-all").value = True
            dialog.query_one("#output-path").value = str(tmp_path / "x.json")
            dialog.query_one("#export-button").press()
            assert await _wait_for(started.is_set, pilot)
            status_calls.clear()  # keep only what happens after the dialog closes
            await pilot.press("escape")
            await pilot.pause()
            assert await _wait_for(lambda: not dialog.is_attached, pilot)
            release.set()
            if failure == "fetch":
                # Closing the dialog drops its worker from the manager, so wait for the
                # callback itself. The other cases stop at the worker's cancelled check.
                assert await _wait_for(lambda: bool(reached), pilot)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert app.is_running
        if failure == "fetch":
            assert reached == ["_fail"]
        assert raised == []
        assert status_calls == []
        assert app._exception is None

    async def test_file_appearing_during_fetch_is_not_clobbered(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        target = tmp_path / "late.json"

        def fetch_then_appear(*args, **kwargs):
            target.write_text("someone else")
            return sample_audit_entries, len(sample_audit_entries)

        mock_app_state.page_loaded = True
        mock_app_state.client.get_logs_sample.side_effect = fetch_then_appear
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#scope-all").value = True
            dialog.query_one("#output-path").value = str(target)
            dialog.query_one("#export-button").press()
            await app.workers.wait_for_complete()
            assert await _wait_for(
                lambda: "file exists · press export again to overwrite"
                in dialog.query_one("#export-status").render().plain,
                pilot,
            )
            assert target.read_text() == "someone else"
            assert not dialog.query_one("#export-button").disabled
            # Confirming now replaces it.
            dialog.query_one("#export-button").press()
            assert await _wait_for(lambda: target.read_text() != "someone else", pilot, timeout=5.0)
            await app.workers.wait_for_complete()
        assert app._exception is None


class TestPageLoadedFlag:
    async def test_log_browser_sets_page_loaded(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            assert mock_app_state.page_loaded is False
            view = await _show_and_load(app, pilot, "l")
            assert view is not None
            assert mock_app_state.page_loaded is True

    async def test_failed_reload_clears_page_and_export_offers_no_page_scope(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            view = await _show_and_load(app, pilot, "l")
            assert mock_app_state.page_loaded is True
            assert mock_app_state.entries
            mock_app_state.client.get_logs.side_effect = RuntimeError("api down")
            view.refresh_data()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert mock_app_state.page_loaded is False
            assert mock_app_state.entries == []
            assert mock_app_state.total_entries == 0
            await pilot.press("e")
            await pilot.pause()
            dialog = app.screen
            assert dialog.query_one("#scope-page").disabled
            assert "entries" not in str(dialog.query_one("#scope-page").label)


class TestStaleLoads:
    """A load that a newer one superseded must not touch the view (F21)."""

    @staticmethod
    def _page(entry, page: int, count: int = 50):
        from cja_audit_log_monitor.models import AuditLogResponse

        entries = [entry.model_copy(update={"id": f"p{page}-{i}"}) for i in range(count)]
        return AuditLogResponse(
            content=entries,
            total_elements=120,
            total_pages=3,
            number_of_elements=count,
            first=page == 0,
            last=False,
            number=page,
            size=50,
        )

    @staticmethod
    def _slow_failing_page1(app):
        """get_logs where page 1 waits for a release, then fails to connect.

        Returns (get_logs, started, release, delivered). ``delivered`` is set once the
        page 1 thread's first hand-off to the UI thread has run; a cancelled thread
        worker keeps running after Textual marks it done, so wait_for_complete
        alone does not cover it.
        """
        import threading

        from cja_audit_log_monitor.client import APIError

        started = threading.Event()
        release = threading.Event()
        delivered = threading.Event()
        page1_thread: list[threading.Thread] = []
        original = app.call_from_thread

        def spy(callback, *args, **kwargs):
            try:
                return original(callback, *args, **kwargs)
            finally:
                if page1_thread and threading.current_thread() is page1_thread[0]:
                    delivered.set()

        app.call_from_thread = spy

        def page1():
            page1_thread.append(threading.current_thread())
            started.set()
            release.wait(5)
            raise APIError("network down")  # no status code: a connection failure

        return page1, started, release, delivered

    async def test_stale_failure_does_not_clear_newer_page(
        self, mock_app_state, sample_audit_entry
    ):
        from cja_audit_log_monitor.tui.widgets import LogTable

        page0 = self._page(sample_audit_entry, 0)
        app = _make_app(mock_app_state)
        page1, started, release, delivered = self._slow_failing_page1(app)
        mock_app_state.client.get_logs.side_effect = (
            lambda query: page1() if query.page == 1 else page0
        )
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            table = view.query_one("#log-table", LogTable)
            assert table.row_count == 50
            table.focus()
            await pilot.press("n")
            assert await _wait_for(started.is_set, pilot)
            await pilot.press("p")
            # Page 0 comes back at once; only then does the slow page 1 fail.
            await app.workers.wait_for_complete()
            assert await _wait_for(lambda: mock_app_state.client.get_logs.call_count == 3, pilot)
            release.set()
            assert await _wait_for(delivered.is_set, pilot)
            await pilot.pause()
            assert table.row_count == 50
            assert app._connection_status == "connected"
            assert mock_app_state.page_loaded is True
            assert len(mock_app_state.entries) == 50
            assert mock_app_state.total_entries == 120
            assert not view.query_one("#table-message", Static).display
            assert not view.query_one("#logs-loading").display
        assert app._exception is None

    async def test_loading_stays_until_newest_load_ends(self, mock_app_state, sample_audit_entry):
        import threading

        from cja_audit_log_monitor.tui.widgets import LogTable

        page0 = self._page(sample_audit_entry, 0)
        app = _make_app(mock_app_state)
        page1, started, release, delivered = self._slow_failing_page1(app)
        reload_started = threading.Event()
        release_reload = threading.Event()
        page0_loads = []

        def get_logs(query):
            if query.page == 1:
                return page1()
            page0_loads.append(query)
            if len(page0_loads) > 1:  # the reload after "p" is slow too
                reload_started.set()
                release_reload.wait(5)
            return page0

        mock_app_state.client.get_logs.side_effect = get_logs
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            table = view.query_one("#log-table", LogTable)
            indicator = view.query_one("#logs-loading")
            table.focus()
            await pilot.press("n")
            assert await _wait_for(started.is_set, pilot)
            await pilot.press("p")  # waits as the pending load: one fetch at a time
            # The superseded page 1 fails; the page 0 reload then starts and is slow.
            release.set()
            assert await _wait_for(delivered.is_set, pilot)
            assert await _wait_for(reload_started.is_set, pilot)
            await pilot.pause()
            assert indicator.display, "a superseded load hid the loading indicator"
            assert table.row_count == 50
            assert app._connection_status == "connected"
            release_reload.set()
            await app.workers.wait_for_complete()
            assert await _wait_for(lambda: not indicator.display, pilot)
            assert table.row_count == 50
            assert app._connection_status == "connected"
        assert app._exception is None


class TestSwapSuffix:
    def test_empty_and_folder_unchanged(self):
        from cja_audit_log_monitor.tui.modals.export_dialog import swap_suffix

        assert swap_suffix("", ".csv") == ""
        assert swap_suffix("~/exports.v2/", ".csv") == "~/exports.v2/"

    def test_known_suffix_replaced_other_appended(self):
        from cja_audit_log_monitor.tui.modals.export_dialog import swap_suffix

        assert swap_suffix("a.json", ".csv") == "a.csv"
        assert swap_suffix("report.v2", ".csv") == "report.v2.csv"


class TestHelpScreen:
    """Help lists every shortcut, in the app's lowercase style, without gaps."""

    async def _open(self, app, pilot):
        await pilot.pause()
        await pilot.press("question_mark")
        await pilot.pause()
        return app.screen

    async def test_lists_view_specific_keys(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            help_screen = await self._open(app, pilot)
            text = "\n".join(str(s.render()) for s in help_screen.query(".help-section-body"))
            for key, words in [
                ("n", "next page"),
                ("p", "previous page"),
                ("space", "start or stop"),
                ("enter", "entry details"),
                ("esc", "close"),
            ]:
                line = next((ln for ln in text.splitlines() if ln.strip().startswith(key)), "")
                assert words in line, (key, line)

    async def test_dashboard_line_uses_configured_days(self, mock_app_state):
        mock_app_state.settings.default_days = 3
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            help_screen = await self._open(app, pilot)
            text = "\n".join(str(s.render()) for s in help_screen.query(".help-section-body"))
            assert "summary of the last 3 days" in text
            assert "last 7 days" not in text

    async def test_title_is_lowercase(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            help_screen = await self._open(app, pilot)
            assert str(help_screen.query_one("#help-title").render()) == "keyboard shortcuts"

    async def test_rows_have_no_blank_gaps(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            help_screen = await self._open(app, pilot)
            for body in help_screen.query(".help-section-body"):
                lines = str(body.render()).splitlines()
                assert all(line.strip() for line in lines)
                assert body.region.height == len(lines)

    async def test_escape_closes(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            help_screen = await self._open(app, pilot)
            await pilot.press("escape")
            await pilot.pause()
            assert app.screen is not help_screen


class TestLogBrowserMessages:
    """The log browser explains an empty table instead of showing a blank grid."""

    async def test_connection_error_is_shown_in_view(self, mock_app_state):
        from cja_audit_log_monitor.auth import AuthenticationError

        mock_app_state.client.get_logs.side_effect = AuthenticationError(
            "invalid_client: invalid client_secret parameter"
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            message = view.query_one("#table-message", Static)
            assert message.display
            assert "not connected" in str(message.render())
            assert "invalid_client" in str(message.render())
            assert view.query_one("#filter-bar").display

    async def test_no_matches_says_so(self, mock_app_state):
        from cja_audit_log_monitor.models import AuditLogResponse

        mock_app_state.client.get_logs.return_value = AuditLogResponse(
            content=[], total_elements=0, total_pages=0
        )
        mock_app_state.filters.search_text = "zzzz"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            message = view.query_one("#table-message", Static)
            assert message.display
            assert "no entries match these filters" in str(message.render())

    async def test_message_hidden_when_rows_load(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            assert not view.query_one("#table-message", Static).display


class TestFooterBindings:
    """The footer only offers keys that do something right now."""

    async def test_close_details_only_when_panel_open(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            assert view.check_action("dismiss_details", ()) is False
            await pilot.press("enter")
            await pilot.pause()
            assert view.check_action("dismiss_details", ()) is True
            await pilot.press("escape")
            await pilot.pause()
            assert view.check_action("dismiss_details", ()) is False


class TestLocalTimes:
    """The TUI shows local time and names the zone."""

    async def test_log_table_header_names_zone(self, mock_app_state, los_angeles_tz):
        from cja_audit_log_monitor.tui.widgets.log_table import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            table = view.query_one(LogTable)
            labels = [str(col.label) for col in table.columns.values()]
            assert labels[0] in ("time (PST)", "time (PDT)")

    async def test_log_table_shows_local_time(
        self, mock_app_state, sample_audit_entry, los_angeles_tz
    ):
        from datetime import UTC, datetime

        from cja_audit_log_monitor.tui.widgets.log_table import LogTable

        entry = sample_audit_entry.model_copy(
            update={"timestamp": datetime(2026, 11, 17, 23, 25, 13, tzinfo=UTC)}
        )
        mock_app_state.client.get_logs.return_value.content = [entry]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            table = view.query_one(LogTable)
            assert str(table.get_row_at(0)[0]) == "2026-11-17 15:25:13"


class TestLocalWindows:
    """Window cards show the queried window in local dates; chart labels name the zone."""

    async def test_dashboard_window_is_last_7_local_days(self, mock_app_state, los_angeles_tz):
        from datetime import datetime, timedelta

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            now = datetime.now().astimezone()
            expected = f"{(now - timedelta(days=7)):%m-%d} → {now:%m-%d}"
            assert str(view.query_one("#stat-range", Static).render()) == expected

    async def test_stats_period_is_queried_window(self, mock_app_state, los_angeles_tz):
        from datetime import datetime, timedelta

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "s")
            now = datetime.now().astimezone()
            expected = f"{(now - timedelta(days=7)):%m-%d} → {now:%m-%d}"
            assert str(view.query_one("#stats-period", Static).render()) == expected

    @pytest.mark.parametrize("key", ["d", "s"])
    async def test_hourly_label_names_zone(self, mock_app_state, los_angeles_tz, key):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, key)
            labels = [str(s.render()) for s in view.query(".section-label")]
            hourly = next(label for label in labels if label.startswith("HOURLY ACTIVITY"))
            assert hourly.endswith(("PST", "PDT"))

    async def test_monitor_last_check_is_local(self, mock_app_state, los_angeles_tz):
        from datetime import UTC, datetime

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            view = app._screens["monitor"]
            mock_app_state.monitor.last_check = datetime(2026, 11, 17, 23, 25, 13, tzinfo=UTC)
            view._update_stats_display()
            await pilot.pause()
            assert "last check 15:25:13" in str(view.query_one("#stats-info", Static).render())


class TestSmallCopyFixes:
    async def test_monitor_alerts_says_none_yet(self, mock_app_state):
        from cja_audit_log_monitor.tui.widgets import AlertSummary

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            summary = app._screens["monitor"].query_one(AlertSummary)
            assert str(summary.render()) == "no alerts yet"

    async def test_alert_summary_short_message_not_cut(self, mock_app_state):
        from cja_audit_log_monitor.tui.widgets import AlertSummary

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            summary = app._screens["monitor"].query_one(AlertSummary)
            summary.add_alert("bulk_delete: 5 deletes in 60 min")
            text = str(summary.render())
            assert "bulk_delete: 5 deletes in 60 min" in text
            assert "..." not in text and "…" not in text

    async def test_recent_alerts_line_uses_the_available_width(self, mock_app_state):
        from cja_audit_log_monitor.tui.widgets import AlertSummary

        text = "bulk_delete: 5 events in 60 minutes by someone.with.a.long.name@example.com"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            summary = app._screens["monitor"].query_one(AlertSummary)
            summary.add_alert(text)
            await pilot.pause()
            assert text in str(summary.render())

    async def test_test_rules_reports_hidden_alerts_and_the_entry_limit(self, mock_app_state):
        from cja_audit_log_monitor.alerts import AlertEngine
        from cja_audit_log_monitor.models import ActionType

        rule = AlertRule(name="any delete", actions=[ActionType.DELETE])
        mock_app_state._alert_engine = AlertEngine([rule])
        now = datetime.now(UTC)
        deletes = [
            AuditLogEntry(
                id=str(i), action="DELETE", user_id="u", timestamp=now - timedelta(seconds=i)
            )
            for i in range(1000)
        ]
        mock_app_state.client.get_all_logs.return_value = deletes
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("a")
            await pilot.pause()
            app.query_one("#test-rules").press()
            await app.workers.wait_for_complete()
            await pilot.pause()
            text = _plain(app._screens["alerts"].query_one("#test-results", Static))
            assert "found 1,000 alerts, showing 10" in text
            assert "the newest 1,000 entries" in text

    async def test_rule_card_uses_singular_event(self, mock_app_state):
        from cja_audit_log_monitor.alerts import AlertEngine

        mock_app_state._alert_engine = AlertEngine()
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("a")
            await pilot.pause()
            text = "\n".join(str(s.render()) for s in app._screens["alerts"].query(Static))
            assert "1 event / 1 min" in text
            assert "1 events" not in text


class TestSidebarKeys:
    """View keys live in the sidebar, so the footer only lists actions and fits."""

    async def test_sidebar_items_show_their_key(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            texts = {
                item.id: str(item.render()).strip() for item in app.query("#sidebar .nav-item")
            }
            assert texts["nav-dashboard"].endswith("d dashboard")
            assert texts["nav-settings"].endswith("c config")

    async def test_footer_hides_view_switch_keys(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            shown = [b.binding.action for b in app.active_bindings.values() if b.binding.show]
            assert not any(action.startswith("switch_screen") for action in shown)
            assert "refresh" in shown and "quit" in shown


class TestActionColumn:
    @pytest.mark.parametrize("size", [(140, 40), (100, 30)])
    async def test_longest_action_fits(self, mock_app_state, sample_audit_entry, size):
        from cja_audit_log_monitor.tui.widgets.log_table import LogTable

        entry = sample_audit_entry.model_copy(update={"action": "API_REQUEST"})
        mock_app_state.client.get_logs.return_value.content = [entry]
        app = _make_app(mock_app_state)
        async with app.run_test(size=size) as pilot:
            view = await _show_and_load(app, pilot, "l")
            table = view.query_one(LogTable)
            cell = table.get_row_at(0)[2]
            assert table.columns["action"].width >= len(str(cell).rstrip())


async def test_component_filter_offers_image(mock_app_state):
    from textual.widgets import Select

    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("l")
        await pilot.pause()
        select = app.query_one("#filter-component", Select)
        values = [value for _, value in select._options]
        assert "IMAGE" in values


async def test_dashboard_anomalies_use_local_hours(mock_app_state, monkeypatch):
    from cja_audit_log_monitor.tui.screens import dashboard

    calls = []

    def fake(entries, local=False):
        calls.append(local)
        return []

    monkeypatch.setattr(dashboard, "analyze_for_anomalies", fake)
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        await _show_and_load(app, pilot, "d")
    assert calls and all(calls)


class TestReviewFixes:
    async def test_n_on_last_page_stays(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            assert mock_app_state.filters.page == 0
            await pilot.press("n")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert mock_app_state.filters.page == 0

    async def test_dashboard_active_users_counts_every_account(
        self, mock_app_state, sample_audit_entry
    ):
        entries = [
            sample_audit_entry.model_copy(
                update={"id": f"e{i}", "user_id": f"U{i}@x.e", "user_email": f"u{i}@example.com"}
            )
            for i in range(25)
        ]
        mock_app_state.client.get_logs_sample.return_value = (entries, 25)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            assert str(view.query_one("#stat-users", Static).render()) == "25"

    async def test_export_writes_off_the_ui_thread(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch
    ):
        import threading

        from cja_audit_log_monitor.tui.modals import export_dialog

        threads = []
        real = export_dialog.export_entries

        def recording(*args, **kwargs):
            threads.append(threading.current_thread() is threading.main_thread())
            return real(*args, **kwargs)

        monkeypatch.setattr(export_dialog, "export_entries", recording)
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.press("e")
            await pilot.pause()
            app.screen.query_one("#output-path").value = str(tmp_path / "x.json")
            await pilot.click("#export-button")
            await app.workers.wait_for_complete()
            await pilot.pause()
        assert threads == [False]


class TestErrorKinds:
    """Views name the kind of failure, and the header tracks the connection."""

    @pytest.mark.parametrize(
        ("exc", "kind"),
        [
            ("auth", "connection"),
            ((None,), "connection"),
            ((401,), "connection"),
            ((403,), "access"),
            ((400,), "rejected"),
            ((500,), "other"),
            ("value", "other"),
        ],
    )
    def test_classify(self, exc, kind):
        from cja_audit_log_monitor.auth import AuthenticationError
        from cja_audit_log_monitor.client import APIError
        from cja_audit_log_monitor.tui.screens.base import classify_error

        if exc == "auth":
            error = AuthenticationError("invalid_client")
        elif exc == "value":
            error = ValueError("boom")
        else:
            error = APIError("failed", status_code=exc[0])
        assert classify_error(error) == kind

    async def test_stats_bad_request_is_not_called_not_connected(self, mock_app_state):
        from cja_audit_log_monitor.client import APIError

        mock_app_state.client.get_logs_sample.side_effect = APIError(
            "API request failed: 400 - invalid_parameters", status_code=400
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "s")
            text = _empty_text(view)
            assert "request rejected" in text
            assert "not connected" not in text
            assert "disconnected" not in str(app.query_one("#status-row").render())

    async def test_logs_forbidden_says_access_denied(self, mock_app_state):
        from cja_audit_log_monitor.client import APIError

        mock_app_state.client.get_logs.side_effect = APIError(
            "API request failed: 403 - forbidden", status_code=403
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            assert "access denied" in str(view.query_one("#table-message", Static).render())

    async def test_login_failure_in_any_view_updates_header(self, mock_app_state):
        from cja_audit_log_monitor.auth import AuthenticationError

        mock_app_state.client.get_logs.side_effect = AuthenticationError(
            "invalid_client: invalid client_secret parameter\nCheck that CLIENT_ID is right."
        )
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            header = str(app.query_one("#status-row").render())
            assert "disconnected" in header
            assert "invalid client_secret parameter" in header
            assert "\n" not in header
            assert "CLIENT_ID" not in header

    async def test_header_recovers_after_a_good_load(self, mock_app_state):
        from cja_audit_log_monitor.auth import AuthenticationError

        mock_app_state.client.get_logs.side_effect = AuthenticationError("expired")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            assert "disconnected" in str(app.query_one("#status-row").render())
            mock_app_state.client.get_logs.side_effect = None
            await _show_and_load(app, pilot, "l")
            header = str(app.query_one("#status-row").render())
            assert "● connected" in header


async def test_alert_test_login_failure_updates_header(mock_app_state):
    from cja_audit_log_monitor.auth import AuthenticationError

    mock_app_state.client.get_all_logs.side_effect = AuthenticationError("expired")
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press("a")
        await pilot.pause()
        await pilot.click("#test-rules")
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert "disconnected" in str(app.query_one("#status-row").render())


class TestLaterRoundPolish:
    async def test_no_repeated_ids_across_views(self, mock_app_state):
        from collections import Counter

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            for key in "dlmsac":
                await pilot.press(key)
                await pilot.pause()
            ids = Counter(w.id for w in app.query("*") if w.id)
            # empty-state and view-body come from the shared ContentView base and
            # are always looked up inside one view.
            # "label" is used inside every Textual Select widget.
            shared = {"empty-state", "view-body", "label"}
            repeated = {i for i, n in ids.items() if n > 1} - shared
            assert repeated == set()

    async def test_top_users_refit_on_resize(self, mock_app_state, sample_audit_entry):
        entries = [
            sample_audit_entry.model_copy(
                update={
                    "id": f"e{i}",
                    "user_id": f"U{i}@x.e",
                    "user_email": f"someone.with.long.name{i}@example.com",
                }
            )
            for i in range(5)
        ]
        mock_app_state.client.get_logs_sample.return_value = (entries, 5)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(160, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            await pilot.resize_terminal(100, 30)
            await pilot.pause()
            await pilot.pause()
            top = view.query_one("#top-users", Static)
            lines = str(top.render()).splitlines()
            assert lines
            assert all(len(line) <= top.content_region.width for line in lines)

    async def test_zone_labels_follow_a_zone_change(self, mock_app_state, los_angeles_tz):
        import time

        from cja_audit_log_monitor.tui.widgets.log_table import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            os.environ["TZ"] = "America/New_York"
            time.tzset()
            await _show_and_load(app, pilot, "l")
            table = view.query_one(LogTable)
            labels = [str(col.label) for col in table.columns.values()]
            assert labels[0] in ("time (EST)", "time (EDT)")
            dash = await _show_and_load(app, pilot, "d")
            hourly = [
                str(s.render())
                for s in dash.query(".section-label")
                if str(s.render()).startswith("HOURLY")
            ]
            assert hourly[0].endswith(("EST", "EDT"))


def test_hourly_chart_narrow_keeps_23_label():
    from cja_audit_log_monitor.tui.widgets.stats_panel import HourlyChart

    markup = HourlyChart.build_markup({h: h + 1 for h in range(24)}, cell=1)
    axis = markup.splitlines()[-1]
    assert "23" in axis
    assert "18" in axis


def test_detail_values_wrap_inside_their_column():
    from rich.console import Console

    from cja_audit_log_monitor.models import AuditLogEntry
    from cja_audit_log_monitor.tui.modals.entry_detail import build_detail_table

    entry = AuditLogEntry(
        id="6afce25938051732907b1022",
        component_name="Report for dv_67c2101db641e334f220bc0a and a long tail of words",
    )
    console = Console(file=io.StringIO(), width=44, record=True, color_system=None)
    console.print(build_detail_table(entry))
    lines = console.export_text().splitlines()
    start = next(i for i, ln in enumerate(lines) if ln.startswith("component name"))
    value_col = lines[start].index("Report")
    continuation = lines[start + 1]
    assert continuation[:value_col].strip() == ""
    assert continuation[value_col:].strip()


@pytest.mark.parametrize("size", [(100, 30), (140, 40)])
async def test_stats_lists_fit_their_columns(mock_app_state, sample_audit_entry, size):
    from datetime import UTC, datetime, timedelta

    base = datetime.now(UTC)
    entries = [
        sample_audit_entry.model_copy(
            update={
                "id": f"e{i}",
                "user_id": f"U{i % 6}@x.e",
                "user_email": f"someone.with.long.name{i % 6}@example.com",
                "timestamp": base - timedelta(days=i % 7, hours=i),
            }
        )
        for i in range(60)
    ]
    mock_app_state.client.get_logs_sample.return_value = (entries, 60)
    app = _make_app(mock_app_state)
    async with app.run_test(size=size) as pilot:
        view = await _show_and_load(app, pilot, "s")
        await pilot.pause()
        for widget_id in ("#daily-chart", "#user-ranking"):
            widget = view.query_one(widget_id, Static)
            lines = _plain(widget).rstrip("\n").splitlines()
            assert lines, widget_id
            assert all(len(line.rstrip()) <= widget.content_region.width for line in lines), (
                widget_id,
                widget.content_region.width,
                lines,
            )


@pytest.mark.parametrize(("key", "widget_id"), [("d", "#top-users"), ("s", "#user-ranking")])
async def test_lists_stay_blank_until_data_loads(mock_app_state, key, widget_id):
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.press(key)
        await pilot.pause()
        await pilot.resize_terminal(120, 40)
        await pilot.pause()
        view = app._screens[app._current_screen]
        assert "no audit activity" not in _plain(view.query_one(widget_id, Static))


def test_state_survives_bad_config_file(tmp_path) -> None:
    """A bad config file is reported, not raised, when the TUI reads settings."""
    from cja_audit_log_monitor.tui.state import AppState

    path = tmp_path / "config.yaml"
    path.write_text("monitor_interval: [1, \n")
    state = AppState(path)
    assert state.settings.monitor_interval == 60
    assert str(path) in (state.config_error or "")


def test_state_survives_bad_config_file_and_bad_env(tmp_path, monkeypatch) -> None:
    """Bad YAML plus an invalid env value still yields settings and the file error."""
    from cja_audit_log_monitor.tui.state import AppState

    path = tmp_path / "config.yaml"
    path.write_text("monitor_interval: [1, \n")
    monkeypatch.setenv("MONITOR_INTERVAL", "abc")
    state = AppState(path)
    assert state.settings.monitor_interval == 60
    assert str(path) in (state.config_error or "")
    summary = state.config_error_summary or ""
    assert summary.startswith("config.yaml: ")
    assert "environment or .env: monitor_interval" in summary


async def test_header_keeps_connection_status_with_bad_config(mock_app_state, tmp_path) -> None:
    """A config problem shows as a short warning beside the real connection status."""
    mock_app_state.config_error = "full multi-line\npydantic text"
    mock_app_state.config_error_summary = (
        "config.yaml: monitor_interval: Input should be a valid integer"
    )
    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30)) as pilot:
        app.set_connection_status("connected", "org TEST@AdobeOrg")
        await pilot.pause()
        header = _status_text(app)
        assert "● connected" in header
        assert "disconnected" not in header
        assert "config.yaml: monitor_interval: Input should be a valid integer" in header
        assert "\n" not in header
        assert "pydantic text" not in header


# ---------------------------------------------------------------------------
# Data is never parsed as markup
# ---------------------------------------------------------------------------

_BRACKET_USER = "[/b]eve@x.com"
_BRACKET_COMPONENT = "Q3 [/final] report"
_BRACKET_ERROR = "[bold red]boom[/] [/oops]"


def _rendered(widget) -> str:
    """What the widget shows, parsed the way Textual parses it (so bad markup raises)."""
    return widget.render().plain


async def test_bracket_data_shows_literally_in_every_view(
    mock_app_state, sample_audit_entry, monkeypatch
):
    from cja_audit_log_monitor.tui.modals import EntryDetailPanel
    from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen
    from cja_audit_log_monitor.tui.widgets import LogTable

    entry = sample_audit_entry.model_copy(
        update={
            "user_email": _BRACKET_USER,
            "component_name": _BRACKET_COMPONENT,
            "component_type": "[/type]",
            "action": "[/act]",
            "description": "[/desc]",
        }
    )
    state = mock_app_state
    state.client.get_logs_sample.return_value = ([entry], 1)
    state.client.get_logs.return_value = _logs_response([entry], total_elements=1, total_pages=1)
    monkeypatch.setattr(
        "cja_audit_log_monitor.tui.screens.dashboard.analyze_for_anomalies",
        lambda entries, local=False: [{"description": f"odd {_BRACKET_USER} [/x]"}],
    )
    app = _make_app(state)
    async with app.run_test(size=(140, 40)) as pilot:
        # dashboard
        view = await _show_and_load(app, pilot, "d")
        assert _BRACKET_USER in _rendered(view.query_one("#top-users", Static))
        assert "[/x]" in _rendered(view.query_one("#anomalies", Static))

        # log browser: table cell text is the literal string, detail panel too
        view = await _show_and_load(app, pilot, "l")
        table = view.query_one("#log-table", LogTable)
        assert await _wait_for(lambda: table.row_count == 1, pilot)
        cells = [table.get_cell_at((0, col)).plain for col in range(len(table.columns))]
        assert _BRACKET_USER in cells
        assert _BRACKET_COMPONENT in cells
        panel = view.query_one("#entry-detail-panel", EntryDetailPanel)
        panel.show_entry(entry)
        await pilot.pause()
        assert "[/type]" in _rendered(panel.query_one("#detail-title", Static))

        # stats
        view = await _show_and_load(app, pilot, "s")
        assert _BRACKET_USER in _rendered(view.query_one("#user-ranking", Static))
        assert "[/act]" in _rendered(view.query_one("#stats-action-chart", Static))

        # monitor: one poll with a fired alert whose name and message have brackets
        fired = FiredAlert(
            rule_name="[/rule]", message="[bold]msg[/", entry=entry, panel=MagicMock()
        )
        monkeypatch.setattr(state, "check_alerts", lambda entries: [fired])
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        assert isinstance(screen, MonitorScreen)
        screen._last_poll_time = screen._last_poll_time or datetime.now(UTC)
        await _drive_poll(screen, pilot)
        assert await _wait_for(lambda: len(app._notifications) > 0, pilot)
        assert any("[/rule]" in n.message for n in app._notifications)
        assert "[/rule]" in _rendered(screen.query_one("#alert-summary", Static))
        await pilot.pause()
        screen._show_error(_BRACKET_ERROR)
        screen._show_warning("[/warn]")
        await pilot.pause()

        # settings: verify with an API error body
        state.client.verify_connection.return_value = {
            "connected": False,
            "authenticated": False,
            "error": _BRACKET_ERROR,
        }
        view = await _show_and_load(app, pilot, "c")
        assert _BRACKET_ERROR in _rendered(view.query_one("#connection-status", Static))


_LITERAL_CASES = ["[/b]x", "[bold]msg[/", "[/", "tail\\", "a\\[b]", "[/]", "[$danger]"]


@pytest.mark.parametrize("text", _LITERAL_CASES)
def test_literal_survives_markup_parsing(text):
    from textual.content import Content

    from cja_audit_log_monitor.formatters import literal, resolve_tcss_markup

    markup = f"[$danger]{literal(text)}[/$danger]\n[b]x[/b]"
    content = Content.from_markup(resolve_tcss_markup(markup))
    assert content.plain.split("\n")[0].rstrip("​") == text


class TestFocusAndKeys:
    """Escape leaves inputs, details scroll by keyboard, Enter applies stats days (F25, F32)."""

    async def test_escape_leaves_search_without_navigating_or_clearing(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            await pilot.press("slash", "a", "b", "c")
            await pilot.pause()
            search = app.query_one("#filter-search", Input)
            assert app.focused is search
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused is not search
            await pilot.press("d")
            await pilot.pause()
            assert app._current_screen == "dashboard"
            assert search.value == "abc"

    async def test_escape_in_search_keeps_open_details(self, mock_app_state):
        from cja_audit_log_monitor.tui.modals.entry_detail import EntryDetailPanel

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            await pilot.press("enter")
            await pilot.pause()
            await pilot.press("slash")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.query_one(EntryDetailPanel).is_visible()

    async def test_detail_panel_scrolls_with_keyboard(self, mock_app_state, sample_audit_entry):
        from cja_audit_log_monitor.tui.modals.entry_detail import EntryDetailPanel

        entry = sample_audit_entry.model_copy(
            update={"changes": {f"field{i}": f"value {i}" for i in range(60)}}
        )
        mock_app_state.client.get_logs.return_value.content[0] = entry
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 30)) as pilot:
            await _show_and_load(app, pilot, "l")
            await pilot.press("enter")
            await pilot.pause()
            panel = app.query_one(EntryDetailPanel)
            await pilot.press("tab")
            await pilot.pause()
            assert app.focused is panel
            assert panel.scroll_y == 0
            await pilot.press("pagedown")
            await pilot.pause()
            assert panel.scroll_y > 0

    async def test_escape_in_detail_panel_closes_it_and_returns_to_table(self, mock_app_state):
        from cja_audit_log_monitor.tui.modals.entry_detail import EntryDetailPanel
        from cja_audit_log_monitor.tui.widgets import LogTable

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            await pilot.press("enter", "tab")
            await pilot.pause()
            assert app.focused is app.query_one(EntryDetailPanel)
            await pilot.press("escape")
            await pilot.pause()
            assert not app.query_one(EntryDetailPanel).is_visible()
            assert app.focused is app.query_one(LogTable)

    async def test_enter_in_stats_days_reloads(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "s")
            mock_app_state.client.get_logs_sample.reset_mock()
            box = app.query_one("#days-input", Input)
            box.focus()
            box.value = ""
            await pilot.press("3", "0", "enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            query = mock_app_state.client.get_logs_sample.call_args.args[0]
            assert (query.end_date - query.start_date).days in (29, 30)
            assert box.value == "30"

    async def test_stats_days_box_shows_the_clamped_value(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "s")
            box = app.query_one("#days-input", Input)
            box.focus()
            box.value = "-5"
            await pilot.press("enter")
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert box.value == "1"

    async def test_help_lists_search_and_tab(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            await pilot.pause()
            sections = {
                str(s.render()): b
                for s, b in zip(
                    app.screen.query(".help-section"), app.screen.query(".help-section-body")
                )
            }
            everywhere = next(str(b.render()) for t, b in sections.items() if "EVERYWHERE" in t)
            lines = everywhere.splitlines()
            assert any(ln.strip().startswith("/") for ln in lines)
            assert any(ln.strip().startswith("tab") for ln in lines)


class TestConfiguredDefaults:
    """The TUI starts from default_page_size, default_days and monitor_interval."""

    @staticmethod
    def _page_by_size(state, sample_audit_entry):
        """Make the mock client return as many rows as the query's page size asks for."""
        from cja_audit_log_monitor.models import AuditLogResponse

        def get_logs(query):
            rows = [
                sample_audit_entry.model_copy(update={"id": f"row-{n}"})
                for n in range(query.page_size)
            ]
            return AuditLogResponse(
                content=rows,
                total_elements=500,
                total_pages=500 // query.page_size,
                number_of_elements=len(rows),
                first=True,
                last=False,
                number=0,
                size=query.page_size,
            )

        state.client.get_logs.side_effect = get_logs

    async def test_log_browser_uses_default_page_size(self, mock_app_state, sample_audit_entry):
        from cja_audit_log_monitor.tui.widgets import LogTable

        mock_app_state.settings.default_page_size = 25
        self._page_by_size(mock_app_state, sample_audit_entry)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            assert app.query_one("#log-table", LogTable).row_count == 25

    async def test_monitor_interval_box_starts_at_the_setting(self, mock_app_state):
        from textual.widgets import Input

        mock_app_state.settings.monitor_interval = 30
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("m")
            assert await _wait_for(lambda: app.query("#interval-input"), pilot)
            assert app.query_one("#interval-input", Input).value == "30"
            assert mock_app_state.monitor.interval == 30

    async def test_stats_days_box_and_query_start_at_the_setting(self, mock_app_state):
        from textual.widgets import Input

        mock_app_state.settings.default_days = 3
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "s")
            assert app.query_one("#days-input", Input).value == "3"
            query = mock_app_state.client.get_logs_sample.call_args.args[0]
            assert (query.end_date - query.start_date).days == 3

    async def test_dashboard_window_follows_default_days(self, mock_app_state):
        mock_app_state.settings.default_days = 3
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "d")
            query = mock_app_state.client.get_logs_sample.call_args.args[0]
            assert (query.end_date - query.start_date).days == 3
            labels = [_plain(s) for s in app.query(".stat-label")]
            assert "last 3 days" in [label.strip() for label in labels]

    async def test_reload_applies_new_defaults_to_open_views(
        self, mock_app_state, sample_audit_entry, tmp_path
    ):
        from textual.widgets import Input

        config = tmp_path / "config.yaml"
        config.write_text("default_page_size: 20\nmonitor_interval: 30\ndefault_days: 3\n")
        mock_app_state._config_path = config
        mock_app_state.refresh_client = MagicMock()  # keep the mock client through the reload
        mock_app_state.verify_connection = MagicMock(
            return_value={"connected": False, "error": "offline"}
        )
        self._page_by_size(mock_app_state, sample_audit_entry)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "m")
            await _show_and_load(app, pilot, "s")
            await _show_and_load(app, pilot, "l")
            await pilot.press("c")
            await pilot.pause()
            app.query_one("#reload-button", Button).press()
            assert await _wait_for(
                lambda: mock_app_state.client.get_logs.call_args is not None
                and mock_app_state.client.get_logs.call_args.args[0].page_size == 20,
                pilot,
            )
            assert app._screens["monitor"].query_one("#interval-input", Input).value == "30"
            assert app._screens["stats"].query_one("#days-input", Input).value == "3"
            assert mock_app_state.filters.page_size == 20
            assert await _wait_for(lambda: _reloaded(app), pilot)

    async def test_reload_relabels_the_dashboard_window(self, mock_app_state, tmp_path):
        config = tmp_path / "config.yaml"
        config.write_text("default_days: 3\n")
        mock_app_state._config_path = config
        mock_app_state.refresh_client = MagicMock()
        mock_app_state.verify_connection = MagicMock(
            return_value={"connected": False, "error": "offline"}
        )
        app = _make_app(mock_app_state)

        def labels():
            return [_plain(s).strip() for s in app.query(".stat-label")]

        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "d")
            assert "last 7 days" in labels()
            await pilot.press("c")
            await pilot.pause()
            app.query_one("#reload-button", Button).press()
            assert await _wait_for(lambda: "last 3 days" in labels(), pilot)
            assert await _wait_for(lambda: _reloaded(app), pilot)


def _dot_color(app):
    """Hex color the status row paints its dot with."""
    strip = app.query_one("#status-row", Static).render_line(0)
    segment = next(seg for seg in strip if "●" in seg.text)
    return Color.from_rich_color(segment.style.color).hex


class TestStatusDotColor:
    """The dot is painted from the theme, so disconnected is the theme's error color."""

    async def test_disconnected_dot_uses_theme_error_color(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            app.set_connection_status("disconnected", "boom")
            await pilot.pause()
            assert _dot_color(app) == Color.parse(app.theme_variables["error"]).hex


class TestChartLoadingState:
    """Charts say "loading…" while their view's load runs, then show the data."""

    @pytest.mark.parametrize(
        ("key", "chart_ids"),
        [
            ("d", ["#action-chart", "#hourly-chart"]),
            ("s", ["#stats-action-chart", "#stats-hourly-chart"]),
        ],
    )
    async def test_charts_show_loading_until_the_load_ends(
        self, mock_app_state, sample_audit_entries, key, chart_ids
    ):
        import threading

        started, release = threading.Event(), threading.Event()

        def slow_sample(query, max_entries=None):
            started.set()
            release.wait(5)
            return sample_audit_entries, len(sample_audit_entries)

        mock_app_state.client.get_logs_sample.side_effect = slow_sample
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.press(key)
            await pilot.pause()
            view = app._screens[app._current_screen]
            view.refresh_data()
            assert await _wait_for(started.is_set, pilot)
            charts = [view.query_one(chart_id, Static) for chart_id in chart_ids]
            assert all("loading…" in str(c.render()) for c in charts)
            release.set()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert all("loading…" not in str(c.render()) for c in charts)
            assert "no data" not in str(charts[0].render())

    async def test_a_failed_load_does_not_leave_loading_text(self, mock_app_state):
        mock_app_state.client.get_logs_sample.side_effect = RuntimeError("boom")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 42)) as pilot:
            view = await _show_and_load(app, pilot, "s")
            for chart_id in ("#stats-action-chart", "#stats-hourly-chart"):
                assert "loading…" not in str(view.query_one(chart_id, Static).render())


class TestPaginationButtons:
    """prev and next are disabled whenever they cannot be used."""

    async def test_disabled_before_the_first_load(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            view = app._screens["logs"]
            assert view.query_one("#prev-page", Button).disabled
            assert view.query_one("#next-page", Button).disabled

    async def test_disabled_after_an_error(self, mock_app_state, sample_audit_entry):
        from cja_audit_log_monitor.models import AuditLogResponse

        page = AuditLogResponse(
            content=[sample_audit_entry.model_copy(update={"id": f"e{i}"}) for i in range(3)],
            total_elements=250,  # three pages at the default page size of 100
            total_pages=3,
            number_of_elements=3,
            first=False,
            last=False,
            number=1,
            size=50,
        )
        mock_app_state.client.get_logs.return_value = page
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.pause()
            mock_app_state.filters.page = 1  # after startup, which resets to the first page
            view = await _show_and_load(app, pilot, "l")
            assert not view.query_one("#prev-page", Button).disabled
            assert not view.query_one("#next-page", Button).disabled
            mock_app_state.client.get_logs.side_effect = RuntimeError("boom")
            view.refresh_data()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert view.query_one("#prev-page", Button).disabled
            assert view.query_one("#next-page", Button).disabled


class TestLoadApplyErrors:
    """A failure inside a view's apply callback leaves a traceback in the log."""

    async def test_apply_exception_is_logged_with_traceback(self, mock_app_state, caplog):
        import logging

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            shown: list[Exception] = []
            view.show_load_error = shown.append

            def bad_apply(_value):
                raise ValueError("apply blew up")

            with caplog.at_level(logging.ERROR):
                view.run_load(lambda: 1, bad_apply)
                assert await _wait_for(lambda: bool(shown), pilot)
            assert [type(e) for e in shown] == [ValueError]
            records = [r for r in caplog.records if r.exc_info]
            assert any("apply blew up" in str(r.exc_info[1]) for r in records)


class TestFilterDropdownEscape:
    """Escape closes an open dropdown first; only the next Escape leaves the filter bar."""

    async def test_first_escape_only_closes_the_dropdown(self, mock_app_state):
        from textual.widgets import Select
        from textual.widgets._select import SelectOverlay

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await _show_and_load(app, pilot, "l")
            select = app.query_one("#filter-action", Select)
            select.focus()
            await pilot.pause()
            await pilot.press("enter")
            assert await _wait_for(lambda: select.expanded, pilot)
            assert isinstance(app.focused, SelectOverlay)
            await pilot.press("escape")
            assert await _wait_for(lambda: not select.expanded, pilot)
            await pilot.pause()
            assert app.focused is select
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused is not select


class TestNarrowLayout:
    """At 80 columns the sidebar is compact and the footer still shows quit."""

    async def test_narrow_sidebar_and_footer(self, mock_app_state):
        from textual.widgets import Footer

        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert app.screen.has_class("-narrow")
            assert app.query_one("#sidebar").region.width <= 6
            footer_text = " ".join(
                str(w.render()) for w in app.query_one(Footer).query("*") if hasattr(w, "render")
            )
            assert "quit" in footer_text

    async def test_footer_keeps_quit_visible_with_details_open(self, mock_app_state):
        from textual.widgets import Footer

        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await _show_and_load(app, pilot, "l")
            table = app.query_one("#log-table")
            assert table.row_count > 0
            await pilot.press("enter")
            panel = app.screen_stack[0].query_one("#entry-detail-panel")
            assert await _wait_for(panel.is_visible, pilot)
            await pilot.pause()

            def quit_visible() -> bool:
                keys = [
                    w for w in app.query_one(Footer).query("FooterKey") if "quit" in str(w.render())
                ]
                return bool(keys) and all(k.region.right <= app.size.width for k in keys)

            assert await _wait_for(quit_visible, pilot)

    async def test_wide_sidebar_keeps_labels(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert app.screen.has_class("-normal")
            assert app.query_one("#sidebar").region.width == 22

    @staticmethod
    def _label(app, nav_id: str) -> str:
        return str(app.screen_stack[0].query_one(f"#{nav_id}").render()).strip()

    async def test_narrow_nav_label_is_key_only(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            assert self._label(app, "nav-logs") == "l"

    async def test_labels_follow_resize(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            assert self._label(app, "nav-logs") == "l logs"
            await pilot.resize_terminal(80, 24)
            assert await _wait_for(lambda: self._label(app, "nav-logs") == "l", pilot)
            await pilot.resize_terminal(140, 40)
            assert await _wait_for(lambda: self._label(app, "nav-logs") == "l logs", pilot)

    async def test_resize_under_modal_updates_labels(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            assert await _wait_for(lambda: isinstance(app.screen, HelpScreen), pilot)
            await pilot.resize_terminal(80, 24)
            assert await _wait_for(lambda: self._label(app, "nav-logs") == "l", pilot)
            await pilot.press("escape")
            assert await _wait_for(lambda: not isinstance(app.screen, HelpScreen), pilot)
            assert self._label(app, "nav-logs") == "l"

    async def test_click_nav_item_at_80_columns(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.click("#nav-logs")
            assert await _wait_for(lambda: app._current_screen == "logs", pilot)


class TestConfigHelpDashboardFit:
    """The config view, help overlay and dashboard fit every terminal size."""

    @staticmethod
    def _value_for(view, label: str):
        from textual.widgets import Static as _Static

        for row in view.query(".settings-row"):
            texts = [str(w.render()) for w in row.query(_Static)]
            if texts and texts[0].strip() == label:
                return row.query(".settings-value").first()
        raise AssertionError(f"no config row {label!r}")

    async def test_config_shows_api_url_at_80_columns(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("c")
            await pilot.pause()
            value = self._value_for(app._screens["settings"], "api base url")
            assert value.region.width >= len(str(mock_app_state.settings.api_base_url))
            assert str(mock_app_state.settings.api_base_url) in str(value.render())

    async def test_config_path_on_one_line_at_100_columns(self, mock_app_state):
        from pathlib import Path

        mock_app_state._config_path = Path("/Users/someone/.cja-audit-log-monitor/config.yaml")
        app = _make_app(mock_app_state)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.press("c")
            await pilot.pause()
            value = self._value_for(app._screens["settings"], "config file")
            assert value.region.height == 1
            assert "config.yaml" in str(value.render())

    async def test_help_body_scrolls_with_keyboard_at_80x24(self, mock_app_state):
        from textual.containers import VerticalScroll

        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.pause()
            await pilot.press("question_mark")
            assert await _wait_for(lambda: isinstance(app.screen, HelpScreen), pilot)
            body = app.screen.query_one("#help-overlay")
            assert isinstance(body, VerticalScroll)
            assert await _wait_for(lambda: app.screen.focused is body, pilot)
            assert body.max_scroll_y > 0
            await pilot.press("pagedown")
            assert await _wait_for(lambda: body.scroll_y > 0, pilot)

    async def test_dashboard_charts_grow_on_wide_terminals(self, mock_app_state):
        heights = {}
        for size in [(140, 42), (200, 60)]:
            app = _make_app(mock_app_state)
            async with app.run_test(size=size) as pilot:
                view = await _show_and_load(app, pilot, "d")
                heights[size] = view.query_one("#hourly-chart").region.height
        assert heights[(200, 60)] > heights[(140, 42)], heights

    async def test_monitor_status_border_follows_state(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 42)) as pilot:
            await pilot.press("m")
            await pilot.pause()
            view = app._screens["monitor"]
            row = view.query_one("#monitor-status")
            colors = {}
            for state in ("stopped", "running", "error"):
                view._set_status(state)
                await pilot.pause()
                colors[state] = row.styles.border_left[1]
            assert len({str(c) for c in colors.values()}) == 3, colors


class TestWideDashboardFill:
    """Wide dashboards fill their columns; short ones keep the chart axis."""

    async def test_hourly_chart_fills_its_column_at_200x60(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(200, 60)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            chart = view.query_one("#hourly-chart")
            column = view.query_one("#dash-left")
            assert await _wait_for(lambda: chart.region.width > 0, pilot)
            widest = max(len(line.rstrip()) for line in _plain(chart).splitlines())
            assert widest >= 0.7 * column.content_region.width, (
                widest,
                column.content_region.width,
            )

    @pytest.mark.parametrize("size", [(80, 24), (100, 30), (140, 42)])
    async def test_hourly_chart_cells_unchanged_below_wide(self, mock_app_state, size):
        app = _make_app(mock_app_state)
        async with app.run_test(size=size) as pilot:
            view = await _show_and_load(app, pilot, "d")
            chart = view.query_one("#hourly-chart")
            widest = max(len(line.rstrip()) for line in _plain(chart).splitlines())
            assert widest <= 49, widest

    async def test_hourly_chart_keeps_axis_at_160x24(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(160, 24)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            chart = view.query_one("#hourly-chart")
            assert chart.region.height >= 7, chart.region.height

    async def test_anomalies_label_is_one_line_at_80x24(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            view = await _show_and_load(app, pilot, "d")
            card = view.query_one("#stat-alerts").parent
            labels = [w for w in card.query(".stat-label")]
            assert labels and all(w.region.height == 1 for w in labels)

    async def test_cjk_user_names_do_not_scroll_sideways_at_80x24(
        self, mock_app_state, sample_audit_entry
    ):
        from rich.cells import cell_len

        from cja_audit_log_monitor.tui.widgets import LogTable

        entries = [
            sample_audit_entry.model_copy(
                update={"id": f"e{i}", "user_email": "山田太郎山田太郎" * 4}
            )
            for i in range(3)
        ]
        app = _make_app(mock_app_state)
        async with app.run_test(size=(80, 24)) as pilot:
            await pilot.press("l")
            await pilot.pause()
            app._screens["logs"]._update_table(entries, 3)
            await pilot.pause()
            table = app.query_one("#log-table", LogTable)
            assert table.virtual_size.width <= table.scrollable_content_region.width
            users = [str(table.get_row_at(i)[1]) for i in range(table.row_count)]
            assert all(u.endswith("…") for u in users), users
            assert all(cell_len(u) <= table.columns["user"].width for u in users), users


# ---------------------------------------------------------------------------
# Guards that see what a user sees: real toasts and the first load (G38)
# ---------------------------------------------------------------------------


async def test_monitor_toasts_show_markup_literally(mock_app_state):
    """Toasts are rendered (notifications=True), so markup in data would raise here."""
    from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30), notifications=True) as pilot:
        await pilot.press("m")
        await pilot.pause()
        screen = app._screens["monitor"]
        assert isinstance(screen, MonitorScreen)
        screen._show_alert("[/rule]: [bold]msg[/")
        screen._show_error("[bold red]boom[/] [/oops]")
        screen._show_warning("[/warn]")
        await pilot.pause()
        assert await _wait_for(lambda: len(app.screen.query("Toast")) == 3, pilot)
        await pilot.pause()
        assert app.is_running
        assert any("[/rule]" in n.message for n in app._notifications)


@pytest.mark.real_mount
@pytest.mark.parametrize(
    ("key", "loaded"),
    [
        ("s", lambda state: state.client.get_logs_sample.called),
        ("c", lambda state: state.client.verify_connection.called),
    ],
)
async def test_views_load_data_when_first_shown(mock_app_state, key, loaded):
    """With the real on_content_mounted, showing a view the first time starts its load."""
    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30)) as pilot:
        await app.workers.wait_for_complete()
        mock_app_state.client.get_logs_sample.reset_mock()
        mock_app_state.client.verify_connection.reset_mock()
        await pilot.press(key)
        assert await _wait_for(lambda: loaded(mock_app_state), pilot)
        await app.workers.wait_for_complete()


@pytest.mark.real_mount
async def test_app_loads_dashboard_on_start(mock_app_state):
    """Starting the app shows dashboard data without any key press."""
    from cja_audit_log_monitor.tui.screens.dashboard import DashboardScreen

    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30)) as pilot:
        assert await _wait_for(lambda: mock_app_state.client.get_logs_sample.called, pilot)
        await app.workers.wait_for_complete()
        await pilot.pause()
        view = app._screens["dashboard"]
        assert isinstance(view, DashboardScreen)
        assert await _wait_for(lambda: "user" in _plain(view.query_one("#top-users")), pilot)


async def test_tui_starts_on_any_bad_config(bad_config) -> None:
    """The TUI starts on any config mistake and shows a one line summary."""
    from .conftest import SECRET_MARK

    state = AppState(bad_config)
    app = _make_app(state)
    async with app.run_test(size=(140, 40)) as pilot:
        await pilot.pause()
        assert app.is_running
        assert state.config_error_summary
        assert SECRET_MARK not in (state.config_error or "")
        assert state.config_error_summary.split(":")[0] in _status_text(app)


async def test_tui_reload_on_any_bad_config(bad_config, tmp_path) -> None:
    """Reload settings onto any config mistake keeps the app running and says why."""
    good = tmp_path / "good.yaml"
    good.write_text("monitor_interval: 30\n")
    good.chmod(0o600)
    state = AppState(good)
    app = _make_app(state)
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        await pilot.press("c")
        await pilot.pause()
        state._config_path = bad_config
        view = app._screens["settings"]
        await view._reload_settings()
        await pilot.pause()
        assert app.is_running
        assert state.config_error_summary


# ---------------------------------------------------------------------------
# Logged warnings show as toasts (G12)
# ---------------------------------------------------------------------------


async def test_tui_shows_config_permission_warning(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("monitor_interval: 30\n")
    path.chmod(0o644)
    app = _make_app(AppState(path))
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        assert await _wait_for(
            lambda: any("chmod 600" in n.message for n in app._notifications), pilot
        )


async def test_tui_shows_unknown_key_warning(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("monitor_intervall: 30\n")
    path.chmod(0o600)
    app = _make_app(AppState(path))
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        assert await _wait_for(
            lambda: any("monitor_intervall" in n.message for n in app._notifications), pilot
        )


async def test_tui_shows_a_warning_logged_on_a_worker_thread(mock_app_state) -> None:
    import asyncio
    import logging

    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        await pilot.pause()
        log = logging.getLogger("cja_audit_log_monitor.notifications")
        await asyncio.to_thread(log.error, "Failed to send webhook to example.com/…")
        assert await _wait_for(
            lambda: any("Failed to send webhook" in n.message for n in app._notifications),
            pilot,
        )


async def test_toast_log_handler_is_removed_after_the_app_ends(mock_app_state) -> None:
    import logging

    from cja_audit_log_monitor.tui.log_toasts import ToastLogHandler

    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
    handlers = logging.getLogger("cja_audit_log_monitor").handlers
    assert not any(isinstance(h, ToastLogHandler) for h in handlers)


class TestReloadKeepsWhatWorks:
    """A failed reload keeps the working settings; toggles survive a reload (G40)."""

    @staticmethod
    def _state(tmp_path):
        path = tmp_path / "config.yaml"
        path.write_text("client_id: from-file\nmonitor_interval: 30\n")
        path.chmod(0o600)
        state = AppState(path)
        assert state.settings.client_id == "from-file"
        return state, path

    def test_reload_onto_a_broken_config_keeps_working_settings(self, tmp_path):
        from cja_audit_log_monitor.config import ConfigError

        state, path = self._state(tmp_path)
        path.write_text("monitor_interval: [unclosed\n")
        with pytest.raises(ConfigError):
            state.reload_settings()
        assert state.settings.client_id == "from-file"
        assert state.settings.monitor_interval == 30
        assert state.config_error_summary

    def test_reload_keeps_rule_toggles(self, tmp_path):
        state, path = self._state(tmp_path)
        state.alert_engine.rules[0].enabled = False
        name = state.alert_engine.rules[0].name
        path.write_text("client_id: from-file\nmonitor_interval: 45\n")
        state.reload_settings()
        assert state.settings.monitor_interval == 45
        rules = {rule.name: rule for rule in state.alert_engine.rules}
        assert rules[name].enabled is False

    def test_reset_rules_turns_toggles_back_on(self, tmp_path):
        state, path = self._state(tmp_path)
        state.alert_engine.rules[0].enabled = False
        state.reload_settings()
        state.reset_alert_rules()
        assert all(rule.enabled for rule in state.alert_engine.rules)

    async def test_reload_button_with_a_broken_config_warns(self, tmp_path):
        state, path = self._state(tmp_path)
        app = _make_app(state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            await pilot.press("c")
            await pilot.pause()
            path.write_text("monitor_interval: [unclosed\n")
            await app._screens["settings"]._reload_settings()
            await pilot.pause()
            assert any("keeping the current settings" in n.message for n in app._notifications)
            assert state.settings.client_id == "from-file"


# ---------------------------------------------------------------------------
# Quit is immediate, even with a request in progress (G5)
# ---------------------------------------------------------------------------


@pytest.mark.real_mount
async def test_quit_during_hung_request_exits_fast(fake_api, tmp_path, monkeypatch) -> None:
    """q during a request exits at once, and the request is never retried after quit."""
    import asyncio
    import threading
    import time

    import httpx

    from .fakeapi import raw_entry

    fake_api.entries = [raw_entry(1)]
    for key, value in fake_api.env(tmp_path / "missing.yaml").items():
        monkeypatch.setenv(key, value)
    built: list[float] = []
    real_client = httpx.Client

    def counting_client(*args, **kwargs):
        built.append(time.monotonic())
        return real_client(*args, **kwargs)

    monkeypatch.setattr("cja_audit_log_monitor.client.httpx.Client", counting_client)
    fake_api.block.set()
    # Release the server after 10 seconds, so a regression fails instead of hanging.
    threading.Timer(10, fake_api.block.clear).start()
    from cja_audit_log_monitor.tui.screens.dashboard import DashboardScreen

    fetch_done = threading.Event()
    real_fetch = DashboardScreen._fetch

    def tracked_fetch(self):
        try:
            return real_fetch(self)
        finally:
            fetch_done.set()

    monkeypatch.setattr(DashboardScreen, "_fetch", tracked_fetch)
    app = CJAAuditApp()
    async with app.run_test(size=(100, 30)) as pilot:
        assert await asyncio.to_thread(fake_api.blocked.wait, 10)
        requests_before = len(fake_api.requests)
        pressed = time.monotonic()
        await pilot.press("q")
        fake_api.block.clear()  # the server answers right away, as in the review's repro
    elapsed = time.monotonic() - pressed
    # Wait until the abandoned fetch thread has ended, however it ends.
    assert await asyncio.to_thread(fetch_done.wait, 15)
    assert elapsed < 2, f"quit took {elapsed:.1f}s"
    assert [t for t in built if t > pressed] == [], "a new HTTP client was built after quit"
    assert len(fake_api.requests) == requests_before, "a request was sent after quit"


# ---------------------------------------------------------------------------
# A late or failing load never ends the app (G32, G34)
# ---------------------------------------------------------------------------


async def test_on_error_that_raises_does_not_end_the_app(mock_app_state) -> None:
    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30)) as pilot:
        await pilot.pause()
        view = app._screens["dashboard"]

        def fetch():
            raise RuntimeError("fetch failed")

        def on_error(error):
            raise ValueError("the error handler failed too")

        view.run_load(fetch, lambda result: None, on_error=on_error)
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._exception is None
        assert app.is_running


async def test_verify_result_during_reload_is_dropped(mock_app_state, monkeypatch) -> None:
    """The config view's verify that ends while the view is rebuilt is dropped, no crash."""
    import asyncio
    import threading

    started, release, queued = threading.Event(), threading.Event(), threading.Event()
    ok = dict(mock_app_state.client.verify_connection.return_value)
    slow: list[int] = []

    def verify():
        if slow:
            slow.pop()
            started.set()
            release.wait(10)
        return ok

    mock_app_state.client.verify_connection.side_effect = verify
    monkeypatch.setattr(mock_app_state, "reload_settings", lambda: None)
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        await pilot.press("c")
        await pilot.pause()
        view = app._screens["settings"]
        slow.append(1)
        view.refresh_data()
        assert await asyncio.to_thread(started.wait, 10)
        original = app.call_from_thread

        def spy(callback, *args, **kwargs):
            queued.set()
            return original(callback, *args, **kwargs)

        app.call_from_thread = spy
        real_mount_all = view.mount_all

        def mount_all(widgets, **kwargs):
            # recompose() removed the old children; the old request ends right now.
            release.set()
            assert queued.wait(5)
            return real_mount_all(widgets, **kwargs)

        monkeypatch.setattr(view, "mount_all", mount_all)
        await view._reload_settings()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert app._exception is None
        assert app.is_running


@pytest.mark.parametrize("outcome", ["fails", "succeeds"])
async def test_alert_test_run_across_reload_is_dropped(mock_app_state, outcome) -> None:
    """A "test rules" run that started before a reload does not land after it (G34)."""
    import asyncio
    import threading

    started, release = threading.Event(), threading.Event()

    def get_all_logs(*args, **kwargs):
        started.set()
        release.wait(10)
        if outcome == "fails":
            raise RuntimeError("Request failed: client has been closed")
        return mock_app_state.client.get_logs_sample.return_value[0]

    mock_app_state.client.get_all_logs.side_effect = get_all_logs
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        await pilot.press("a")
        await pilot.pause()
        view = app._screens["alerts"]
        app.query_one("#test-rules").press()
        assert await asyncio.to_thread(started.wait, 10)
        before = _plain(view.query_one("#test-results", Static))
        app.settings_reloaded()
        release.set()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert _plain(view.query_one("#test-results", Static)) == before
        assert "disconnected" not in _status_text(app)


# ---------------------------------------------------------------------------
# Hung requests do not use up the threads (G33)
# ---------------------------------------------------------------------------


async def test_hung_refreshes_use_one_thread_and_other_views_still_load(mock_app_state) -> None:
    import asyncio
    import threading

    release = threading.Event()
    verify_calls: list[int] = []
    ok = dict(mock_app_state.client.verify_connection.return_value)

    def hung_verify():
        verify_calls.append(1)
        release.wait(15)
        return ok

    mock_app_state.client.verify_connection.side_effect = hung_verify
    app = _make_app(mock_app_state)
    try:
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.pause()
            dashboard = app._screens["dashboard"]
            for _ in range(40):  # more presses of r than the thread pool has threads
                dashboard.refresh_data()
                await pilot.pause()
            assert await _wait_for(lambda: len(verify_calls) >= 1, pilot)
            assert len(verify_calls) == 1  # one fetch at a time for the view

            mock_app_state.client.get_logs_sample.reset_mock()
            await pilot.press("s")
            await pilot.pause()
            app._screens["stats"].refresh_data()
            assert await _wait_for(lambda: mock_app_state.client.get_logs_sample.called, pilot)

            release.set()  # the hung fetch ends; the newest pending one runs next
            assert await _wait_for(lambda: len(verify_calls) == 2, pilot)
            await app.workers.wait_for_complete()
    finally:
        release.set()
        await asyncio.sleep(0)


class TestExportDialogReports:
    """The export dialog always reports its result (G25, G40, G44)."""

    async def _open(self, app, pilot):
        await pilot.pause()
        await pilot.press("e")
        await pilot.pause()
        return app.screen

    async def test_ctrl_p_does_not_open_the_command_palette(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            await pilot.pause()
            await pilot.press("ctrl+p")
            await pilot.pause()
            assert type(app.screen).__name__ != "CommandPalette"

    async def test_escape_during_write_still_reports_the_file(
        self, mock_app_state, sample_audit_entries, tmp_path, monkeypatch
    ):
        import threading

        from cja_audit_log_monitor.tui.modals import export_dialog

        started, release = threading.Event(), threading.Event()
        real_export = export_dialog.export_entries

        def slow_export(*args, **kwargs):
            started.set()
            release.wait(10)
            return real_export(*args, **kwargs)

        monkeypatch.setattr(export_dialog, "export_entries", slow_export)
        mock_app_state.page_loaded = True
        mock_app_state.entries = sample_audit_entries
        target = tmp_path / "out.json"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40), notifications=True) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.pause()
            await pilot.click("#export-button")
            assert await _wait_for(started.is_set, pilot)
            await pilot.press("escape")
            await pilot.pause()
            release.set()
            assert await _wait_for(
                lambda: any("exported" in n.message for n in app._notifications), pilot
            )
        assert target.exists()

    async def test_limit_reached_only_when_the_limit_cut_the_result(
        self, mock_app_state, sample_audit_entry, tmp_path
    ):
        many = [sample_audit_entry.model_copy(update={"id": f"m{i}"}) for i in range(5)]
        mock_app_state.page_loaded = True
        mock_app_state.entries = many[:1]
        mock_app_state.total_entries = 6
        mock_app_state.client.get_logs_sample.return_value = (many, 6)
        target = tmp_path / "all.json"
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40), notifications=True) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#scope-all").value = True
            dialog.query_one("#output-path").value = str(target)
            await pilot.pause()
            await pilot.click("#export-button")
            assert await _wait_for(
                lambda: any("exported" in n.message for n in app._notifications), pilot
            )
            message = next(n.message for n in app._notifications if "exported" in n.message)
            assert "limit reached" not in message


async def test_hostile_names_in_every_tui_view(mock_app_state) -> None:
    """Review Focus 4 in the TUI: no control code from data in any view's output."""
    from .test_cli import _hostile_entry

    entry = _hostile_entry()
    mock_app_state.client.get_logs_sample.return_value = ([entry], 1)
    mock_app_state.client.get_logs.return_value = _logs_response([entry])
    mock_app_state.client.get_all_logs.return_value = [entry]
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        for key in "dlsac":
            await _show_and_load(app, pilot, key)
            screen = app.export_screenshot()
            assert "\x1b]0;" not in screen and "PWNED\x07" not in screen
        assert app.is_running


async def test_two_entries_with_the_same_id_on_one_page(mock_app_state, sample_audit_entries):
    """G35: a repeated id on one page still shows every row."""
    from cja_audit_log_monitor.tui.widgets import LogTable

    page = sample_audit_entries[:5]
    page[3] = page[3].model_copy(update={"id": page[1].id})
    mock_app_state.client.get_logs.return_value = _logs_response(page, total_elements=5)
    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40)) as pilot:
        view = await _show_and_load(app, pilot, "l")
        table = view.query_one("#log-table", LogTable)
        assert await _wait_for(lambda: table.row_count == 5, pilot)
        view.refresh_data()
        await app.workers.wait_for_complete()
        await pilot.pause()
        assert table.row_count == 5


@pytest.mark.parametrize("size", [(80, 24), (100, 30)])
@pytest.mark.parametrize(("key", "widget_id"), [("d", "#top-users"), ("s", "#user-ranking")])
async def test_top_users_cjk_name_fits_one_line(
    mock_app_state, sample_audit_entries, size, key, widget_id
):
    """G36: names are cut by cell width, so a wide name never wraps the count."""
    from rich.cells import cell_len

    cjk = "日本語のユーザー名前テスト@example.com"
    entries = [
        e.model_copy(update={"user_email": cjk, "user_id": "U-cjk"}) for e in sample_audit_entries
    ]
    mock_app_state.client.get_logs_sample.return_value = (entries, len(entries))
    app = _make_app(mock_app_state)
    async with app.run_test(size=size) as pilot:
        view = await _show_and_load(app, pilot, key)
        widget = view.query_one(widget_id, Static)
        await pilot.pause()
        width = widget.content_region.width
        lines = [line for line in _plain(widget).splitlines() if line.strip()]
        assert lines
        for line in lines:
            assert cell_len(line.rstrip()) <= width - 1, line


@pytest.mark.parametrize("modal_key", ["question_mark", "e"])
@pytest.mark.parametrize("view_key", ["d", "s", "a", "c"])
async def test_focus_and_scroll_survive_modal(
    mock_app_state, sample_audit_entries, modal_key, view_key
):
    """G37: closing the help overlay or export dialog leaves focus and scroll as they were."""
    mock_app_state.page_loaded = True
    mock_app_state.entries = sample_audit_entries
    app = _make_app(mock_app_state)
    async with app.run_test(size=(80, 24)) as pilot:
        view = await _show_and_load(app, pilot, view_key)
        await pilot.pause()
        before = (app.focused, [w.scroll_y for w in view.query("VerticalScroll")])
        await pilot.press(modal_key)
        await pilot.pause()
        await pilot.press("escape")
        await pilot.pause()
        after = (app.focused, [w.scroll_y for w in view.query("VerticalScroll")])
        assert after == before


class TestLayoutAndKeys:
    """Keys and small view fixes (G40)."""

    async def test_escape_leaves_stats_days_box(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press("s")
            await pilot.pause()
            box = app._screens["stats"].query_one("#days-input", Input)
            box.focus()
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert app.focused is not box
            await pilot.press("d")
            await pilot.pause()
            assert app._current_screen == "dashboard"

    @pytest.mark.parametrize("modal_key", ["question_mark"])
    async def test_q_quits_from_help_and_export_dialog(self, mock_app_state, modal_key):
        """q quits from the help overlay. In the export dialog q is a letter in the path box."""
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            await pilot.press(modal_key)
            await pilot.pause()
            quits: list[bool] = []
            app.action_quit = lambda: quits.append(True)
            await pilot.press("q")
            await pilot.pause()
            assert quits == [True]

    async def test_page_past_the_end_moves_to_the_last_page(self, mock_app_state):
        """After the total shrinks, an empty page past the end loads the last page."""
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            mock_app_state.filters.page = 3
            mock_app_state.filters.page_size = 50
            view._update_table([], 60)
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert mock_app_state.filters.page == 1  # the last page of 60 entries at 50

    async def test_refresh_keeps_the_cursor_on_the_same_entry(
        self, mock_app_state, sample_audit_entries
    ):
        from cja_audit_log_monitor.tui.widgets import LogTable

        mock_app_state.client.get_logs.return_value = _logs_response(sample_audit_entries)
        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            view = await _show_and_load(app, pilot, "l")
            table = view.query_one("#log-table", LogTable)
            assert await _wait_for(lambda: table.row_count == len(sample_audit_entries), pilot)
            table.move_cursor(row=4)
            chosen = table.get_selected_entry()
            view.refresh_data()
            await app.workers.wait_for_complete()
            await pilot.pause()
            assert table.get_selected_entry() == chosen

    async def test_huge_stats_days_is_refused_in_the_box(self, mock_app_state):
        from textual.widgets import Input

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            await pilot.press("s")
            await pilot.pause()
            view = app._screens["stats"]
            view.query_one("#days-input", Input).value = "4000000"
            view._apply_days()
            await pilot.pause()
            assert mock_app_state.stats_days <= 3650

    async def test_org_id_shown_in_full_in_the_config_view(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(160, 40)) as pilot:
            view = await _show_and_load(app, pilot, "c")
            text = "\n".join(_plain(s) for s in view.query(Static))
            assert mock_app_state.settings.org_id in text


@pytest.mark.parametrize("size", [(80, 24), (100, 30), (140, 42)])
async def test_config_buttons_visible(mock_app_state, size):
    from textual.widgets import Button

    app = _make_app(mock_app_state)
    async with app.run_test(size=size) as pilot:
        view = await _show_and_load(app, pilot, "c")
        await pilot.pause()
        for button_id in ("#verify-button", "#reload-button"):
            button = view.query_one(button_id, Button)
            visible = app.screen.find_widget(button).visible_region
            assert visible.height > 0, f"{button_id} is off screen at {size}"


async def test_stats_period_tile_is_one_line_at_100(mock_app_state):
    app = _make_app(mock_app_state)
    async with app.run_test(size=(100, 30)) as pilot:
        view = await _show_and_load(app, pilot, "s")
        from rich.cells import cell_len

        widget = view.query_one("#stats-period", Static)
        text = _plain(widget).strip()
        assert "→" in text
        assert cell_len(text) <= widget.content_region.width


async def test_footer_fits_80_with_detail_focused(mock_app_state):
    from textual.widgets import Footer

    from cja_audit_log_monitor.tui.modals import EntryDetailPanel

    app = _make_app(mock_app_state)
    async with app.run_test(size=(80, 24)) as pilot:
        await _show_and_load(app, pilot, "l")
        await pilot.press("enter")
        panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
        assert await _wait_for(lambda: panel.display and not panel.has_class("hidden"), pilot)
        await pilot.press("tab")
        await pilot.pause()
        footer = app.query_one(Footer)
        keys = list(footer.query("FooterKey"))
        last = keys[-1]
        assert last.region.x + last.region.width <= footer.region.width
        assert "quit" in [k.description for k in keys]


async def test_detail_panel_is_wider_at_200(mock_app_state):
    from cja_audit_log_monitor.tui.modals import EntryDetailPanel

    app = _make_app(mock_app_state)
    async with app.run_test(size=(200, 60)) as pilot:
        await _show_and_load(app, pilot, "l")
        await pilot.press("enter")
        panel = app.query_one("#entry-detail-panel", EntryDetailPanel)
        assert await _wait_for(lambda: panel.display and not panel.has_class("hidden"), pilot)
        await pilot.pause()
        assert panel.region.width >= 60


class TestMonitorStatusTexts:
    """The monitor status row and toasts say what failed (G41)."""

    async def test_status_row_and_toasts_show_each_new_error(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.client import APIError

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            await _drive_poll(screen, pilot)
            mock_app_state.client.get_logs.side_effect = APIError("upstream down", 503)
            await _drive_poll(screen, pilot)
            assert "upstream down" in _status_indicator(screen)
            mock_app_state.client.get_logs.side_effect = APIError("gateway timeout", 504)
            await _drive_poll(screen, pilot)
            messages = [n.message for n in app._notifications]
            assert any("upstream down" in m for m in messages)
            assert any("gateway timeout" in m for m in messages)
            screen._stop_monitoring()

    async def test_403_marks_the_header(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.client import APIError

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            app.set_connection_status("connected")
            mock_app_state.client.get_logs.side_effect = APIError("forbidden", 403)
            await _drive_poll(screen, pilot)
            assert "● connected" not in _status_text(app)
            screen._stop_monitoring()

    async def test_alerts_panel_clears_on_restart(self, mock_app_state, monkeypatch):
        from cja_audit_log_monitor.tui.widgets import AlertSummary

        app = _make_app(mock_app_state)
        async with app.run_test(size=(140, 40)) as pilot:
            screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
            screen.query_one(AlertSummary).add_alert("r: 1 event by u")
            screen._stop_monitoring()
            await pilot.pause()
            screen._start_monitoring()
            await pilot.pause()
            assert "no alerts yet" in str(screen.query_one(AlertSummary).render())
            screen._stop_monitoring()


def test_no_private_textual_imports() -> None:
    """G53: a private Textual module could be renamed in any release."""
    import re
    from pathlib import Path

    import cja_audit_log_monitor

    root = Path(cja_audit_log_monitor.__file__).parent
    hits = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if re.search(r"textual(\.\w+)*\._\w+", path.read_text())
    ]
    assert hits == []


async def test_tui_monitor_stops_on_an_error_retrying_cannot_fix(mock_app_state, monkeypatch):
    """A 403 stops the TUI monitor, as it stops the CLI monitor (G52)."""
    from cja_audit_log_monitor.client import APIError

    app = _make_app(mock_app_state)
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        await _drive_poll(screen, pilot)
        mock_app_state.client.get_logs.side_effect = APIError("forbidden", status_code=403)
        await _drive_poll(screen, pilot)
        assert await _wait_for(lambda: not mock_app_state.monitor.is_running, pilot)
        assert "stopped" in _status_indicator(screen)
        assert any("forbidden" in n.message for n in app._notifications)
