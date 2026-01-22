"""Real-time monitoring screen."""

from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widgets import Button, Input, Label, LoadingIndicator, Static
from textual.worker import Worker

from ...models import AuditLogQuery
from ..state import AppState
from ..widgets import AlertSummary, LogTable


class MonitorScreen(Screen):
    """Screen for real-time audit log monitoring."""

    BINDINGS = [
        ("space", "toggle_monitor", "Start/Stop"),
    ]

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize MonitorScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(**kwargs)
        self._state = state
        self._monitor_worker: Worker | None = None
        self._last_timestamp: datetime | None = None
        self._seen_ids: set[str] = set()

    def compose(self) -> ComposeResult:
        """Compose monitor screen widgets."""
        with Container(id="monitor-container"):
            with Horizontal(id="monitor-controls"):
                yield Button("▶ Start", id="start-button", variant="success")
                yield Button("⏹ Stop", id="stop-button", variant="error", disabled=True)
                yield Label("Interval:")
                yield Input(value="60", id="interval-input", type="integer")
                yield Label("seconds")

            with Horizontal(id="monitor-status", classes="monitor-stopped"):
                yield Static("● Stopped", id="status-indicator")
                yield Static("", id="stats-info")

            yield Static("[bold]Live Log Stream[/bold]")
            yield LogTable(id="monitor-log", show_details=False)

            yield Static("[bold]Alerts[/bold]")
            yield AlertSummary(id="alert-summary")

            yield LoadingIndicator(id="loading")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "start-button":
            self._start_monitoring()
        elif event.button.id == "stop-button":
            self._stop_monitoring()

    def action_toggle_monitor(self) -> None:
        """Toggle monitoring on/off."""
        if self._state.monitor.is_running:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self) -> None:
        """Start the monitoring loop."""
        # Get interval
        try:
            interval = int(self.query_one("#interval-input", Input).value)
            if interval < 5:
                interval = 5
                self.query_one("#interval-input", Input).value = "5"
        except ValueError:
            interval = 60

        self._state.monitor.interval = interval
        self._state.monitor.is_running = True
        self._state.monitor.entries_since_start = 0
        self._state.monitor.alerts_triggered = 0

        # Initialize seen IDs with current entries
        self._seen_ids.clear()
        self._last_timestamp = datetime.now(UTC)

        # Update UI
        self.query_one("#start-button", Button).disabled = True
        self.query_one("#stop-button", Button).disabled = False
        self.query_one("#interval-input", Input).disabled = True

        status_container = self.query_one("#monitor-status")
        status_container.remove_class("monitor-stopped")
        status_container.add_class("monitor-running")
        self.query_one("#status-indicator", Static).update("[green]● Running[/green]")

        # Clear log table
        self.query_one("#monitor-log", LogTable).clear()

        # Start monitoring worker
        self._monitor_worker = self.run_worker(
            self._monitoring_loop(),
            exclusive=True,
            thread=True,
        )

    def _stop_monitoring(self) -> None:
        """Stop the monitoring loop."""
        self._state.monitor.is_running = False

        if self._monitor_worker:
            self._monitor_worker.cancel()
            self._monitor_worker = None

        # Update UI
        self.query_one("#start-button", Button).disabled = False
        self.query_one("#stop-button", Button).disabled = True
        self.query_one("#interval-input", Input).disabled = False

        status_container = self.query_one("#monitor-status")
        status_container.remove_class("monitor-running")
        status_container.add_class("monitor-stopped")
        self.query_one("#status-indicator", Static).update("[red]● Stopped[/red]")

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        import asyncio

        while self._state.monitor.is_running:
            try:
                await self._poll_for_new_entries()
                self._state.monitor.last_check = datetime.now(UTC)
                self.call_from_thread(self._update_stats_display)
            except Exception as e:
                self.call_from_thread(self._show_error, str(e))

            # Wait for interval
            await asyncio.sleep(self._state.monitor.interval)

    async def _poll_for_new_entries(self) -> None:
        """Poll API for new entries."""
        query = AuditLogQuery(
            start_date=self._last_timestamp,
            page_size=100,
        )

        try:
            with self._state.client:
                entries = self._state.client.get_all_logs(query, max_entries=100)
        except Exception as e:
            self.call_from_thread(self._show_error, f"API error: {e}")
            return

        # Filter out already seen entries
        new_entries = []
        for entry in entries:
            if entry.id and entry.id not in self._seen_ids:
                self._seen_ids.add(entry.id)
                new_entries.append(entry)

        if new_entries:
            # Update last timestamp
            timestamps = [e.timestamp for e in new_entries if e.timestamp]
            if timestamps:
                self._last_timestamp = max(timestamps)

            # Update count
            self._state.monitor.entries_since_start += len(new_entries)

            # Check for alerts
            alerts = self._state.check_alerts(new_entries)
            if alerts:
                self._state.monitor.alerts_triggered += len(alerts)
                for alert in alerts:
                    # Extract alert info and notify
                    self.call_from_thread(self._show_alert, "Alert triggered")

            # Add entries to table (in reverse order so newest is at top)
            for entry in reversed(new_entries):
                self.call_from_thread(self._add_entry_to_table, entry)

    def _add_entry_to_table(self, entry) -> None:
        """Add entry to the monitor log table."""
        table = self.query_one("#monitor-log", LogTable)
        table.append_entry(entry)

    def _update_stats_display(self) -> None:
        """Update the stats display."""
        monitor = self._state.monitor
        last_check = monitor.last_check.strftime("%H:%M:%S") if monitor.last_check else "Never"
        self.query_one("#stats-info", Static).update(
            f"Last check: {last_check} | "
            f"New entries: {monitor.entries_since_start} | "
            f"Alerts: {monitor.alerts_triggered}"
        )

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.app.notify(f"Monitor error: {error}", severity="error")

    def _show_alert(self, message: str) -> None:
        """Show alert notification."""
        self.app.notify(message, severity="warning")
        alert_summary = self.query_one("#alert-summary", AlertSummary)
        alert_summary.add_alert("Alert", message)

    async def create_widget(self) -> Container:
        """Create widget for embedding in main content area.

        Returns:
            Container with monitor content.
        """
        container = Container()
        for widget in self.compose():
            await container.mount(widget)
        return container
