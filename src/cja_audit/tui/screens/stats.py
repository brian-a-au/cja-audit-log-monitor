"""Statistics screen for analytics and visualizations."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
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


class StatsScreen(Screen):
    """Screen for viewing statistics and analytics."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize StatsScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(**kwargs)
        self._state = state
        self._days = 7

    def compose(self) -> ComposeResult:
        """Compose statistics screen widgets."""
        with Container(id="stats-container"):
            yield Static("[bold]Statistics & Analytics[/bold]", id="stats-title")

            with Horizontal(id="stats-controls"):
                yield Label("Days to analyze:")
                yield Input(value="7", id="days-input", type="integer")
                yield Button("Update", id="update-button", variant="primary")

            yield StatsPanel(id="stats-summary")

            with Horizontal():
                with Vertical(classes="stats-section"):
                    yield Static("[bold]Action Distribution[/bold]")
                    yield ActionBarChart(id="action-chart")

                with Vertical(classes="stats-section"):
                    yield Static("[bold]Hourly Activity[/bold]")
                    yield HourlyChart(id="hourly-chart")

            yield Static("[bold]Daily Activity[/bold]")
            yield Static(id="daily-chart")

            yield Static("[bold]User Activity Ranking[/bold]")
            yield Static(id="user-ranking")

            yield LoadingIndicator(id="loading")

    async def on_mount(self) -> None:
        """Load data when screen mounts."""
        self.query_one("#loading").display = True
        self.run_worker(self._load_data(), exclusive=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "update-button":
            try:
                self._days = int(self.query_one("#days-input", Input).value)
                if self._days < 1:
                    self._days = 1
            except ValueError:
                self._days = 7

            self.query_one("#loading").display = True
            self.run_worker(self._load_data(), exclusive=True)

    async def _load_data(self) -> None:
        """Load statistics data."""
        worker = get_current_worker()

        try:
            query = build_date_range_query(self._days)
            with self._state.client:
                entries = self._state.client.get_all_logs(query, max_entries=5000)

            if worker.is_cancelled:
                return

            # Calculate all statistics
            stats = calculate_stats(entries)
            hourly = get_hourly_distribution(entries)
            daily = get_daily_distribution(entries)
            users = get_user_activity(entries)

            self.call_from_thread(self._update_display, stats, hourly, daily, users)

        except Exception as e:
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._hide_loading)

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

    async def create_widget(self) -> Container:
        """Create widget for embedding in main content area.

        Returns:
            Container with stats content.
        """
        container = Container()
        for widget in self.compose():
            await container.mount(widget)
        # Trigger data load
        self.set_timer(0.1, lambda: self.run_worker(self._load_data(), exclusive=True))
        return container
