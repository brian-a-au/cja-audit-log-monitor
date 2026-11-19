#!/usr/bin/env python3
"""Capture SVG screenshots of every TUI view by driving the real app with mock data.

The app runs headless via Textual's ``run_test``; only the API client is mocked.
Views load their data through their normal workers, so the screenshots show what
a user actually sees.

Usage:
    uv run python scripts/capture_screenshots.py [--out DIR] [--size 140x42]
"""
# cspell:ignore tcss TCSS Signups

import argparse
import asyncio
import os
import random
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

from cja_audit_log_monitor.models import ActionType, AuditLogEntry, AuditLogResponse, ComponentType

# ---------------------------------------------------------------------------
# Mock data generators
# ---------------------------------------------------------------------------


def generate_mock_entries(count: int = 150) -> list[AuditLogEntry]:
    """Generate realistic mock audit log entries."""
    users = [
        "alice.smith@example.com",
        "bob.jones@example.com",
        "carol.williams@example.com",
        "david.brown@example.com",
        "eva.martinez@example.com",
        "frank.wilson@example.com",
        "grace.taylor@example.com",
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
            "Q4 Sales Report",
            "Marketing Overview",
            "Customer Journey Analysis",
            "Revenue Dashboard",
            "User Engagement Report",
            "Conversion Funnel",
        ],
        ComponentType.FILTER: [
            "Returning Visitors",
            "Mobile Users",
            "High Value Customers",
            "New Signups",
            "Enterprise Segment",
        ],
        ComponentType.CALCULATED_METRIC: [
            "Conversion Rate",
            "Customer LTV",
            "Bounce Rate",
            "Session Duration",
        ],
        ComponentType.DATA_VIEW: [
            "Production View",
            "Staging View",
            "Analytics Sandbox",
        ],
        ComponentType.ANNOTATION: [
            "Black Friday Sale",
            "Site Outage",
            "New Feature Launch",
        ],
        ComponentType.AUDIENCE: [
            "Engaged Users",
            "At-Risk Customers",
            "VIP Segment",
        ],
    }

    entries = []
    # Use fixed seed for reproducible screenshots
    random.seed(42)
    # Recent data, so it falls inside the dashboard's "last 7 days" window.
    base_time = datetime.now(UTC).replace(minute=30, second=0, microsecond=0) - timedelta(hours=1)

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
            per_user=True,
        ),
        AlertRule(
            name="bulk_export",
            description="Multiple export operations",
            enabled=True,
            actions=[ActionType.EXPORT],
            threshold_count=3,
            threshold_window_minutes=30,
            per_user=True,
        ),
        AlertRule(
            name="sensitive_component_delete",
            description="Deletion of sensitive components",
            enabled=True,
            actions=[ActionType.DELETE],
            components=[ComponentType.DATA_VIEW, ComponentType.CONNECTION],
            threshold_count=1,
            threshold_window_minutes=1,
        ),
        AlertRule(
            name="bulk_share",
            description="Bulk sharing activity",
            enabled=True,
            actions=[ActionType.SHARE],
            threshold_count=10,
            threshold_window_minutes=60,
            per_user=True,
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

    def mock_get_logs_sample(query=None, max_entries=1000):
        del query  # see mock_get_all_logs
        return entries[:max_entries], len(entries)

    mock_client.get_logs = mock_get_logs
    mock_client.get_all_logs = mock_get_all_logs
    mock_client.get_logs_sample = mock_get_logs_sample
    mock_client.verify_connection = MagicMock(
        return_value={
            "connected": True,
            "authenticated": True,
            "org_id": "ABC123DEF@AdobeOrg",
            "api_url": "https://cja.adobe.io",
            "total_logs_available": len(entries),
        }
    )
    mock_client.close = MagicMock()

    app.state._settings = mock_settings
    app.state._client = mock_client
    app.state._token_manager = MagicMock()
    # Never show the real config location in images.
    app.state._config_path = Path("~/.cja-audit-log-monitor/config.yaml")

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


# ---------------------------------------------------------------------------
# Main capture routine
# ---------------------------------------------------------------------------


VIEWS = [
    ("d", "dashboard", "dashboard"),
    ("l", "logs", "log-browser"),
    ("m", "monitor", "monitor"),
    ("s", "stats", "statistics"),
    ("a", "alerts", "alerts"),
    ("c", "settings", "settings"),
]


async def capture_screenshots(output_dir: Path, size: tuple[int, int]) -> None:
    """Capture one SVG per view into ``output_dir``."""
    from cja_audit_log_monitor.tui import CJAAuditApp

    output_dir.mkdir(parents=True, exist_ok=True)
    entries = generate_mock_entries(150)

    app = CJAAuditApp()
    setup_mock_state(app, entries)

    async with app.run_test(size=size) as pilot:
        await pilot.pause(delay=1.0)
        for key, view_name, file_stem in VIEWS:
            await pilot.press(key)
            await pilot.pause(delay=1.0)
            if view_name == "monitor":
                # Start a live session so the stream shows entries.
                app._screens["monitor"]._start_monitoring()
                await pilot.pause(delay=1.5)
            filepath = output_dir / f"{file_stem}.svg"
            app.save_screenshot(str(filepath))
            print(f"  Captured: {filepath}")
        app._screens["monitor"]._stop_monitoring()


def main() -> None:
    """Parse arguments and capture screenshots."""
    # Screenshots show times in UTC, whatever the local zone of the machine is.
    os.environ["TZ"] = "UTC"
    time.tzset()
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--out",
        type=Path,
        default=Path(__file__).parent.parent / "docs" / "screenshots",
        help="Output directory (default: docs/screenshots)",
    )
    parser.add_argument("--size", default="140x42", help="Terminal size COLSxROWS")
    args = parser.parse_args()
    cols, rows = (int(n) for n in args.size.lower().split("x"))
    asyncio.run(capture_screenshots(args.out, (cols, rows)))


if __name__ == "__main__":
    main()
