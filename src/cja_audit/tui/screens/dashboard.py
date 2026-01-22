"""Dashboard screen showing summary statistics."""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...alerts import analyze_for_anomalies
from ...formatters import ACTION_COLORS
from ...stats import build_date_range_query, calculate_stats
from ..state import AppState


class DashboardScreen(Screen):
    """Dashboard screen with summary view."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize DashboardScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(**kwargs)
        self._state = state
        self._stats: dict = {}

    def compose(self) -> ComposeResult:
        """Compose dashboard widgets."""
        with Container(id="dashboard-container"):
            yield Static("[bold]Dashboard[/bold]", id="dashboard-title")
            yield Static(id="connection-status")

            with Horizontal(classes="dashboard-stats"):
                with Vertical(classes="stat-card"):
                    yield Static("Total Entries", classes="stat-label")
                    yield Static("-", id="stat-total", classes="stat-value")

                with Vertical(classes="stat-card"):
                    yield Static("Date Range", classes="stat-label")
                    yield Static("-", id="stat-range", classes="stat-value")

                with Vertical(classes="stat-card"):
                    yield Static("Active Users", classes="stat-label")
                    yield Static("-", id="stat-users", classes="stat-value")

                with Vertical(classes="stat-card"):
                    yield Static("Recent Alerts", classes="stat-label")
                    yield Static("-", id="stat-alerts", classes="stat-value")

            yield Static("[bold]Action Distribution[/bold]")
            yield Static(id="action-chart", classes="bar-chart")

            yield Static("[bold]Top 5 Active Users (Last 7 Days)[/bold]")
            yield Static(id="top-users")

            yield Static("[bold]Recent Anomalies[/bold]")
            yield Static(id="anomalies")

            yield Horizontal(
                Button("Refresh", id="refresh-button", variant="primary"),
                Static(id="last-update"),
            )

            yield LoadingIndicator(id="loading")

    async def on_mount(self) -> None:
        """Load data when screen mounts."""
        self.query_one("#loading").display = True
        self.run_worker(self._load_data(), exclusive=True)

    async def _load_data(self) -> None:
        """Load dashboard data."""
        worker = get_current_worker()

        try:
            # Verify connection first
            result = await self._state.verify_connection()

            if worker.is_cancelled:
                return

            if result.get("connected"):
                self.call_from_thread(
                    self._update_connection_status,
                    True,
                    result.get("org_id", "Unknown"),
                )
            else:
                self.call_from_thread(
                    self._update_connection_status,
                    False,
                    result.get("error", "Connection failed"),
                )
                return

            # Fetch last 7 days of data
            query = build_date_range_query(7)
            with self._state.client:
                entries = self._state.client.get_all_logs(query, max_entries=1000)

            if worker.is_cancelled:
                return

            # Calculate stats
            stats = calculate_stats(entries)
            anomalies = analyze_for_anomalies(entries)

            # Update UI from worker
            self.call_from_thread(self._update_stats, stats, anomalies, len(entries))

        except Exception as e:
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._hide_loading)

    def _update_connection_status(self, connected: bool, info: str) -> None:
        """Update connection status display."""
        status = self.query_one("#connection-status", Static)
        if connected:
            status.update(f"[green]● Connected[/green] - {info}")
        else:
            status.update(f"[red]● Disconnected[/red] - {info}")

    def _update_stats(self, stats: dict, anomalies: list, entry_count: int) -> None:
        """Update statistics display."""
        self._stats = stats

        # Update stat cards
        self.query_one("#stat-total", Static).update(f"{stats.get('total_entries', 0):,}")

        date_range = stats.get("date_range")
        if date_range:
            self.query_one("#stat-range", Static).update(
                f"{date_range['start'][:10]} to {date_range['end'][:10]}"
            )
        else:
            self.query_one("#stat-range", Static).update("N/A")

        top_users = stats.get("top_users", [])
        self.query_one("#stat-users", Static).update(str(len(top_users)))

        alert_count = len(anomalies)
        self.query_one("#stat-alerts", Static).update(
            f"[yellow]{alert_count}[/yellow]" if alert_count > 0 else "0"
        )

        # Update action chart
        actions = stats.get("action_counts", {})
        if actions:
            max_count = max(actions.values()) if actions else 1
            chart_lines = []
            for action, count in sorted(actions.items(), key=lambda x: -x[1])[:8]:
                color = ACTION_COLORS.get(action, "white")
                bar_width = int((count / max_count) * 30)
                bar = "█" * bar_width
                chart_lines.append(f"[{color}]{action:15}[/{color}] {bar} {count:,}")
            self.query_one("#action-chart", Static).update("\n".join(chart_lines))
        else:
            self.query_one("#action-chart", Static).update("[dim]No data[/dim]")

        # Update top users
        if top_users:
            user_lines = []
            for i, (user, count) in enumerate(top_users[:5], 1):
                user_lines.append(f"  {i}. {user}: {count:,} actions")
            self.query_one("#top-users", Static).update("\n".join(user_lines))
        else:
            self.query_one("#top-users", Static).update("[dim]No data[/dim]")

        # Update anomalies
        if anomalies:
            anomaly_lines = []
            for anomaly in anomalies[:5]:
                anomaly_lines.append(f"  [yellow]⚠[/yellow] {anomaly['description']}")
            self.query_one("#anomalies", Static).update("\n".join(anomaly_lines))
        else:
            self.query_one("#anomalies", Static).update("[dim]No anomalies detected[/dim]")

        # Update last refresh time
        self.query_one("#last-update", Static).update(
            f"[dim]Last updated: {datetime.now().strftime('%H:%M:%S')}[/dim]"
        )

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.query_one("#connection-status", Static).update(f"[red]Error: {error}[/red]")

    def _hide_loading(self) -> None:
        """Hide loading indicator."""
        self.query_one("#loading").display = False

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "refresh-button":
            self.query_one("#loading").display = True
            self.run_worker(self._load_data(), exclusive=True)

    async def create_widget(self) -> Container:
        """Create widget for embedding in main content area.

        Returns:
            Container with dashboard content.
        """
        container = Container()
        for widget in self.compose():
            await container.mount(widget)
        # Trigger data load
        self.set_timer(0.1, lambda: self.run_worker(self._load_data(), exclusive=True))
        return container
