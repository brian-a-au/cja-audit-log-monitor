"""Statistics panel widget."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ...formatters import ACTION_COLORS


class StatsPanel(Static):
    """Widget for displaying statistics summary."""

    def __init__(self, **kwargs) -> None:
        """Initialize StatsPanel."""
        super().__init__(**kwargs)
        self._stats: dict = {}

    def compose(self) -> ComposeResult:
        """Compose stats panel widgets."""
        with Vertical(classes="stats-grid"):
            yield Static(id="stats-total")
            yield Static(id="stats-date-range")
            yield Static(id="stats-actions")
            yield Static(id="stats-top-users")

    def update_stats(self, stats: dict) -> None:
        """Update displayed statistics.

        Args:
            stats: Dictionary of statistics to display.
        """
        self._stats = stats

        # Update total
        total = stats.get("total_entries", 0)
        self.query_one("#stats-total", Static).update(
            f"[bold]Total Entries:[/bold] {total:,}"
        )

        # Update date range
        date_range = stats.get("date_range")
        if date_range:
            self.query_one("#stats-date-range", Static).update(
                f"[bold]Period:[/bold] {date_range['start']} to {date_range['end']}"
            )
        else:
            self.query_one("#stats-date-range", Static).update(
                "[bold]Period:[/bold] N/A"
            )

        # Update action distribution
        actions = stats.get("action_counts", {})
        action_lines = ["[bold]Actions:[/bold]"]
        for action, count in sorted(actions.items(), key=lambda x: -x[1])[:5]:
            color = ACTION_COLORS.get(action, "white")
            action_lines.append(f"  [{color}]{action}[/{color}]: {count:,}")
        self.query_one("#stats-actions", Static).update("\n".join(action_lines))

        # Update top users
        top_users = stats.get("top_users", [])
        user_lines = ["[bold]Top Users:[/bold]"]
        for user, count in top_users[:5]:
            user_lines.append(f"  {user}: {count:,}")
        self.query_one("#stats-top-users", Static).update("\n".join(user_lines))


class ActionBarChart(Static):
    """Simple horizontal bar chart for action distribution."""

    def __init__(self, **kwargs) -> None:
        """Initialize ActionBarChart."""
        super().__init__(**kwargs)
        self._data: dict[str, int] = {}

    def update_data(self, data: dict[str, int]) -> None:
        """Update chart data.

        Args:
            data: Dictionary mapping action names to counts.
        """
        self._data = data
        self._render_chart()

    def _render_chart(self) -> None:
        """Render the bar chart."""
        if not self._data:
            self.update("[dim]No data[/dim]")
            return

        max_count = max(self._data.values()) if self._data else 1
        lines = []

        for action, count in sorted(self._data.items(), key=lambda x: -x[1]):
            color = ACTION_COLORS.get(action, "white")
            bar_width = int((count / max_count) * 30) if max_count > 0 else 0
            bar = "█" * bar_width
            pct = (count / sum(self._data.values())) * 100 if self._data else 0
            line = f"[{color}]{action:15}[/{color}] [{color}]{bar}[/{color}] {count:,} ({pct:.1f}%)"
            lines.append(line)

        self.update("\n".join(lines))


class HourlyChart(Static):
    """Simple chart for hourly distribution."""

    def __init__(self, **kwargs) -> None:
        """Initialize HourlyChart."""
        super().__init__(**kwargs)
        self._data: dict[int, int] = {}

    def update_data(self, data: dict[int, int]) -> None:
        """Update chart data.

        Args:
            data: Dictionary mapping hour (0-23) to count.
        """
        self._data = data
        self._render_chart()

    def _render_chart(self) -> None:
        """Render the hourly chart."""
        if not self._data:
            self.update("[dim]No data[/dim]")
            return

        max_count = max(self._data.values()) if self._data else 1
        lines = []

        for hour in range(24):
            count = self._data.get(hour, 0)
            bar_width = int((count / max_count) * 20) if max_count > 0 else 0
            bar = "█" * bar_width
            lines.append(f"{hour:02d}:00 │ {bar} {count}")

        self.update("\n".join(lines))
