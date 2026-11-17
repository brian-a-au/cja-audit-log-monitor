"""Statistics screen for analytics and visualizations."""

from collections.abc import Iterator

from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...stats import (
    build_date_range_query,
    calculate_stats,
    get_daily_distribution,
    get_hourly_distribution,
    get_user_activity,
)
from ..state import AppState
from ..widgets import ActionBarChart, HourlyChart, StatsPanel
from .base import ContentView


class StatsScreen(ContentView):
    """Screen for viewing statistics and analytics."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize StatsScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(state, **kwargs)
        self._days = 7

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the stats content.
        """
        controls = Horizontal(
            Label("days"),
            Input(value="7", id="days-input", type="integer", compact=True),
            Button("update", id="update-button", variant="primary", compact=True),
            id="stats-controls",
            classes="toolbar",
        )

        action_section = Vertical(
            Static("ACTION DISTRIBUTION", classes="section-label"),
            ActionBarChart(id="action-chart"),
            classes="stats-section",
        )

        hourly_section = Vertical(
            Static("HOURLY ACTIVITY", classes="section-label"),
            HourlyChart(id="hourly-chart"),
            classes="stats-section",
        )

        charts_row = Horizontal(action_section, hourly_section)

        yield Container(
            Static("statistics", id="stats-title", classes="section-label"),
            controls,
            StatsPanel(id="stats-summary"),
            charts_row,
            Static("DAILY ACTIVITY", classes="section-label"),
            Static(id="daily-chart"),
            Static("USER ACTIVITY RANKING", classes="section-label"),
            Static(id="user-ranking"),
            LoadingIndicator(id="loading"),
            id="stats-container",
        )

    def on_content_mounted(self) -> None:
        """Called after compose_content widgets are mounted."""
        self.run_worker(self._load_data(), exclusive=True, thread=True)

    def refresh_data(self) -> None:
        """Refresh statistics data."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.run_worker(self._load_data(), exclusive=True, thread=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "update-button":
            try:
                self._days = int(self.query_one("#days-input", Input).value)
                if self._days < 1:
                    self._days = 1
            except ValueError:
                self._days = 7

            self.refresh_data()

    async def _load_data(self) -> None:
        """Load statistics data."""
        worker = get_current_worker()

        try:
            query = build_date_range_query(self._days)
            entries = self._state.client.get_all_logs(query, max_entries=5000)

            if worker.is_cancelled:
                return

            # Calculate all statistics
            stats = calculate_stats(entries)
            hourly = get_hourly_distribution(entries)
            daily = get_daily_distribution(entries)
            users = get_user_activity(entries)

            self.app.call_from_thread(self._update_display, stats, hourly, daily, users)

        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
        finally:
            self.app.call_from_thread(self._hide_loading)

    def _update_display(
        self,
        stats: dict,
        hourly: dict,
        daily: dict,
        users: list,
    ) -> None:
        """Update all statistics displays."""
        # Update summary panel
        stats_panel = self.query_one("#stats-summary", StatsPanel)
        stats_panel.update_stats(stats)

        # Update action chart
        action_chart = self.query_one("#action-chart", ActionBarChart)
        action_chart.update_data(stats.get("action_counts", {}))

        # Update hourly chart
        hourly_chart = self.query_one("#hourly-chart", HourlyChart)
        hourly_chart.update_data(hourly)

        # Update daily chart
        if daily:
            max_daily = max(daily.values()) if daily else 1
            daily_lines = []
            for date, count in sorted(daily.items())[-14:]:  # Last 14 days
                bar_width = int((count / max_daily) * 30) if max_daily > 0 else 0
                bar = "█" * bar_width
                daily_lines.append(f"  {date} │ {bar} {count}")
            self.query_one("#daily-chart", Static).update("\n".join(daily_lines))
        else:
            self.query_one("#daily-chart", Static).update("[dim]No data[/dim]")

        # Update user ranking
        if users:
            user_lines = []
            for i, (user, count) in enumerate(users[:10], 1):
                user_lines.append(f"  {i:2}. {user[:40]:40} {count:,} actions")
            self.query_one("#user-ranking", Static).update("\n".join(user_lines))
        else:
            self.query_one("#user-ranking", Static).update("[dim]No data[/dim]")

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.app.notify(f"Error: {error}", severity="error")

    def _hide_loading(self) -> None:
        """Hide loading indicator."""
        self.query_one("#loading").display = False
