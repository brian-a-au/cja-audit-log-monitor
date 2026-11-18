"""Dashboard screen showing summary statistics."""

from collections.abc import Iterator
from datetime import datetime, timedelta

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...alerts import analyze_for_anomalies
from ...formatters import resolve_tcss_markup
from ...stats import build_date_range_query, calculate_stats, get_hourly_distribution
from ...utils import local_tz_name
from ..state import AppState
from ..widgets import ActionBarChart, FittedStatic, HourlyChart
from .base import (
    ContentView,
    error_message,
    no_activity_message,
    not_connected_message,
    sample_note,
    show_sample_note,
    stat_card,
)

DASHBOARD_DAYS = 7
DASHBOARD_SAMPLE = 1000


class DashboardScreen(ContentView):
    """Dashboard screen with summary view."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize DashboardScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for the view.
        """
        super().__init__(state, **kwargs)
        self._stats: dict = {}
        self._top_users: list[tuple[str, int]] | None = None  # None until data loads

    def compose_header(self) -> Iterator[Widget]:
        """Title stays visible above the empty state."""
        yield Static("dashboard", id="dashboard-title", classes="section-label view-title")

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for the dashboard."""
        yield LoadingIndicator(id="dashboard-loading")
        yield Horizontal(
            stat_card("total entries", "stat-total"),
            stat_card("active users", "stat-users"),
            stat_card("anomalies", "stat-alerts"),
            stat_card(f"last {DASHBOARD_DAYS} days", "stat-range"),
            classes="dashboard-stats",
        )
        yield sample_note()
        yield Horizontal(
            Vertical(
                Static("ACTION DISTRIBUTION", classes="section-label"),
                ActionBarChart(id="action-chart"),
                Static(
                    f"HOURLY ACTIVITY · {local_tz_name()}",
                    id="dashboard-hourly-label",
                    classes="section-label",
                ),
                HourlyChart(id="hourly-chart"),
                id="dash-left",
            ),
            Vertical(
                Static("TOP USERS", classes="section-label"),
                FittedStatic(id="top-users", redraw=self._render_top_users),
                Static("RECENT ANOMALIES", classes="section-label"),
                Static(id="anomalies"),
                id="dash-right",
            ),
            id="dash-columns",
        )
        yield Horizontal(
            Button("refresh", id="refresh-button", variant="primary", compact=True),
            Static(id="last-update"),
            classes="toolbar",
        )

    def on_content_mounted(self) -> None:
        """Load data the first time the dashboard is shown."""
        self.refresh_data()

    def refresh_data(self) -> None:
        """Refresh dashboard data."""
        self.set_loading(True)
        self.run_worker(self._load_data(), exclusive=True, thread=True)

    async def _load_data(self) -> None:
        """Load dashboard data."""
        worker = get_current_worker()

        try:
            result = self._state.verify_connection()

            if worker.is_cancelled:
                return

            if not result.get("connected"):
                error = str(result.get("error", "connection failed"))
                self.app.call_from_thread(self._show_disconnected, error)
                return

            self.app.call_from_thread(
                self.app.set_connection_status,
                "connected",
                f"org {result.get('org_id', 'unknown')}",
            )

            query = build_date_range_query(DASHBOARD_DAYS)
            entries, total = self._state.client.get_logs_sample(query, max_entries=DASHBOARD_SAMPLE)

            if worker.is_cancelled:
                return

            if not entries:
                self.app.call_from_thread(
                    self.set_empty_state, no_activity_message(DASHBOARD_DAYS)
                )
                return

            stats = calculate_stats(entries)
            anomalies = analyze_for_anomalies(entries, local=True)
            hourly = get_hourly_distribution(entries, local=True)

            self.app.call_from_thread(self._update_stats, stats, anomalies, hourly, total)

        except Exception as e:
            self.app.call_from_thread(self._show_error, e)
        finally:
            self.app.call_from_thread(self.set_loading, False)

    def _show_error(self, error: Exception) -> None:
        """Report a failed API call in the view, and in the header if it was a connection."""
        self.app.note_api_error(error)
        self.set_empty_state(error_message(error))

    def _show_disconnected(self, error: str) -> None:
        """Report a failed connection in the header and the view."""
        self.app.set_connection_status("disconnected", error)
        self.set_empty_state(not_connected_message(error))

    def _update_stats(
        self, stats: dict, anomalies: list, hourly: dict[int, int], total: int | None = None
    ) -> None:
        """Update statistics display."""
        self._stats = stats
        self.set_empty_state(None)

        shown = stats.get("total_entries", 0)
        total = shown if total is None else max(total, shown)
        self.query_one("#stat-total", Static).update(f"{total:,}")
        show_sample_note(self, shown, total)

        now = datetime.now().astimezone()
        start = now - timedelta(days=DASHBOARD_DAYS)
        self.query_one("#stat-range", Static).update(f"{start:%m-%d} → {now:%m-%d}")

        top_users = stats.get("top_users", [])
        self.query_one("#stat-users", Static).update(f"{stats.get('user_count', 0):,}")

        alert_count = len(anomalies)
        self.query_one("#stat-alerts", Static).update(
            resolve_tcss_markup(f"[$warning]{alert_count}[/$warning]") if alert_count else "0"
        )

        self.query_one("#action-chart", ActionBarChart).update_data(
            stats.get("action_counts", {}), width=24
        )
        self.query_one("#hourly-chart", HourlyChart).update_data(hourly)
        # Refresh the zone name, which can change (daylight saving) in a long session.
        self.query_one("#dashboard-hourly-label", Static).update(
            f"HOURLY ACTIVITY · {local_tz_name()}"
        )

        self._top_users = list(top_users)
        self._render_top_users()

        if anomalies:
            lines = [
                resolve_tcss_markup(f"[$warning]⚠[/$warning] {anomaly['description']}")
                for anomaly in anomalies[:5]
            ]
            self.query_one("#anomalies", Static).update("\n".join(lines))
        else:
            self.query_one("#anomalies", Static).update(
                resolve_tcss_markup(
                    "[$success]✓[/$success] [$text-muted]none detected[/$text-muted]"
                )
            )

        self.query_one("#last-update", Static).update(
            f"last updated {datetime.now().strftime('%H:%M:%S')}"
        )

    def _render_top_users(self) -> None:
        """Draw the top users list to fit the column's current width."""
        if self._top_users is None:
            return
        widget = self.query_one("#top-users", Static)
        if not self._top_users:
            widget.update(no_activity_message(DASHBOARD_DAYS))
            return
        # Fit "name count" on one line: count takes 6 cells (space + 5 digits).
        name_width = max(8, min(28, widget.content_region.width - 6))
        lines = []
        for user, count in self._top_users[:8]:
            name = user if len(user) <= name_width else user[: name_width - 1] + "…"
            lines.append(f"{name:<{name_width}} {count:>5,}")
        widget.update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-button":
            self.refresh_data()
