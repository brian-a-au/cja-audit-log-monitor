#!/usr/bin/env python3
"""Capture screenshots of all TUI screens using Textual's screenshot feature with mock data."""

import asyncio
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from cja_audit.models import ActionType, AuditLogEntry, AuditLogResponse, ComponentType


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


def create_mock_client(entries: list[AuditLogEntry]):
    """Create a mock client that returns mock data."""
    mock_client = MagicMock()
    mock_client.__enter__ = MagicMock(return_value=mock_client)
    mock_client.__exit__ = MagicMock(return_value=None)

    def mock_get_all_logs(query=None, max_entries=None):
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

    return mock_client


def create_mock_settings():
    """Create mock settings."""
    from cja_audit.models import AlertRule

    mock_settings = MagicMock()
    mock_settings.client_id = "demo_client_12345"
    mock_settings.client_secret = "demo_secret"
    mock_settings.org_id = "ABC123DEF@AdobeOrg"
    mock_settings.api_base_url = "https://cja.adobe.io"
    mock_settings.ims_base_url = "https://ims-na1.adobelogin.com"
    mock_settings.default_page_size = 50
    mock_settings.default_days = 7
    mock_settings.monitor_interval = 60
    mock_settings.scopes = "openid,AdobeID"
    mock_settings.is_oauth_configured = lambda: True
    mock_settings.is_jwt_configured = lambda: False
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


def setup_mock_state(app, entries: list[AuditLogEntry]):
    """Configure the app's state with mock data directly."""
    mock_client = create_mock_client(entries)
    mock_settings = create_mock_settings()

    # Inject mock client and settings directly into the state
    app.state._settings = mock_settings
    app.state._client = mock_client
    app.state._token_manager = MagicMock()

    # Pre-populate state data so it's available immediately
    app.state.entries = entries
    app.state.total_entries = len(entries)
    app.state.is_connected = True
    app.state.connection_error = None
    app.state.last_refresh = datetime.now(UTC)

    # Monkey-patch verify_connection to return mock data
    async def mock_verify_connection():
        return {
            "connected": True,
            "authenticated": True,
            "org_id": "ABC123DEF@AdobeOrg",
            "api_url": "https://cja.adobe.io",
            "total_logs_available": len(entries),
        }

    app.state.verify_connection = mock_verify_connection


def populate_dashboard_data(app, entries: list[AuditLogEntry]):
    """Directly populate dashboard widgets with mock data."""
    from textual.widgets import Static

    from cja_audit.alerts import analyze_for_anomalies
    from cja_audit.formatters import ACTION_COLORS
    from cja_audit.stats import calculate_stats

    stats = calculate_stats(entries)
    anomalies = analyze_for_anomalies(entries)

    try:
        # Update stat cards
        app.query_one("#stat-total", Static).update(f"{stats.get('total_entries', 0):,}")

        date_range = stats.get("date_range")
        if date_range:
            app.query_one("#stat-range", Static).update(
                f"{date_range['start'][:10]} to {date_range['end'][:10]}"
            )

        top_users = stats.get("top_users", [])
        app.query_one("#stat-users", Static).update(str(len(top_users)))
        app.query_one("#stat-alerts", Static).update(str(len(anomalies)))

        # Update connection status
        app.query_one("#connection-status", Static).update(
            "[green]● Connected[/green] - ABC123DEF@AdobeOrg"
        )

        # Update action chart
        actions = stats.get("action_counts", {})
        if actions:
            max_count = max(actions.values()) if actions else 1
            chart_lines = []
            for action, count in sorted(actions.items(), key=lambda x: -x[1])[:8]:
                color = ACTION_COLORS.get(action, "white")
                bar_width = int((count / max_count) * 30)
                bar = "█" * bar_width
                chart_lines.append(f"[{color}]{action:15}[/{color}] {bar} {count:,}")
            app.query_one("#action-chart", Static).update("\n".join(chart_lines))

        # Update top users
        if top_users:
            user_lines = []
            for i, (user, count) in enumerate(top_users[:5], 1):
                user_lines.append(f"  {i}. {user}: {count:,} actions")
            app.query_one("#top-users", Static).update("\n".join(user_lines))

        # Update anomalies
        if anomalies:
            anomaly_lines = []
            for anomaly in anomalies[:5]:
                anomaly_lines.append(f"  [yellow]⚠[/yellow] {anomaly['description']}")
            app.query_one("#anomalies", Static).update("\n".join(anomaly_lines))
        else:
            app.query_one("#anomalies", Static).update("[dim]No anomalies detected[/dim]")

        # Update last update time
        app.query_one("#last-update", Static).update(
            f"[dim]Last updated: {datetime.now(UTC).strftime('%H:%M:%S')}[/dim]"
        )

        # Hide loading indicator
        app.query_one("#loading").display = False
    except Exception as e:
        print(f"Error populating dashboard: {e}")
        import traceback
        traceback.print_exc()


async def capture_screenshots():
    """Capture screenshots of all TUI screens with mock data."""
    from cja_audit.tui import CJAAuditApp

    output_dir = Path(__file__).parent.parent / "docs" / "screenshots"
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate mock data
    entries = generate_mock_entries(150)

    # Screen configurations: (key to press or None if already on screen, filename, delay)
    screens = [
        (None, "dashboard.svg", 3.0),  # Already on dashboard at start
        ("l", "log-browser.svg", 3.0),
        ("m", "monitor.svg", 2.0),
        ("s", "statistics.svg", 3.0),
        ("a", "alerts.svg", 2.0),
        ("c", "settings.svg", 2.0),
    ]

    app = CJAAuditApp()

    # Set up mock state BEFORE running the test
    setup_mock_state(app, entries)

    try:
        async with app.run_test(size=(120, 40)) as pilot:
            # Wait for app to fully mount
            await pilot.pause(delay=2.0)

            # Directly populate dashboard with data
            populate_dashboard_data(app, entries)
            await pilot.pause(delay=1.0)

            for key, filename, delay in screens:
                if key:
                    # Navigate to screen
                    await pilot.press(key)
                # Allow time for screen to fully render
                await pilot.pause(delay=delay)

                # Save screenshot
                filepath = output_dir / filename
                app.save_screenshot(str(filepath))
                print(f"Captured: {filepath}")

    except Exception as e:
        print(f"Warning during capture: {e}")
        import traceback
        traceback.print_exc()

    print(f"\nAll screenshots saved to: {output_dir}")


if __name__ == "__main__":
    asyncio.run(capture_screenshots())
