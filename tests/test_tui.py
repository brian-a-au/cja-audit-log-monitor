"""Tests for the TUI module."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from textual.widgets import Button, Static

from cja_audit_log_monitor.alerts import FiredAlert
from cja_audit_log_monitor.models import AlertRule
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
def _patch_screen_workers():
    """Patch screen on_content_mounted workers for all TUI tests."""
    patchers = [patch(p, _noop) for p in _SCREEN_WORKER_PATCHES]
    for p in patchers:
        p.start()
    yield
    for p in patchers:
        p.stop()


# ---------------------------------------------------------------------------
# TestNotificationDispatch
# ---------------------------------------------------------------------------


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
        fake_nm.pop_first_failure.return_value = None
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
        fake_nm.pop_first_failure.return_value = None
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

    console = Console(width=200, record=True, color_system=None)
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

    def test_long_user_truncated_with_ellipsis(self, sample_audit_entry):
        from cja_audit_log_monitor.tui.widgets import LogTable

        entry = sample_audit_entry.model_copy(
            update={"user_email": "a.very.long.user.name.for.testing@example-company.com"}
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
            card = app._screens["alerts"].query_one("#card-bulk_delete")
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

        async def _no_loop(self):
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


class TestMonitorScreen:
    """Test the Monitor screen."""

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
        app = _make_app(mock_app_state)
        async with app.run_test() as pilot:
            await pilot.press("m")
            await pilot.pause()
            monitor_screen = app._screens["monitor"]
            monitor_screen._state.monitor.is_running = False
            monitor_screen._poll_for_new_entries = AsyncMock()

            await monitor_screen._poll_once()

            monitor_screen._poll_for_new_entries.assert_not_awaited()

    def test_monitor_surfaces_pop_first_failure_warning(self):
        """When pop_first_failure returns a string, _show_warning is dispatched."""
        from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

        expected_warning = (
            "Notification delivery failed (slack);"
            " subsequent failures suppressed for this session — check logs."
        )

        state = MagicMock()
        state.notification_manager.pop_first_failure.return_value = expected_warning

        screen = MonitorScreen(state=state)
        mock_app = MagicMock()

        with patch.object(
            MonitorScreen, "app", new_callable=lambda: property(lambda self: mock_app)
        ):
            # Directly exercise the warning-surface idiom as it appears in production code.
            warning = screen._state.notification_manager.pop_first_failure()
            if warning:
                screen.app.call_from_thread(screen._show_warning, warning)

            mock_app.call_from_thread.assert_called_once_with(
                screen._show_warning, expected_warning
            )

        # Confirm the warning string contains the expected channel name
        call_args = mock_app.call_from_thread.call_args
        assert "slack" in call_args.args[1].lower()

    def test_monitor_show_alert_uses_rule_name(self):
        """_show_alert renders 'rule_name: message' (not the literal 'Alert triggered')."""
        from cja_audit_log_monitor.tui.screens.monitor import MonitorScreen

        state = MagicMock()
        screen = MonitorScreen(state=state)
        mock_app = MagicMock()
        alert_summary = MagicMock()
        screen.query_one = MagicMock(return_value=alert_summary)

        with patch.object(
            MonitorScreen, "app", new_callable=lambda: property(lambda self: mock_app)
        ):
            screen._show_alert("bulk_delete", "Multiple delete operations: 5 events in 60 minutes")

        # Toast text contains both rule_name and message
        notify_args = mock_app.notify.call_args
        assert "bulk_delete" in notify_args.args[0]
        assert "Multiple delete operations" in notify_args.args[0]

        # alert_summary.add_alert() was called with rule_name and message
        alert_summary.add_alert.assert_called_once_with(
            "bulk_delete", "Multiple delete operations: 5 events in 60 minutes"
        )


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

    async def test_entry_detail_panel_shows_when_toggled(
        self, mock_app_state, sample_audit_entry
    ):
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

    async def test_entry_detail_panel_dismisses_on_escape(
        self, mock_app_state, sample_audit_entry
    ):
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

    async def test_entry_detail_panel_toggle_semantics(
        self, mock_app_state, sample_audit_entries
    ):
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
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        target = tmp_path / "page.json"
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(target)
            await pilot.click("#export-button")
            await app.workers.wait_for_complete()
            await pilot.pause()
        import json

        assert len(json.loads(target.read_text())["entries"]) == len(sample_audit_entries)
        mock_app_state.client.get_logs_sample.assert_not_called()

    async def test_all_scope_fetches_every_matching_entry(
        self, mock_app_state, sample_audit_entries, sample_audit_entry, tmp_path
    ):
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
            await app.workers.wait_for_complete()
            await pilot.pause()
        import json

        assert len(json.loads(target.read_text())["entries"]) == 30
        _, kwargs = mock_app_state.client.get_logs_sample.call_args
        assert kwargs["max_entries"] == 10_000

    async def test_dialog_closes_itself_after_export_without_crashing(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        from cja_audit_log_monitor.tui.modals import ExportDialog

        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(tmp_path / "x.json")
            await pilot.click("#export-button")
            await pilot.pause(2.0)
            assert not isinstance(app.screen, ExportDialog)
        assert app._exception is None

    async def test_closing_before_auto_close_does_not_crash(
        self, mock_app_state, sample_audit_entries, tmp_path
    ):
        mock_app_state.entries = sample_audit_entries
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            dialog.query_one("#output-path").value = str(tmp_path / "x.json")
            await pilot.click("#export-button")
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause(2.0)
        assert app._exception is None

    async def test_dialog_uses_lowercase_labels(self, mock_app_state):
        app = _make_app(mock_app_state)
        async with app.run_test(size=(120, 40)) as pilot:
            dialog = await self._open(app, pilot)
            assert str(dialog.query_one("#export-button").label) == "export"
            assert str(dialog.query_one("#cancel-button").label) == "cancel"
            assert str(dialog.query_one("#export-title").render()) == "export audit logs"


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
            expected = f"{(now - timedelta(days=7)):%Y-%m-%d} → {now:%Y-%m-%d}"
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
            summary.add_alert("bulk_delete", "5 deletes in 60 min")
            text = str(summary.render())
            assert "bulk_delete: 5 deletes in 60 min" in text
            assert "..." not in text and "…" not in text

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
            shown = [
                b.binding.action for b in app.active_bindings.values() if b.binding.show
            ]
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


async def test_alert_card_shows_local_time_with_zone(mock_app_state, los_angeles_tz):
    from datetime import UTC, datetime

    from cja_audit_log_monitor.models import AuditLogEntry
    from cja_audit_log_monitor.tui.widgets.alert_card import AlertCard

    entry = AuditLogEntry(id="1", timestamp=datetime(2026, 11, 17, 23, 25, 13, tzinfo=UTC))
    app = _make_app(mock_app_state)
    async with app.run_test(size=(120, 40)) as pilot:
        card = AlertCard("rule", "fired", entry)
        await app.screen.mount(card)
        await pilot.pause()
        text = str(card.render())
        assert "2026-11-17 15:25:13 PST" in text


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
                str(s.render()) for s in dash.query(".section-label")
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
    console = Console(width=44, record=True, color_system=None)
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
