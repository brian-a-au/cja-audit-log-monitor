#!/usr/bin/env python3
"""Capture screenshots of all TUI screens using Textual's screenshot feature with mock data.

Root-cause fix (2025-05-02): All screen classes extend textual.screen.Screen.
When mounted as child widgets inside a Container (#main-content) rather than via
push_screen(), Textual gives the Screen a zero-size region even though its .size
property reports the full terminal dimensions.  Child widgets inherit that zero
region and render as invisible in SVG screenshots.

Fix: wrap compose_content() output in a ScreenContentWidget (Widget subclass)
instead of mounting the Screen directly.  Workers / on_content_mounted are NOT
used in the screenshot script; widgets are populated synchronously via helper
functions after mounting so there is no threading or async complication.
"""
# cspell:ignore tcss TCSS Signups

import asyncio
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from textual.app import ComposeResult
from textual.containers import Container
from textual.widget import Widget
from textual.widgets import Label, LoadingIndicator, Static

from cja_audit_log_monitor.models import ActionType, AuditLogEntry, AuditLogResponse, ComponentType

# ---------------------------------------------------------------------------
# ScreenContentWidget — the key fix
# ---------------------------------------------------------------------------


class ScreenContentWidget(Widget):
    """Thin wrapper that renders a Screen's compose_content() as a properly-sized Widget.

    When a Screen is mounted as a child widget inside a Container, Textual assigns it
    a zero-size region.  Wrapping the same compose_content() output in a plain Widget
    (which does NOT have Screen's special coordinate semantics) means the children get
    laid out relative to the parent Container and receive real dimensions.
    """

    DEFAULT_CSS = """
    ScreenContentWidget {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, screen_instance, **kwargs):
        super().__init__(**kwargs)
        self._screen = screen_instance

    def compose(self) -> ComposeResult:
        yield from self._screen.compose_content()


# ---------------------------------------------------------------------------
# Mock data generators
# ---------------------------------------------------------------------------


def generate_mock_entries(count: int = 150) -> list[AuditLogEntry]:
    """Generate realistic mock audit log entries."""
    users = [
        "alice.smith@company.com",
        "bob.jones@company.com",
        "carol.williams@company.com",
        "david.brown@company.com",
        "eva.martinez@company.com",
        "frank.wilson@company.com",
        "grace.taylor@company.com",
    ]

    actions = [
        ActionType.CREATE,
        ActionType.EDIT,
        ActionType.DELETE,
        ActionType.SHARE,
        ActionType.EXPORT,
        ActionType.APPROVE,
    ]
    action_weights = [30, 40, 10, 8, 7, 5]

    components = [
        (ComponentType.PROJECT, "Dashboard"),
        (ComponentType.FILTER, "Segment"),
        (ComponentType.CALCULATED_METRIC, "Metric"),
        (ComponentType.DATA_VIEW, "Data View"),
        (ComponentType.ANNOTATION, "Annotation"),
        (ComponentType.AUDIENCE, "Audience"),
    ]

    component_names = {
        ComponentType.PROJECT: [
            "Q4 Sales Report", "Marketing Overview", "Customer Journey Analysis",
            "Revenue Dashboard", "User Engagement Report", "Conversion Funnel",
        ],
        ComponentType.FILTER: [
            "Returning Visitors", "Mobile Users", "High Value Customers",
            "New Signups", "Enterprise Segment",
        ],
        ComponentType.CALCULATED_METRIC: [
            "Conversion Rate", "Customer LTV", "Bounce Rate", "Session Duration",
        ],
        ComponentType.DATA_VIEW: [
            "Production View", "Staging View", "Analytics Sandbox",
        ],
        ComponentType.ANNOTATION: [
            "Black Friday Sale", "Site Outage", "New Feature Launch",
        ],
        ComponentType.AUDIENCE: [
            "Engaged Users", "At-Risk Customers", "VIP Segment",
        ],
    }

    entries = []
    # Use fixed seed for reproducible screenshots
    random.seed(42)
    base_time = datetime(2025, 1, 20, 15, 30, 0, tzinfo=UTC)

    for i in range(count):
        timestamp = base_time - timedelta(
            days=random.randint(0, 6),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )

        user = random.choice(users)
        action = random.choices(actions, weights=action_weights)[0]
        comp_type, comp_prefix = random.choice(components)
        comp_name = random.choice(component_names[comp_type])

        action_verb = {
            ActionType.CREATE: "Created",
            ActionType.EDIT: "Modified",
            ActionType.DELETE: "Deleted",
            ActionType.SHARE: "Shared",
            ActionType.EXPORT: "Exported",
            ActionType.APPROVE: "Approved",
        }.get(action, str(action.value))

        entries.append(
            AuditLogEntry(
                id=f"entry-{i:05d}",
                timestamp=timestamp,
                user_id=f"user-{users.index(user):03d}",
                user_email=user,
                action=action.value,
                component_type=comp_type.value,
                component_id=f"comp-{i:05d}",
                component_name=comp_name,
                description=f"{action_verb} {comp_prefix.lower()}: {comp_name}",
                org_id="ABC123DEF@AdobeOrg",
                ip_address=f"192.168.{random.randint(1, 255)}.{random.randint(1, 255)}",
            )
        )

    entries.sort(key=lambda e: e.timestamp or base_time, reverse=True)
    return entries


def create_mock_settings():
    """Create mock settings."""
    from cja_audit_log_monitor.models import AlertRule

    mock_settings = MagicMock()
    mock_settings.client_id = "demo_client_12345"
    mock_settings.secret = "demo_secret"
    mock_settings.org_id = "ABC123DEF@AdobeOrg"
    mock_settings.api_base_url = "https://cja.adobe.io"
    mock_settings.ims_base_url = "https://ims-na1.adobelogin.com"
    mock_settings.default_page_size = 50
    mock_settings.default_days = 7
    mock_settings.monitor_interval = 60
    mock_settings.scopes = "openid,AdobeID"
    mock_settings.is_oauth_configured = lambda: True
    mock_settings.alert_rules = [
        AlertRule(
            name="bulk_delete",
            description="Alert on multiple delete operations",
            enabled=True,
            actions=[ActionType.DELETE],
            threshold_count=5,
            threshold_window_minutes=60,
        ),
        AlertRule(
            name="sensitive_export",
            description="Alert on data exports",
            enabled=True,
            actions=[ActionType.EXPORT],
            threshold_count=3,
            threshold_window_minutes=30,
        ),
        AlertRule(
            name="off_hours_activity",
            description="Activity outside business hours",
            enabled=True,
            threshold_count=10,
            threshold_window_minutes=60,
        ),
    ]
    return mock_settings


def setup_mock_state(app, entries: list[AuditLogEntry]) -> None:
    """Configure the app's state with mock data directly."""
    mock_settings = create_mock_settings()

    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    def mock_get_all_logs(query=None, max_entries=None):
        del query  # mock signature matches real API; query is intentionally unused
        if max_entries:
            return entries[:max_entries]
        return entries

    def mock_get_logs(query=None):
        page = query.page if query and query.page else 0
        page_size = query.page_size if query and query.page_size else 50
        start = page * page_size
        end = start + page_size
        page_entries = entries[start:end]
        return AuditLogResponse(
            content=page_entries,
            total_elements=len(entries),
            total_pages=(len(entries) + page_size - 1) // page_size,
            number_of_elements=len(page_entries),
            first=page == 0,
            last=end >= len(entries),
            number=page,
            size=page_size,
        )

    mock_client.get_logs = mock_get_logs
    mock_client.get_all_logs = mock_get_all_logs
    mock_client.verify_connection = MagicMock(return_value={
        "connected": True,
        "authenticated": True,
        "org_id": "ABC123DEF@AdobeOrg",
        "api_url": "https://cja.adobe.io",
        "total_logs_available": len(entries),
    })
    mock_client.close = MagicMock()

    app.state._settings = mock_settings
    app.state._client = mock_client
    app.state._token_manager = MagicMock()

    # Pre-populate state data
    app.state.entries = entries
    app.state.total_entries = len(entries)
    app.state.is_connected = True
    app.state.connection_error = None
    app.state.last_refresh = datetime.now(UTC)

    # Provide a SYNC verify_connection (dashboard calls it synchronously from a thread)
    def sync_verify_connection():
        return {
            "connected": True,
            "authenticated": True,
            "org_id": "ABC123DEF@AdobeOrg",
            "api_url": "https://cja.adobe.io",
            "total_logs_available": len(entries),
        }

    app.state.verify_connection = sync_verify_connection

    # Provide a SYNC fetch_logs_page so log-browser can populate without real API
    def sync_fetch_logs_page():
        return entries[:50], len(entries)

    app.state.fetch_logs_page = sync_fetch_logs_page


def install_widget_show_screen(app) -> None:
    """Monkey-patch app._show_screen to use ScreenContentWidget instead of raw Screen.

    This is the core fix: by mounting a Widget wrapper (not a Screen) the layout
    engine assigns real dimensions to the children.  Workers / on_content_mounted
    are intentionally NOT called — widgets are populated synchronously via the
    populate_*_data helpers below.
    """

    async def patched_show_screen(screen_name: str) -> None:
        content = app.query_one("#main-content", Container)
        await content.remove_children()

        nav_labels = {
            "nav-dashboard": "dashboard",
            "nav-logs": "logs",
            "nav-monitor": "monitor",
            "nav-stats": "stats",
            "nav-alerts": "alerts",
            "nav-settings": "config",
        }
        for item in app.query("#sidebar .nav-item"):
            label = nav_labels.get(item.id, "")
            is_active = item.id == f"nav-{screen_name}"
            item.set_class(is_active, "active")
            prefix = "▸ " if is_active else "  "
            item.update(f"{prefix}{label}")

        screen = app._screens.get(screen_name)
        if screen:
            wrapper = ScreenContentWidget(screen)
            await content.mount(wrapper)

        app._current_screen = screen_name

    app._show_screen = patched_show_screen


# ---------------------------------------------------------------------------
# Per-screen populate helpers (synchronous, safe to call in the event loop)
# ---------------------------------------------------------------------------


def _hide_loading(app) -> None:
    """Hide the LoadingIndicator in the current screen if present."""
    try:
        app.query_one("#loading", LoadingIndicator).display = False
    except Exception:
        pass


def populate_dashboard_data(app, entries: list[AuditLogEntry]) -> None:
    """Directly populate dashboard widgets with mock data."""
    from cja_audit_log_monitor.alerts import analyze_for_anomalies
    from cja_audit_log_monitor.formatters import ACTION_COLORS, TCSS_TOKEN_HEX, resolve_tcss_markup
    from cja_audit_log_monitor.stats import calculate_stats

    stats = calculate_stats(entries)
    anomalies = analyze_for_anomalies(entries)

    try:
        # Connection status
        app.query_one("#connection-status", Static).update(
            resolve_tcss_markup("[$success]●[/$success] connected · ABC123DEF@AdobeOrg")
        )

        # Stat cards
        app.query_one("#stat-total", Static).update(f"{stats.get('total_entries', 0):,}")

        date_range = stats.get("date_range")
        if date_range:
            app.query_one("#stat-range", Static).update(
                f"{date_range['start'][:10]} to {date_range['end'][:10]}"
            )
        else:
            app.query_one("#stat-range", Static).update("N/A")

        top_users = stats.get("top_users", [])
        app.query_one("#stat-users", Static).update(str(len(top_users)))
        app.query_one("#stat-alerts", Static).update(str(len(anomalies)))

        # Action chart
        actions = stats.get("action_counts", {})
        if actions:
            max_count = max(actions.values())
            chart_lines = []
            for action, count in sorted(actions.items(), key=lambda x: -x[1])[:8]:
                token = ACTION_COLORS.get(action, "$text-muted")
                color = TCSS_TOKEN_HEX.get(token, token)
                bar_width = int((count / max_count) * 30)
                bar = "█" * bar_width
                chart_lines.append(f"[{color}]{action:15}[/{color}] {bar} {count:,}")
            app.query_one("#action-chart", Static).update("\n".join(chart_lines))
        else:
            app.query_one("#action-chart", Static).update("[dim]No data[/dim]")

        # Top users
        if top_users:
            user_lines = [f"  {i}. {u}: {c:,} actions" for i, (u, c) in enumerate(top_users[:5], 1)]
            app.query_one("#top-users", Static).update("\n".join(user_lines))
        else:
            app.query_one("#top-users", Static).update("[dim]No data[/dim]")

        # Anomalies
        if anomalies:
            anomaly_lines = []
            for anomaly in anomalies[:5]:
                anomaly_lines.append(
                    resolve_tcss_markup(f"  [$warning]⚠[/$warning] {anomaly['description']}")
                )
            app.query_one("#anomalies", Static).update("\n".join(anomaly_lines))
        else:
            app.query_one("#anomalies", Static).update("[dim]No anomalies detected[/dim]")

        # Last update time
        app.query_one("#last-update", Static).update(
            f"[dim]Last updated: {datetime.now().strftime('%H:%M:%S')}[/dim]"
        )

        _hide_loading(app)
    except Exception as e:
        print(f"  Warning - populate_dashboard_data: {e}")
        import traceback
        traceback.print_exc()


def populate_log_browser_data(app, entries: list[AuditLogEntry]) -> None:
    """Populate the log browser with mock entries."""
    from cja_audit_log_monitor.tui.widgets import LogTable

    try:
        table = app.query_one("#log-table", LogTable)
        table.load_entries(entries[:50])

        total = len(entries)
        page_size = 50
        total_pages = max(1, (total + page_size - 1) // page_size)

        app.query_one("#page-info", Label).update(f"Page 1 of {total_pages}")
        app.query_one("#entry-count", Static).update(f"Total: {total:,} entries")

        _hide_loading(app)
    except Exception as e:
        print(f"  Warning - populate_log_browser_data: {e}")
        import traceback
        traceback.print_exc()


def populate_monitor_data(app, entries: list[AuditLogEntry]) -> None:
    """Populate the monitor screen with some initial entries to show the log table."""
    from cja_audit_log_monitor.formatters import resolve_tcss_markup
    from cja_audit_log_monitor.tui.widgets import LogTable

    try:
        # Show stopped state (the default) but populate the log table with recent entries
        table = app.query_one("#monitor-log", LogTable)
        for entry in entries[:20]:
            table.append_entry(entry)

        app.query_one("#status-indicator", Static).update(
            resolve_tcss_markup("[$danger]● stopped[/$danger]")
        )
        app.query_one("#stats-info", Static).update(
            "Last check: 15:30:00 | New entries: 0 | Alerts: 0"
        )

        _hide_loading(app)
    except Exception as e:
        print(f"  Warning - populate_monitor_data: {e}")
        import traceback
        traceback.print_exc()


def populate_stats_data(app, entries: list[AuditLogEntry]) -> None:
    """Populate the stats screen with computed statistics."""
    from cja_audit_log_monitor.stats import (
        calculate_stats,
        get_daily_distribution,
        get_hourly_distribution,
        get_user_activity,
    )
    from cja_audit_log_monitor.tui.widgets import ActionBarChart, HourlyChart, StatsPanel

    try:
        stats = calculate_stats(entries)
        hourly = get_hourly_distribution(entries)
        daily = get_daily_distribution(entries)
        users = get_user_activity(entries)

        # Summary panel
        app.query_one("#stats-summary", StatsPanel).update_stats(stats)

        # Action distribution chart
        app.query_one("#action-chart", ActionBarChart).update_data(stats.get("action_counts", {}))

        # Hourly chart
        app.query_one("#hourly-chart", HourlyChart).update_data(hourly)

        # Daily chart
        if daily:
            max_daily = max(daily.values()) if daily else 1
            daily_lines = []
            for date, count in sorted(daily.items())[-14:]:
                bar_width = int((count / max_daily) * 30) if max_daily > 0 else 0
                bar = "█" * bar_width
                daily_lines.append(f"  {date} │ {bar} {count}")
            app.query_one("#daily-chart", Static).update("\n".join(daily_lines))
        else:
            app.query_one("#daily-chart", Static).update("[dim]No data[/dim]")

        # User ranking
        if users:
            user_lines = [
                f"  {i:2}. {u[:40]:40} {c:,} actions"
                for i, (u, c) in enumerate(users[:10], 1)
            ]
            app.query_one("#user-ranking", Static).update("\n".join(user_lines))
        else:
            app.query_one("#user-ranking", Static).update("[dim]No data[/dim]")

        _hide_loading(app)
    except Exception as e:
        print(f"  Warning - populate_stats_data: {e}")
        import traceback
        traceback.print_exc()


def populate_alerts_data(app) -> None:
    """Populate the alerts screen — rule cards are already composed; just hide loading."""
    try:
        # Rule cards are created in compose_content from state.alert_engine.rules,
        # which is seeded with mock alert_rules.  Just hide loading.
        _hide_loading(app)

        # Show a placeholder test-results message
        try:
            app.query_one("#test-results", Static).update(
                "[dim]Press 'Test Rules' to run rules against recent data[/dim]"
            )
        except Exception:
            pass
    except Exception as e:
        print(f"  Warning - populate_alerts_data: {e}")


def populate_settings_data(app) -> None:
    """Populate the settings screen — static content is composed; update connection status."""
    from cja_audit_log_monitor.formatters import resolve_tcss_markup

    try:
        app.query_one("#connection-status", Static).update(
            resolve_tcss_markup(
                "[$success]●[/$success] connected\n"
                "  organization: ABC123DEF@AdobeOrg\n"
                "  api url: https://cja.adobe.io\n"
                "  total logs available: 150"
            )
        )
        _hide_loading(app)
    except Exception as e:
        print(f"  Warning - populate_settings_data: {e}")
        import traceback
        traceback.print_exc()


# ---------------------------------------------------------------------------
# Main capture routine
# ---------------------------------------------------------------------------


async def capture_screenshots():
    """Capture screenshots of all TUI screens with mock data."""
    from cja_audit_log_monitor.tui import CJAAuditApp

    output_dir = Path(__file__).parent.parent / "docs" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    entries = generate_mock_entries(150)

    app = CJAAuditApp()

    # Inject mock state BEFORE running the app
    setup_mock_state(app, entries)

    # Install the patched _show_screen that uses ScreenContentWidget
    install_widget_show_screen(app)

    try:
        async with app.run_test(size=(120, 40)) as pilot:
            # Wait for app to fully mount and initial screen to compose
            await pilot.pause(delay=1.5)

            # --- Dashboard ---
            print("Populating dashboard...")
            populate_dashboard_data(app, entries)
            await pilot.pause(delay=0.5)
            filepath = output_dir / "dashboard.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")

            # --- Log Browser ---
            print("Navigating to log browser...")
            await pilot.press("l")
            await pilot.pause(delay=1.0)
            populate_log_browser_data(app, entries)
            await pilot.pause(delay=0.5)
            filepath = output_dir / "log-browser.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")

            # --- Monitor ---
            print("Navigating to monitor...")
            await pilot.press("m")
            await pilot.pause(delay=1.0)
            populate_monitor_data(app, entries)
            await pilot.pause(delay=0.5)
            filepath = output_dir / "monitor.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")

            # --- Statistics ---
            print("Navigating to statistics...")
            await pilot.press("s")
            await pilot.pause(delay=1.0)
            populate_stats_data(app, entries)
            await pilot.pause(delay=0.5)
            filepath = output_dir / "statistics.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")

            # --- Alerts ---
            print("Navigating to alerts...")
            await pilot.press("a")
            await pilot.pause(delay=1.0)
            populate_alerts_data(app)
            await pilot.pause(delay=0.5)
            filepath = output_dir / "alerts.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")

            # --- Settings ---
            print("Navigating to settings...")
            await pilot.press("c")
            await pilot.pause(delay=1.0)
            populate_settings_data(app)
            await pilot.pause(delay=0.5)
            filepath = output_dir / "settings.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")

    except Exception as e:
        print(f"Warning during capture: {e}")
        import traceback
        traceback.print_exc()

    print(f"\nAll screenshots saved to: {output_dir}")


if __name__ == "__main__":
    asyncio.run(capture_screenshots())
