"""Real-time monitoring screen."""

import threading
from collections.abc import Iterator
from datetime import UTC, datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Input, Label, LoadingIndicator, Static
from textual.worker import Worker

from ...formatters import resolve_tcss_markup
from ...models import AuditLogQuery
from ..state import AppState
from ..widgets import AlertSummary, LogTable

# Cap _seen_ids to prevent unbounded memory growth during long sessions
_MAX_SEEN_IDS = 10_000
# Fetch multiple pages per poll to avoid dropping events during bursts.
_MAX_POLL_PAGES = 20


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
        self._refresh_worker: Worker | None = None
        self._last_timestamp: datetime | None = None
        self._seen_ids: set[str] = set()
        # Guard shared poll state against concurrent refresh/background workers.
        self._poll_lock = threading.Lock()

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield from self.compose_content()

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the monitor content.
        """
        controls = Horizontal(
            Button("▶ Start", id="start-button", variant="success"),
            Button("⏹ Stop", id="stop-button", variant="error", disabled=True),
            Label("Interval:"),
            Input(value="60", id="interval-input", type="integer"),
            Label("seconds"),
            id="monitor-controls",
        )

        status = Horizontal(
            Static(resolve_tcss_markup("[$danger]● stopped[/$danger]"), id="status-indicator"),
            Static("", id="stats-info"),
            id="monitor-status",
            classes="monitor-stopped",
        )

        yield Container(
            controls,
            status,
            Static("LIVE LOG STREAM", classes="section-label"),
            LogTable(id="monitor-log", show_details=False),
            Static("ALERTS", classes="section-label"),
            AlertSummary(id="alert-summary"),
            LoadingIndicator(id="loading"),
            id="monitor-container",
        )

    def refresh_data(self) -> None:
        """Refresh monitor data for the active screen."""
        if self._state.monitor.is_running:
            if self._poll_lock.locked() or (
                self._refresh_worker is not None and self._refresh_worker.is_running
            ):
                self.app.notify("Monitor poll already in progress.", severity="information")
                return
            self._refresh_worker = self.run_worker(
                self._poll_once(),
                exclusive=False,
                thread=True,
            )
        else:
            self.app.notify("Monitor is stopped. Start monitoring to fetch live entries.")

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
        self.query_one("#status-indicator", Static).update(
            resolve_tcss_markup("[$success]● running[/$success]")
        )

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
        if self._refresh_worker:
            self._refresh_worker.cancel()
            self._refresh_worker = None

        # Update UI
        self.query_one("#start-button", Button).disabled = False
        self.query_one("#stop-button", Button).disabled = True
        self.query_one("#interval-input", Input).disabled = False

        status_container = self.query_one("#monitor-status")
        status_container.remove_class("monitor-running")
        status_container.add_class("monitor-stopped")
        self.query_one("#status-indicator", Static).update(
            resolve_tcss_markup("[$danger]● stopped[/$danger]")
        )

    async def _monitoring_loop(self) -> None:
        """Main monitoring loop."""
        import asyncio

        while self._state.monitor.is_running:
            try:
                with self._poll_lock:
                    await self._poll_for_new_entries()
                    self._state.monitor.last_check = datetime.now(UTC)
                if self._state.monitor.is_running:
                    self.app.call_from_thread(self._update_stats_display)
            except Exception as e:
                self.app.call_from_thread(self._show_error, str(e))

            # Wait for interval
            await asyncio.sleep(self._state.monitor.interval)

    async def _poll_once(self) -> None:
        """Poll once for new entries (used by manual refresh)."""
        try:
            if not self._state.monitor.is_running:
                return
            with self._poll_lock:
                if not self._state.monitor.is_running:
                    return
                await self._poll_for_new_entries()
                if not self._state.monitor.is_running:
                    return
                self._state.monitor.last_check = datetime.now(UTC)
            if self._state.monitor.is_running:
                self.app.call_from_thread(self._update_stats_display)
        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))

    async def _poll_for_new_entries(self) -> None:
        """Poll API for new entries."""
        if not self._state.monitor.is_running:
            return
        try:
            query = AuditLogQuery(
                start_date=self._last_timestamp,
                page_size=100,
                page=0,
            )
            entries = []
            hit_page_limit = False
            page = 0
            while page < _MAX_POLL_PAGES:
                if not self._state.monitor.is_running:
                    return
                query.page = page
                response = self._state.client.get_logs(query)
                batch = response.content
                if not batch:
                    break
                entries.extend(batch)

                oldest_ts = next(
                    (entry.timestamp for entry in reversed(batch) if entry.timestamp),
                    None,
                )
                reached_known_time = bool(
                    self._last_timestamp and oldest_ts and oldest_ts <= self._last_timestamp
                )
                if response.last or reached_known_time:
                    break
                page += 1
            else:
                hit_page_limit = True

            if hit_page_limit:
                self.app.call_from_thread(
                    self._show_warning,
                    "High event volume detected; only the most recent pages were fetched.",
                )
        except Exception as e:
            self.app.call_from_thread(self._show_error, f"API error: {e}")
            return

        if not self._state.monitor.is_running:
            return

        # Filter out already seen entries
        new_entries = []
        for entry in entries:
            entry_key = (
                entry.id
                or f"{entry.timestamp}-{entry.action}-{entry.component_type}-{entry.component_id}-"
                f"{entry.user_id}-{entry.user_email}"
            )
            if entry_key not in self._seen_ids:
                self._seen_ids.add(entry_key)
                new_entries.append(entry)

        # Prune _seen_ids if it grows too large
        if len(self._seen_ids) > _MAX_SEEN_IDS:
            # Keep only the most recent half
            excess = len(self._seen_ids) - _MAX_SEEN_IDS // 2
            it = iter(self._seen_ids)
            to_remove = [next(it) for _ in range(excess)]
            self._seen_ids.difference_update(to_remove)

        if new_entries:
            # Update last timestamp
            timestamps = [e.timestamp for e in new_entries if e.timestamp]
            if timestamps:
                self._last_timestamp = max(timestamps)

            # Update count
            self._state.monitor.entries_since_start += len(new_entries)

            # Check for alerts
            fired = self._state.check_alerts(new_entries)
            if fired:
                self._state.monitor.alerts_triggered += len(fired)
                for fa in fired:
                    self.app.call_from_thread(self._show_alert, fa.rule_name, fa.message)

            # Add entries to table (in reverse order so newest is at top)
            for entry in reversed(new_entries):
                self.app.call_from_thread(self._add_entry_to_table, entry)

        # Drain any pending delivery-failure warning, regardless of whether this poll had new
        # entries. Matches the CLI's _handle_entry behavior (drain after every alert-engine cycle).
        warning = self._state.notification_manager.pop_first_failure()
        if warning:
            self.app.call_from_thread(self._show_warning, warning)

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

    def _show_warning(self, warning: str) -> None:
        """Show warning message."""
        self.app.notify(warning, severity="warning")

    def _show_alert(self, rule_name: str, message: str) -> None:
        """Show alert notification."""
        text = f"{rule_name}: {message}"
        self.app.notify(text, severity="warning")
        alert_summary = self.query_one("#alert-summary", AlertSummary)
        alert_summary.add_alert(rule_name, message)
