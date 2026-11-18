"""Real-time monitoring for audit logs."""

import logging
import signal
import threading
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from rich.console import Console
from rich.markup import escape
from rich.status import Status
from rich.text import Text

from .alerts import AlertEngine
from .auth import AuthenticationError
from .client import APIError, AuditLogsClient, is_final_page
from .formatters import get_action_color
from .models import AuditLogEntry, AuditLogQuery, AuditLogResponse
from .notifications import NotificationManager
from .utils import RecentIds, entry_key, get_user_identifier

logger = logging.getLogger(__name__)

_MONITOR_PAGE_SIZE = 100
_MAX_POLL_PAGES = 20

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
    max_pages: int = _MAX_POLL_PAGES,
    stop: threading.Event | None = None,
) -> tuple[list[AuditLogEntry], bool]:
    """Read every page of ``query`` and return the entries not in ``seen``, oldest first.

    Paging ends on an empty page, the last page (by ``last`` or the API's page count), or after
    ``max_pages`` pages. A page of entries already seen does not end it: pages are newest first,
    so a late-indexed entry can sit behind them. ``seen`` is not changed; the caller adds the
    keys once the whole poll has worked. When ``stop`` is set, paging ends before the next page.

    Returns:
        The unseen entries, oldest first, and whether the page limit ended paging.
    """
    fresh: dict[str, AuditLogEntry] = {}
    hit_cap = False
    for page in range(max_pages):
        if stop is not None and stop.is_set():
            break
        query.page = page
        response = get_logs(query)
        for entry in response.content:
            key = entry_key(entry)
            if key not in seen and key not in fresh:
                fresh[key] = entry
        if not response.content or response.last or is_final_page(page, response):
            break
    else:
        hit_cap = True
    # The API returns newest first; hand them back oldest first.
    return list(reversed(fresh.values())), hit_cap


class AuditLogMonitor:
    """Real-time monitor for CJA audit logs."""

    def __init__(
        self,
        client: AuditLogsClient,
        console: Console | None = None,
        interval: int = 60,
        alert_engine: AlertEngine | None = None,
        notification_manager: NotificationManager | None = None,
        entry_filter: Callable[[AuditLogEntry], bool] | None = None,
    ) -> None:
        """Initialize the monitor.

        Args:
            client: Audit logs API client.
            console: Rich console for output.
            interval: Polling interval in seconds.
            alert_engine: Optional alert engine for suspicious activity detection.
            notification_manager: Optional notification manager for external delivery.
            entry_filter: Optional predicate; only entries it accepts are returned.
        """
        self.client = client
        self.console = console or Console()
        self.interval = interval
        self.alert_engine = alert_engine
        self.notification_manager = notification_manager
        self._running = False
        self._entry_filter = entry_filter
        self._last_poll_time: datetime | None = None
        self._seen = RecentIds(SEEN_IDS_MAX)
        # Why the last poll failed, or None when it worked.
        self._poll_error: str | None = None
        self._stop_announced = False
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
        query = build_poll_query(self._last_poll_time, now, _MONITOR_PAGE_SIZE)

        try:
            new_entries, hit_cap = fetch_unseen(self.client.get_logs, query, self._seen)
            if hit_cap:
                logger.warning(
                    "Monitor poll reached %d pages; backlog may be larger than one cycle",
                    _MAX_POLL_PAGES,
                )
        except AuthenticationError:
            raise
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

        # Only remember entries once the whole poll succeeded, so a failed page is retried.
        for entry in new_entries:
            self._seen.add(entry_key(entry))
        self._last_poll_time = now

        if self._entry_filter:
            new_entries = [e for e in new_entries if self._entry_filter(e)]
        return new_entries

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
                    except Exception:
                        logger.exception(
                            "Notification dispatch failed for rule %s", fa.rule_name
                        )
            if self.notification_manager:
                warning = self.notification_manager.pop_first_failure()
                if warning:
                    self.console.print(f"[yellow]{escape(str(warning))}[/yellow]")

        self._display_entry(entry)

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
        if not self._stop_announced:
            self._stop_announced = True
            self.console.print("\n[yellow]Stopping monitor...[/yellow]")

    def _run_poll(self, status: Status) -> None:
        """Poll once, show the result, and update the status line."""
        is_baseline = self._last_poll_time is None
        entries = self._get_new_entries()
        if is_baseline:
            if entries:
                self.console.print(f"[dim]Found {len(entries)} recent entries[/dim]")
                for entry in entries[-5:]:
                    self._display_entry(entry)
                self.console.print()
        else:
            for entry in entries:
                self._handle_entry(entry)
        clock = datetime.now().strftime("%H:%M:%S")
        if self._poll_error is not None:
            status.update(
                f"Last poll {clock} failed: {escape(self._poll_error)}. "
                f"Retrying in {self.interval}s"
            )
        else:
            status.update(f"Last poll {clock}: {len(entries)} new. Next in {self.interval}s")

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
            with self.console.status("Waiting for first poll...") as status:
                self._run_poll(status)

                start_time = time.monotonic()
                last_check = start_time

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
            # Restore signal handlers
            signal.signal(signal.SIGINT, original_sigint)
            signal.signal(signal.SIGTERM, original_sigterm)
            self._running = False

    def stop(self) -> None:
        """Stop the monitor."""
        self._running = False
