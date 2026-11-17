"""Dashboard screen showing summary statistics."""

from collections.abc import Iterator
from datetime import datetime

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...alerts import analyze_for_anomalies
from ...formatters import resolve_tcss_markup
from ...stats import build_date_range_query, calculate_stats, get_hourly_distribution
from ..state import AppState
from ..widgets import ActionBarChart, HourlyChart
from .base import ContentView

DASHBOARD_DAYS = 7


def not_connected_message(error: str) -> str:
    """Empty-state copy shown when the API connection fails."""
    return resolve_tcss_markup(
        f"[$danger]●[/$danger] not connected · {error}\n"
        "[$text-muted]press c to open config, or run: "
        "cja-audit-log-monitor cli verify[/$text-muted]"
    )


def no_activity_message(days: int) -> str:
    """Empty-state copy shown when a time window has no entries."""
    return resolve_tcss_markup(
        f"[$text-muted]no audit activity in the last {days} days[/$text-muted]"
    )


def _stat_card(label: str, value_id: str) -> Vertical:
    return Vertical(
        Static(label, classes="stat-label"),
        Static("-", id=value_id, classes="stat-value"),
        classes="stat-card",
    )


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

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for the dashboard."""
        yield LoadingIndicator(id="loading")
        yield Static("dashboard", id="dashboard-title", classes="section-label")
        yield Horizontal(
            _stat_card("total entries", "stat-total"),
            _stat_card("active users", "stat-users"),
            _stat_card("anomalies", "stat-alerts"),
            _stat_card(f"window · last {DASHBOARD_DAYS} days", "stat-range"),
            classes="dashboard-stats",
        )
        yield Horizontal(
            Vertical(
                Static("ACTION DISTRIBUTION", classes="section-label"),
                ActionBarChart(id="action-chart"),
                Static("HOURLY ACTIVITY", classes="section-label"),
                HourlyChart(id="hourly-chart"),
                id="dash-left",
            ),
            Vertical(
                Static("TOP USERS", classes="section-label"),
                Static(id="top-users"),
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
            entries = self._state.client.get_all_logs(query, max_entries=1000)

            if worker.is_cancelled:
                return

            if not entries:
                self.app.call_from_thread(
                    self.set_empty_state, no_activity_message(DASHBOARD_DAYS)
                )
                return

            stats = calculate_stats(entries)
            anomalies = analyze_for_anomalies(entries)
            hourly = get_hourly_distribution(entries)

            self.app.call_from_thread(self._update_stats, stats, anomalies, hourly)

        except Exception as e:
            self.app.call_from_thread(self._show_disconnected, str(e))
        finally:
            self.app.call_from_thread(self.set_loading, False)

    def _show_disconnected(self, error: str) -> None:
        """Report a failed connection in the header and the view."""
        self.app.set_connection_status("disconnected", error)
        self.set_empty_state(not_connected_message(error))

    def _update_stats(self, stats: dict, anomalies: list, hourly: dict[int, int]) -> None:
        """Update statistics display."""
        self._stats = stats
        self.set_empty_state(None)

        self.query_one("#stat-total", Static).update(f"{stats.get('total_entries', 0):,}")

        date_range = stats.get("date_range")
        range_text = (
            f"{date_range['start'][5:10]} → {date_range['end'][5:10]}" if date_range else "n/a"
        )
        self.query_one("#stat-range", Static).update(range_text)

        top_users = stats.get("top_users", [])
        self.query_one("#stat-users", Static).update(str(len(top_users)))

        alert_count = len(anomalies)
        self.query_one("#stat-alerts", Static).update(
            resolve_tcss_markup(f"[$warning]{alert_count}[/$warning]") if alert_count else "0"
        )

        self.query_one("#action-chart", ActionBarChart).update_data(
            stats.get("action_counts", {}), width=24
        )
        self.query_one("#hourly-chart", HourlyChart).update_data(hourly)

        if top_users:
            name_width = 28
            lines = []
            for user, count in top_users[:8]:
                name = user if len(user) <= name_width else user[: name_width - 1] + "…"
                lines.append(f"{name:<{name_width}} {count:>5,}")
            self.query_one("#top-users", Static).update("\n".join(lines))
        else:
            self.query_one("#top-users", Static).update(no_activity_message(DASHBOARD_DAYS))

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

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-button":
            self.refresh_data()
