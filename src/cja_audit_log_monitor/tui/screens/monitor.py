"""Real-time monitoring screen."""

import logging
import threading
from collections.abc import Iterator
from datetime import UTC, datetime

from textual.binding import Binding
from textual.containers import Container, Horizontal
from textual.validation import Integer
from textual.widget import Widget
from textual.widgets import Button, Input, Label, Static
from textual.worker import Worker

from ...alerts import FiredAlert
from ...config import MAX_MONITOR_INTERVAL
from ...formatters import cut_cells, literal, resolve_tcss_markup
from ...models import AuditLogEntry
from ...monitor import (
    POLL_OVERLAP,
    POLL_PAGE_SIZE,
    SEEN_IDS_MAX,
    build_poll_query,
    fetch_unseen,
    is_retryable,
    seen_time,
    skipped_message,
)
from ...utils import RecentIds, entry_key, to_local
from ..state import AppState
from ..widgets import AlertSummary, LogTable
from .base import ContentView, classify_error

logger = logging.getLogger(__name__)

# Rows kept in the live stream; older rows are dropped so long sessions stay fast.
MONITOR_MAX_ROWS = 1000
# Rows the first poll of a session shows as context. They are not alerted on or counted.
_CONTEXT_ROWS = 100
# Allowed polling interval, in seconds (the same limits as monitor_interval).
_MIN_INTERVAL = 5
_MAX_INTERVAL = MAX_MONITOR_INTERVAL


class _IntervalInput(Input):
    """The interval box. It takes digits only, so it lets space through to start/stop."""

    def check_consume_key(self, key: str, character: str | None) -> bool:
        """Do not claim space, so the view's start/stop binding still sees it."""
        return key != "space" and super().check_consume_key(key, character)


class MonitorView(ContentView):
    """View for real-time audit log monitoring."""

    # Priority, so space reaches this binding before the focused interval box handles it.
    BINDINGS = [
        Binding("space", "toggle_monitor", "start/stop", priority=True),
    ]

    # The view itself takes focus so `space` works as soon as it is shown.
    can_focus = True

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize MonitorView.

        Args:
            state: Application state.
            **kwargs: Additional arguments for the view.
        """
        super().__init__(state, **kwargs)
        self._monitor_worker: Worker | None = None
        self._refresh_worker: Worker | None = None
        # When the last successful poll ran; the next poll reads from just before it.
        self._last_poll_time: datetime | None = None
        # Keys of recent entries, so the overlap between polls is not shown twice.
        self._seen = RecentIds(SEEN_IDS_MAX)
        # Guard shared poll state against concurrent refresh/background workers.
        self._poll_lock = threading.Lock()
        # Set to end the running monitor loop. Each start makes a new event, so a loop
        # or poll from an earlier start cannot write into a later session.
        self._stop_event: threading.Event | None = None

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the monitor content.
        """
        controls = Horizontal(
            Button("▶ start", id="start-button", variant="success", compact=True),
            Button("■ stop", id="stop-button", variant="error", disabled=True, compact=True),
            Label("interval"),
            _IntervalInput(
                value=str(self._state.monitor.interval),
                id="interval-input",
                type="integer",
                compact=True,
                validators=[Integer(minimum=_MIN_INTERVAL, maximum=_MAX_INTERVAL)],
            ),
            Label("s"),
            id="monitor-controls",
            classes="toolbar",
        )

        status = Horizontal(
            Static(resolve_tcss_markup("[$danger]● stopped[/$danger]"), id="status-indicator"),
            Static("last check - · new 0 · alerts 0", id="stats-info"),
            id="monitor-status",
            classes="monitor-status monitor-stopped",
        )

        yield Container(
            controls,
            status,
            Static("LIVE LOG STREAM", classes="section-label"),
            LogTable(id="monitor-log"),
            Static("ALERTS", classes="section-label"),
            AlertSummary(id="alert-summary"),
            id="monitor-container",
        )

    def default_focus(self) -> Widget | None:
        """Focus the view so `space` toggles monitoring right away."""
        return self

    def refresh_data(self) -> bool:
        """Poll now if monitoring is running.

        Returns:
            False when no poll started; the user has been told why.
        """
        if not self._state.monitor.is_running:
            self.app.notify("the monitor is stopped · press space to start it")
            return False
        if self._poll_lock.locked() or (
            self._refresh_worker is not None and self._refresh_worker.is_running
        ):
            self.app.notify("a poll is already running", severity="information")
            return False
        self._refresh_worker = self.run_worker(
            self._poll_once(self._stop_event),
            exclusive=False,
            thread=True,
        )
        return True

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Apply the interval when Enter is pressed in its box."""
        if event.input.id == "interval-input":  # pragma: no branch - the only Input here
            self._apply_interval()

    def on_settings_reloaded(self) -> None:
        """Show the reloaded default interval (the monitor is stopped; reload needs that)."""
        box = self.query_one("#interval-input", Input)
        box.value = str(self._state.monitor.interval)
        box.validate(box.value)  # clears a stale -invalid mark

    def _apply_interval(self) -> bool:
        """Use the interval box's value if it is 5 to 86,400 seconds.

        Otherwise keep the current interval and mark the box invalid.

        Returns:
            True if the box held a valid interval.
        """
        interval_input = self.query_one("#interval-input", Input)
        result = interval_input.validate(interval_input.value)  # sets or clears -invalid
        if result is not None and not result.is_valid:
            interval_input.add_class("-invalid")
            return False
        self._state.monitor.interval = int(interval_input.value)
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "start-button":
            self._start_monitoring()
        elif event.button.id == "stop-button":  # pragma: no branch - only two buttons
            self._stop_monitoring()

    def action_toggle_monitor(self) -> None:
        """Toggle monitoring on/off."""
        if self._state.monitor.is_running:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self) -> None:
        """Start the monitoring loop."""
        if not self._apply_interval():
            self._show_warning(
                f"interval must be {_MIN_INTERVAL} to {_MAX_INTERVAL:,} seconds · "
                f"using {self._state.monitor.interval}"
            )
        monitor = self._state.monitor
        monitor.is_running = True
        monitor.entries_since_start = 0
        monitor.alerts_triggered = 0
        monitor.last_check = None
        monitor.last_error = None
        self.query_one("#alert-summary", AlertSummary).clear()

        # A new session starts from now with nothing seen.
        self._seen = RecentIds(SEEN_IDS_MAX)
        self._last_poll_time = None

        # Update UI
        self.query_one("#start-button", Button).disabled = True
        self.query_one("#stop-button", Button).disabled = False
        self.query_one("#interval-input", Input).disabled = True

        self._set_status("running")
        self._update_stats_display()

        # Clear log table
        self.query_one("#monitor-log", LogTable).clear()

        # Start monitoring worker
        self._stop_event = threading.Event()
        self._monitor_worker = self.run_worker(
            self._monitoring_loop(self._stop_event),
            exclusive=True,
            thread=True,
        )

    def _stop_monitoring(self) -> None:
        """Stop the monitoring loop."""
        self._state.monitor.is_running = False
        if self._stop_event:
            self._stop_event.set()
            self._stop_event = None

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

        self._set_status("stopped")

    _STATUS_MARKUP = {
        "running": "[$success]● running[/$success]",
        "error": "[$warning]● error[/$warning] [$text-muted]· retrying each interval[/$text-muted]",
        "stopped": "[$danger]● stopped[/$danger]",
    }

    def _set_status(self, status: str, detail: str = "") -> None:
        """Show ``running``, ``error`` or ``stopped`` in the status row; an error shows why."""
        status_container = self.query_one("#monitor-status")
        for name in self._STATUS_MARKUP:
            status_container.set_class(status == name, f"monitor-{name}")
        markup = self._STATUS_MARKUP[status]
        if status == "error" and detail:
            first_line = " ".join(detail.split())
            short = cut_cells(first_line, max(20, self.size.width - 40))
            markup = (
                f"[$warning]● error[/$warning] [$text-muted]· {literal(short)} "
                f"· retrying each interval[/$text-muted]"
            )
        self.query_one("#status-indicator", Static).update(resolve_tcss_markup(markup))

    def on_unmount(self) -> None:
        """End the monitor loop when the view goes away, e.g., when the app quits.

        Python waits for the loop's thread before the program exits, so a loop left
        running would hold the terminal until its next poll.
        """
        self._state.monitor.is_running = False
        if self._stop_event:
            self._stop_event.set()

    async def _monitoring_loop(self, stop: threading.Event) -> None:
        """Poll until ``stop`` is set, waiting the interval between polls.

        The wait is ``stop.wait``, not a sleep, so a stop ends the loop at once.
        """
        while not stop.is_set():
            self._guarded_poll(stop)
            stop.wait(self._state.monitor.interval)

    async def _poll_once(self, stop: threading.Event | None = None) -> None:
        """Poll once for new entries (used by manual refresh)."""
        stop = stop or self._stop_event
        if stop is None or stop.is_set() or not self._state.monitor.is_running:
            return
        self._guarded_poll(stop)

    def _guarded_poll(self, stop: threading.Event) -> None:
        """Run one poll. Any error is logged and shown, never raised.

        The worker exits on error and takes the app with it, so one bad poll must not
        escape. Once ``stop`` is set, errors are dropped quietly (e.g. during shutdown).
        """
        try:
            with self._poll_lock:
                self._poll_for_new_entries(stop)
        except Exception as e:
            if stop.is_set():
                return
            logger.exception("Monitor poll failed")
            try:
                self.app.call_from_thread(self._apply_poll_error, stop, e, False)
            except Exception:
                logger.exception("Could not show the monitor poll failure")

    def _poll_for_new_entries(self, stop: threading.Event) -> None:
        """Fetch entries not seen yet and hand them to the UI in one call.

        Runs on a worker thread. Each poll reads from just before the last good poll up to
        now and drops entries already seen (see ``fetch_unseen``). The first poll of a session
        reads the whole window to seed the seen keys; its rows are context, not new events,
        so they are neither alerted on nor counted. Nothing is written once ``stop`` is set,
        so a poll from a stopped session is dropped.
        """
        if stop.is_set():
            return
        now = datetime.now(UTC)
        first_poll = self._last_poll_time is None
        query = build_poll_query(self._last_poll_time, now, POLL_PAGE_SIZE)
        warnings: list[str] = []
        try:
            new_entries, skipped = fetch_unseen(
                self._state.client.get_logs, query, self._seen, stop=stop
            )
        except Exception as e:
            if not stop.is_set():
                self.app.call_from_thread(self._apply_poll_error, stop, e)
            return
        if skipped != 0:
            warnings.append(skipped_message(skipped))

        fired: list[FiredAlert] = []
        try:
            if new_entries and not first_poll:
                # Checked right before alerting, so a stop sends no more notifications.
                if stop.is_set():
                    return
                fired = self._state.check_alerts(new_entries)
            # A delivery-failure warning is drained after every poll, as the CLI does.
            warnings.extend(self._state.notification_manager.pop_failures())
        except Exception as e:
            # A bug in local alert code is not an API failure: the poll itself worked.
            logger.exception("Monitor alert check failed")
            warnings.append(f"alert check failed · {e}")

        if stop.is_set():
            return
        self.app.call_from_thread(
            self._apply_poll, stop, now, new_entries, fired, warnings, first_poll
        )

    def _apply_poll(
        self,
        stop: threading.Event,
        polled_at: datetime,
        new_entries: list[AuditLogEntry],
        fired: list[FiredAlert],
        warnings: list[str],
        context_only: bool = False,
    ) -> None:
        """Show one good poll's results. Runs on the UI thread.

        With ``context_only`` (a session's first poll), the entries are remembered and the
        newest are shown, but they are not counted as new.
        """
        if stop.is_set():
            return  # the session this poll belongs to has ended
        # Remember entries only once the whole poll worked, so a failed page is re-read.
        for entry in new_entries:
            self._seen.add(entry_key(entry), seen_time(entry, polled_at))
        self._last_poll_time = polled_at
        # The next poll starts at polled_at - POLL_OVERLAP, so older entries cannot come back.
        self._seen.forget_before(polled_at - POLL_OVERLAP)

        monitor = self._state.monitor
        monitor.last_check = polled_at
        if context_only:
            new_entries = new_entries[-_CONTEXT_ROWS:]
        else:
            monitor.entries_since_start += len(new_entries)
        monitor.alerts_triggered += len(fired)
        if monitor.last_error is not None:
            monitor.last_error = None
            self._set_status("running")
        self.app.note_api_ok()

        if new_entries:
            # The newest row is at the bottom and the view follows it, like `tail -f`.
            table = self.query_one("#monitor-log", LogTable)
            table.append_entries(new_entries, MONITOR_MAX_ROWS)
        for fa in fired:
            self._show_alert(fa.summary)
        for warning in warnings:
            self._show_warning(warning)
        self._update_stats_display()

    def _apply_poll_error(
        self, stop: threading.Event, error: Exception, from_api: bool = True
    ) -> None:
        """Show a failed poll. Runs on the UI thread; only the first failure in a row toasts.

        ``from_api`` is False for a local bug, which must not mark the header disconnected.
        """
        if stop.is_set():
            return
        monitor = self._state.monitor
        new_error = monitor.last_error != str(error)  # a toast for each new error text
        monitor.last_error = str(error)
        if from_api:
            self.app.note_api_error(error)
            if classify_error(error) == "access":
                # The connection works but this account may not read the logs.
                self.app.set_connection_status("disconnected", f"no access: {error}")
        if from_api and not is_retryable(error):
            # Retrying cannot fix this (bad credentials, 400, 401, 403, 404): stop, as
            # the CLI monitor does, instead of failing every interval.
            self._stop_monitoring()
            self._show_error(f"{error} · monitor stopped")
            return
        self._set_status("error", str(error))
        if new_error:
            self._show_error(str(error))

    def _update_stats_display(self) -> None:
        """Update the stats display."""
        monitor = self._state.monitor
        last_check = f"{to_local(monitor.last_check):%H:%M:%S}" if monitor.last_check else "-"
        self.query_one("#stats-info", Static).update(
            f"last check {last_check} · "
            f"new {monitor.entries_since_start} · "
            f"alerts {monitor.alerts_triggered}"
        )

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.app.notify(f"monitor error · {error}", severity="error", markup=False)

    def _show_warning(self, warning: str) -> None:
        """Show warning message."""
        self.app.notify(warning, severity="warning", markup=False)

    def _show_alert(self, summary: str) -> None:
        """Show an alert's one line summary as a toast and in the recent alerts list."""
        self.app.notify(summary, severity="warning", markup=False)
        alert_summary = self.query_one("#alert-summary", AlertSummary)
        alert_summary.add_alert(summary)
