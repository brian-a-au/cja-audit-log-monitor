"""Real-time monitoring for audit logs."""

import logging
import signal
import threading
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.markup import escape
from rich.status import Status
from rich.text import Text

from .alerts import AlertEngine, order_oldest_first
from .auth import AuthenticationError
from .client import APIError, AuditLogsClient, is_final_page
from .formatters import get_action_color
from .models import AuditLogEntry, AuditLogQuery, AuditLogResponse
from .notifications import NotificationManager
from .utils import RecentIds, entry_key, get_user_identifier

logger = logging.getLogger(__name__)
_PACKAGE_LOGGER = "cja_audit_log_monitor"

# A poll asks for the largest page the API allows, so a normal poll is one request and a
# backlog after a gap (a laptop asleep, an outage) is read in few requests.
POLL_PAGE_SIZE = 1000
# The most pages one poll reads: 50,000 events, about a week at 5 events a minute. Past
# that the oldest events of the gap are skipped and the monitor says how many.
MAX_POLL_PAGES = 50

# API statuses that retrying will not fix: the monitor stops instead of looping.
FATAL_STATUS = frozenset({400, 401, 403, 404})

# Each poll re-reads this much before the last poll, so late-arriving events are not missed.
POLL_OVERLAP = timedelta(minutes=5)
# How many recent entry keys to remember for de-duplicating the overlap.
SEEN_IDS_MAX = 5000


def build_poll_query(since: datetime | None, now: datetime, page_size: int) -> AuditLogQuery:
    """Build the query for one poll: from just before ``since`` (or ``now``) up to ``now``."""
    return AuditLogQuery(
        start_date=(since or now) - POLL_OVERLAP,
        end_date=now,
        page=0,
        page_size=page_size,
    )


def fetch_unseen(
    get_logs: Callable[[AuditLogQuery], AuditLogResponse],
    query: AuditLogQuery,
    seen: RecentIds,
    max_pages: int | None = None,
    stop: threading.Event | None = None,
) -> tuple[list[AuditLogEntry], int | None]:
    """Read every page of ``query`` and return the entries not in ``seen``, oldest first.

    Paging ends on an empty page, the last page (by ``last`` or the API's page count), or after
    ``max_pages`` pages. A page of entries already seen does not end it: pages are newest first,
    so a late-indexed entry can sit behind them. ``seen`` is not changed; the caller adds the
    keys once the whole poll has worked. When ``stop`` is set, paging ends before the next page.

    Returns:
        The unseen entries, oldest first, and how many matching events were not read
        because the page limit ended paging: 0 when paging ended normally, or None when
        the limit was hit and the API gave no total.
    """
    if max_pages is None:
        max_pages = MAX_POLL_PAGES
    fresh: dict[str, AuditLogEntry] = {}
    read = 0
    response: AuditLogResponse | None = None
    for page in range(max_pages):
        if stop is not None and stop.is_set():
            break
        query.page = page
        response = get_logs(query)
        read += len(response.content)
        for entry in response.content:
            key = entry_key(entry)
            if key not in seen and key not in fresh:
                fresh[key] = entry
        if not response.content or response.last or is_final_page(page, response):
            break
    else:
        total = response.total_elements if response is not None else None
        # A total below what was read means the API's count is not usable here.
        skipped = None if total is None or total < read else total - read
        return list(reversed(fresh.values())), skipped
    # The API returns newest first; hand them back oldest first.
    return list(reversed(fresh.values())), 0


def skipped_message(skipped: int | None) -> str:
    """The warning for a poll that hit the page limit (``skipped`` from fetch_unseen)."""
    if skipped is None:
        return "The gap held more events than one poll reads; older events were skipped."
    return f"{skipped:,} older events in this gap were skipped (more than one poll reads)."


class AuditLogMonitor:
    """Real-time monitor for CJA audit logs."""

    def __init__(
        self,
        client: AuditLogsClient,
        console: Console | None = None,
        err_console: Console | None = None,
        interval: int = 60,
        alert_engine: AlertEngine | None = None,
        notification_manager: NotificationManager | None = None,
        entry_filter: Callable[[AuditLogEntry], bool] | None = None,
    ) -> None:
        """Initialize the monitor.

        Args:
            client: Audit logs API client.
            console: Rich console for entries and the status line.
            err_console: Rich console for warnings; defaults to one writing to stderr.
            interval: Polling interval in seconds.
            alert_engine: Optional alert engine for suspicious activity detection.
            notification_manager: Optional notification manager for external delivery.
            entry_filter: Optional predicate; only entries it accepts are returned.
        """
        self.client = client
        self.console = console or Console()
        self.err_console = err_console or Console(stderr=True)
        self._status: Status | None = None
        self.interval = interval
        self.alert_engine = alert_engine
        self.notification_manager = notification_manager
        self._running = False
        self._entry_filter = entry_filter
        self._last_poll_time: datetime | None = None
        self._seen = RecentIds(SEEN_IDS_MAX)
        # When the first poll was tried; events after it are never treated as baseline.
        self._first_attempt: datetime | None = None
        # Events the last poll skipped at the page limit (None: an unknown number).
        self._skipped: int | None = 0
        # Why the last poll failed, or None when it worked.
        self._poll_error: str | None = None
        # How many polls worked, so a caller can tell a run where every poll failed.
        self.successful_polls = 0
        self._stop_announced = False
        # True while a poll (and its alerts and deliveries) runs; Ctrl+C then ends it at once.
        self._in_poll = False
        # True once Ctrl+C or SIGTERM stopped the monitor.
        self.stopped_by_user = False
        self._on_new_entry: Callable[[AuditLogEntry], None] | None = None

    def set_callback(self, callback: Callable[[AuditLogEntry], None]) -> None:
        """Set callback for new entries.

        Args:
            callback: Function to call with each new entry.
        """
        self._on_new_entry = callback

    def _get_new_entries(self) -> list[AuditLogEntry]:
        """Fetch entries not seen before, oldest first.

        Each poll re-reads an overlap window before the last poll and drops entries whose key is
        already remembered, so late-indexed events are not missed. The first poll reads the whole
        window to seed the remembered keys. Fatal API errors are re-raised; other errors are
        logged and give no entries.
        """
        now = datetime.now(UTC)
        if self._last_poll_time is None and self._first_attempt is None:
            self._first_attempt = now
        query = build_poll_query(self._last_poll_time, now, POLL_PAGE_SIZE)
        self._skipped = 0

        try:
            new_entries, skipped = fetch_unseen(self.client.get_logs, query, self._seen)
            if skipped != 0:
                self._skipped = skipped
        except AuthenticationError as e:
            if not e.transient:
                raise
            # IMS or the network failed for a moment: try again next poll, like an API 503.
            logger.error("Error fetching audit logs: %s", e)
            self._poll_error = str(e)
            return []
        except APIError as e:
            if e.status_code in FATAL_STATUS:
                raise
            logger.error("Error fetching audit logs: %s", e)
            self._poll_error = str(e)
            return []
        except Exception as e:
            logger.error("Error fetching audit logs: %s", e)
            self._poll_error = str(e)
            return []
        self._poll_error = None
        self.successful_polls += 1

        # Only remember entries once the whole poll succeeded, so a failed page is retried.
        for entry in new_entries:
            self._seen.add(entry_key(entry))
        self._last_poll_time = now

        if self._entry_filter:
            new_entries = [e for e in new_entries if self._entry_filter(e)]
        return order_oldest_first(new_entries)

    def _handle_entry(self, entry: AuditLogEntry) -> None:
        """Handle a new audit log entry."""
        if self.alert_engine:
            for fa in self.alert_engine.check_entry(entry):
                self.console.print(fa.panel)
                if self.notification_manager and self.notification_manager.is_configured():
                    try:
                        self.notification_manager.notify_alert(
                            fa.rule_name, fa.message, fa.entry
                        )
                    except Exception as e:
                        logger.error(
                            "Notification dispatch failed for rule %s: %s",
                            fa.rule_name,
                            type(e).__name__,
                        )
            if self.notification_manager:
                warning = self.notification_manager.pop_first_failure()
                if warning:
                    self._print_warning(str(warning))

        self._display_entry(entry)

        if self._on_new_entry:
            self._on_new_entry(entry)

    def _print_warning(self, text: str) -> None:
        """Print a warning to stderr without corrupting the live status line.

        Rich does not route the stderr console through the live display on stdout, so the
        status is paused while the warning prints and then shown again.
        """
        status = self._status
        if status is not None:
            status.stop()
        try:
            self.err_console.print(f"[yellow]{escape(text)}[/yellow]")
        finally:
            if status is not None:
                status.start()

    @contextmanager
    def _logs_around_status(self) -> Iterator[None]:
        """While the status line is live, print the package's log records around it.

        The root handler writes to stderr, which Rich does not route through the live
        status on stdout, so a log line would land on the status line. Here each record is
        printed with the status paused, and the package logger stops passing records up
        to the root handler until the monitor ends.
        """
        monitor = self
        package_logger = logging.getLogger(_PACKAGE_LOGGER)

        class _AroundStatus(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                try:
                    monitor._print_warning(record.getMessage())
                except Exception:
                    self.handleError(record)

        handler = _AroundStatus()
        old_propagate = package_logger.propagate
        package_logger.addHandler(handler)
        package_logger.propagate = False
        try:
            yield
        finally:
            package_logger.removeHandler(handler)
            package_logger.propagate = old_propagate

    def _display_entry(self, entry: AuditLogEntry) -> None:
        """Display a new audit log entry."""
        timestamp = entry.timestamp.strftime("%H:%M:%S UTC") if entry.timestamp else "-"
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
        """Stop the monitor. During a poll, end the poll at once.

        A poll can block on the network or on a webhook for minutes, so waiting for it
        would make Ctrl+C look broken. The entries of an interrupted poll are dropped.
        """
        self._running = False
        self.stopped_by_user = True
        if not self._stop_announced:
            self._stop_announced = True
            self.console.print("\n[yellow]Monitor stopped.[/yellow]")
        if self._in_poll:
            raise KeyboardInterrupt

    def _run_poll(self, status: Status) -> None:
        """Poll once, show the result, and update the status line."""
        self._in_poll = True
        try:
            self._poll_and_show(status)
        finally:
            self._in_poll = False

    def _poll_and_show(self, status: Status) -> None:
        """The body of ``_run_poll``."""
        is_baseline = self._last_poll_time is None
        entries = self._get_new_entries()
        if self._skipped != 0:
            self._print_warning(skipped_message(self._skipped))
        if is_baseline and self._first_attempt is not None:
            # Polls before this one failed: events after the first attempt are new, not
            # baseline, so they still raise alerts.
            first = self._first_attempt
            late = [e for e in entries if e.timestamp is not None and e.timestamp > first]
            entries = [e for e in entries if e not in late]
            for entry in late:
                self._handle_entry(entry)
        if is_baseline:
            if entries:
                self.console.print(f"[dim]Found {len(entries)} recent entries[/dim]")
                for entry in entries[-5:]:
                    self._display_entry(entry)
                self.console.print()
        else:
            for entry in entries:
                self._handle_entry(entry)
        clock = datetime.now(UTC).strftime("%H:%M:%S UTC")
        if self._poll_error is not None:
            status.update(
                f"Last poll {clock} failed: {escape(self._poll_error)}. "
                f"Retrying in {self.interval}s"
            )
        elif is_baseline:
            status.update(
                f"Baseline {clock}: {len(entries)} existing entries. Next in {self.interval}s"
            )
        else:
            skipped = ""
            if self._skipped != 0:
                count = "some" if self._skipped is None else f"{self._skipped:,}"
                skipped = f", {count} skipped"
            status.update(
                f"Last poll {clock}: {len(entries)} new{skipped}. Next in {self.interval}s"
            )

    def start(self, duration: int | None = None) -> None:
        """Start monitoring for new audit log entries.

        Args:
            duration: Optional duration in seconds. None for indefinite.
        """
        self._running = True
        self._stop_announced = False

        # Register signal handlers
        original_sigint = signal.signal(signal.SIGINT, self._signal_handler)
        original_sigterm = signal.signal(signal.SIGTERM, self._signal_handler)

        try:
            self.console.print(
                f"[green]Starting audit log monitor[/green] "
                f"(polling every {self.interval}s, Ctrl+C to stop)"
            )
            self.console.print()

            # Initial fetch sets the baseline; show the newest few entries for context.
            with suppress(KeyboardInterrupt), self.console.status(
                "Waiting for first poll..."
            ) as status, self._logs_around_status():
                self._status = status
                # The duration counts from before the first poll, which can be slow.
                start_time = time.monotonic()
                last_check = start_time
                self._run_poll(status)

                while self._running:
                    current_time = time.monotonic()

                    # Check duration limit
                    if duration and (current_time - start_time) >= duration:
                        self.console.print("[yellow]Duration limit reached[/yellow]")
                        break

                    if current_time - last_check >= self.interval:
                        self._run_poll(status)
                        last_check = current_time

                    time.sleep(1)

        finally:
            self._status = None
            # Restore signal handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            self._running = False

    def stop(self) -> None:
        """Stop the monitor."""
        self._running = False
