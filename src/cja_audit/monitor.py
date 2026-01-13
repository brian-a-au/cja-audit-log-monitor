"""Real-time monitoring for audit logs."""

import logging
import signal
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from rich.console import Console
from rich.live import Live
from rich.spinner import Spinner
from rich.text import Text

from .alerts import AlertEngine
from .client import AuditLogsClient
from .formatters import format_single_entry, get_action_color
from .models import AuditLogEntry, AuditLogQuery
from .utils import get_user_identifier

logger = logging.getLogger(__name__)


class AuditLogMonitor:
    """Real-time monitor for CJA audit logs."""

    def __init__(
        self,
        client: AuditLogsClient,
        console: Console | None = None,
        interval: int = 60,
        alert_engine: AlertEngine | None = None,
    ) -> None:
        """Initialize the monitor.

        Args:
            client: Audit logs API client.
            console: Rich console for output.
            interval: Polling interval in seconds.
            alert_engine: Optional alert engine for suspicious activity detection.
        """
        self.client = client
        self.console = console or Console()
        self.interval = interval
        self.alert_engine = alert_engine
        self._running = False
        self._last_seen_id: str | None = None
        self._last_seen_timestamp: datetime | None = None
        self._on_new_entry: Callable[[AuditLogEntry], None] | None = None

    def set_callback(self, callback: Callable[[AuditLogEntry], None]) -> None:
        """Set callback for new entries.

        Args:
            callback: Function to call with each new entry.
        """
        self._on_new_entry = callback

    def _get_new_entries(self) -> list[AuditLogEntry]:
        """Fetch new audit log entries since last check."""
        query = AuditLogQuery(page_size=50)

        # If we have a last seen timestamp, use it as start date
        if self._last_seen_timestamp:
            # Add a small buffer to avoid missing entries
            query.start_date = self._last_seen_timestamp - timedelta(seconds=1)

        try:
            response = self.client.get_logs(query)
            entries = response.content

            if not entries:
                return []

            # Filter out already seen entries
            new_entries = []
            for entry in entries:
                if self._last_seen_id and entry.id == self._last_seen_id:
                    break
                if (
                    self._last_seen_timestamp
                    and entry.timestamp
                    and entry.timestamp <= self._last_seen_timestamp
                ):
                    continue
                new_entries.append(entry)

            # Update last seen markers
            if entries:
                self._last_seen_id = entries[0].id
                if entries[0].timestamp:
                    self._last_seen_timestamp = entries[0].timestamp

            # Return in chronological order
            return list(reversed(new_entries))

        except Exception as e:
            logger.error("Error fetching audit logs: %s", e)
            return []

    def _handle_entry(self, entry: AuditLogEntry) -> None:
        """Handle a new audit log entry."""
        # Check alerts
        if self.alert_engine:
            alerts = self.alert_engine.check_entry(entry)
            for alert in alerts:
                self.console.print(alert)

        # Display entry
        self._display_entry(entry)

        # Call custom callback
        if self._on_new_entry:
            self._on_new_entry(entry)

    def _display_entry(self, entry: AuditLogEntry) -> None:
        """Display a new audit log entry."""
        timestamp = entry.timestamp.strftime("%H:%M:%S") if entry.timestamp else "-"
        action_color = get_action_color(entry.action or "")

        text = Text()
        text.append(f"[{timestamp}] ", style="dim")
        text.append(f"{entry.action or '-'}", style=action_color)
        text.append(" | ")
        text.append(f"{get_user_identifier(entry, default='-')}", style="cyan")
        text.append(" | ")
        text.append(f"{entry.component_type or '-'}", style="yellow")
        text.append(" | ")
        text.append(f"{entry.component_name or entry.component_id or '-'}")

        self.console.print(text)

    def _signal_handler(self, signum: int, frame: object) -> None:
        """Handle interrupt signal."""
        self._running = False
        self.console.print("\n[yellow]Stopping monitor...[/yellow]")

    def start(self, duration: int | None = None) -> None:
        """Start monitoring for new audit log entries.

        Args:
            duration: Optional duration in seconds. None for indefinite.
        """
        self._running = True

        # Register signal handlers
        original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self.console.print(
                f"[green]Starting audit log monitor[/green] "
                f"(polling every {self.interval}s, Ctrl+C to stop)"
            )
            self.console.print()

            # Initial fetch to set baseline
            initial = self._get_new_entries()
            if initial:
                self.console.print(f"[dim]Found {len(initial)} recent entries[/dim]")
                for entry in initial[-5:]:  # Show last 5
                    self._display_entry(entry)
            self.console.print()

            start_time = time.time()
            last_check = start_time

            while self._running:
                current_time = time.time()

                # Check duration limit
                if duration and (current_time - start_time) >= duration:
                    self.console.print("[yellow]Duration limit reached[/yellow]")
                    break

                # Check for new entries
                if current_time - last_check >= self.interval:
                    new_entries = self._get_new_entries()
                    for entry in new_entries:
                        self._handle_entry(entry)
                    last_check = current_time

                    if not new_entries:
                        # Show heartbeat
                        self.console.print(
                            f"[dim]{datetime.now().strftime('%H:%M:%S')} - "
                            f"No new entries[/dim]",
                            end="\r",
                        )

                time.sleep(1)

        finally:
            # Restore signal handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            self._running = False

    def stop(self) -> None:
        """Stop the monitor."""
        self._running = False


def watch_component(
    client: AuditLogsClient,
    component_id: str,
    console: Console | None = None,
    interval: int = 60,
) -> None:
    """Watch a specific component for audit events.

    Args:
        client: Audit logs API client.
        component_id: Component ID to watch.
        console: Rich console for output.
        interval: Polling interval in seconds.
    """
    console = console or Console()
    monitor = AuditLogMonitor(client, console, interval)

    console.print(f"[green]Watching component:[/green] {component_id}")

    # Override get_new_entries to filter by component
    original_get_new = monitor._get_new_entries

    def filtered_get_new() -> list[AuditLogEntry]:
        entries = original_get_new()
        return [e for e in entries if e.component_id == component_id]

    monitor._get_new_entries = filtered_get_new  # type: ignore
    monitor.start()


def watch_user(
    client: AuditLogsClient,
    user_id: str,
    console: Console | None = None,
    interval: int = 60,
) -> None:
    """Watch a specific user's audit events.

    Args:
        client: Audit logs API client.
        user_id: User ID or email to watch.
        console: Rich console for output.
        interval: Polling interval in seconds.
    """
    console = console or Console()
    monitor = AuditLogMonitor(client, console, interval)

    console.print(f"[green]Watching user:[/green] {user_id}")

    # Override get_new_entries to filter by user
    original_get_new = monitor._get_new_entries

    def filtered_get_new() -> list[AuditLogEntry]:
        entries = original_get_new()
        return [
            e
            for e in entries
            if e.user_id == user_id or e.user_email == user_id
        ]

    monitor._get_new_entries = filtered_get_new  # type: ignore
    monitor.start()
