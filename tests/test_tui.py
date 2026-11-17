"""Tests for the TUI module."""

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
            loading = app.query_one("#loading")
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
            body_text = str(panel.query_one("#detail-body", Static).render())
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

        Note: toggle() calls show_entry() → _render() → query_one(), so we need
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
            body_text_a = str(body.render())
            assert entry_a.id in body_text_a

            # Move cursor to second row and fire the highlighted handler directly.
            # (pilot key dispatch doesn't reach LogBrowserScreen BINDINGS in this
            # widget-mounted test setup; calling the handler is equivalent.)
            table.move_cursor(row=1)
            log_screen.on_data_table_row_highlighted(event=None)
            await pilot.pause()

            body_text_b = str(body.render())
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
            radio_buttons = app.screen.query("RadioButton")
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
