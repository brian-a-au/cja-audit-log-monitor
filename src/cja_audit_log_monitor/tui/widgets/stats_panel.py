"""Statistics panel widget."""

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Static

from ...formatters import ACTION_COLORS, TCSS_TOKEN_HEX, render_bar, resolve_tcss_markup

_MUTED = TCSS_TOKEN_HEX["$text-muted"]


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
        """Update displayed statistics."""
        self._stats = stats

        total = stats.get("total_entries", 0)
        self.query_one("#stats-total", Static).update(
            resolve_tcss_markup(
                f"[$text-muted]total entries[/$text-muted] [$text-strong]{total:,}[/$text-strong]"
            )
        )

        date_range = stats.get("date_range")
        if date_range:
            self.query_one("#stats-date-range", Static).update(
                resolve_tcss_markup(
                    f"[$text-muted]period[/$text-muted] "
                    f"[$text-strong]{date_range['start']}[/$text-strong] to "
                    f"[$text-strong]{date_range['end']}[/$text-strong]"
                )
            )
        else:
            self.query_one("#stats-date-range", Static).update(
                resolve_tcss_markup(
                    "[$text-muted]period[/$text-muted] [$text-muted]N/A[/$text-muted]"
                )
            )

        actions = stats.get("action_counts", {})
        action_lines = [resolve_tcss_markup("[$text-muted]actions[/$text-muted]")]
        for action, count in sorted(actions.items(), key=lambda x: -x[1])[:5]:
            token = ACTION_COLORS.get(action, "$text-muted")
            color = TCSS_TOKEN_HEX.get(token, token)
            action_lines.append(f"  [{color}]{action}[/{color}]: {count:,}")
        self.query_one("#stats-actions", Static).update("\n".join(action_lines))

        top_users = stats.get("top_users", [])
        user_lines = [resolve_tcss_markup("[$text-muted]top users[/$text-muted]")]
        for user, count in top_users[:5]:
            user_lines.append(f"  {user}: {count:,}")
        self.query_one("#stats-top-users", Static).update("\n".join(user_lines))


class ActionBarChart(Static):
    """Horizontal bar chart of action counts, colored by action severity."""

    def __init__(self, **kwargs) -> None:
        """Initialize ActionBarChart."""
        super().__init__(**kwargs)
        self._data: dict[str, int] = {}

    def update_data(self, data: dict[str, int], width: int = 30) -> None:
        """Update chart data.

        Args:
            data: Mapping of action name to count.
            width: Width in cells of the longest bar.
        """
        self._data = data
        self.update(self.build_markup(data, width))

    @staticmethod
    def build_markup(data: dict[str, int], width: int = 30) -> str:
        """Build the chart as Rich markup (one line per action, largest first)."""
        if not data:
            return f"[{_MUTED}]no data[/{_MUTED}]"
        total = sum(data.values())
        max_count = max(data.values())
        label_width = max(len(action) for action in data)
        lines = []
        for action, count in sorted(data.items(), key=lambda x: -x[1]):
            color = TCSS_TOKEN_HEX.get(ACTION_COLORS.get(action, "$text-muted"), _MUTED)
            bar = render_bar(count, max_count, width).ljust(width)
            pct = count / total * 100 if total else 0
            lines.append(
                f"[{color}]{action:<{label_width}}[/{color}]  [{color}]{bar}[/{color}] "
                f"{count:>5,}  [{_MUTED}]{pct:4.1f}%[/{_MUTED}]"
            )
        return "\n".join(lines)


class HourlyChart(Static):
    """24-hour column chart, six rows tall, with an hour axis beneath."""

    ROWS = 6
    _LEVELS = " ▁▂▃▄▅▆▇█"

    def __init__(self, **kwargs) -> None:
        """Initialize HourlyChart."""
        super().__init__(**kwargs)
        self._data: dict[int, int] = {}

    def update_data(self, data: dict[int, int]) -> None:
        """Update chart data.

        Args:
            data: Mapping of hour (0-23) to count.
        """
        self._data = data
        self.update(self.build_markup(data))

    @classmethod
    def build_markup(cls, data: dict[int, int]) -> str:
        """Build the chart as Rich markup: ``ROWS`` bar rows plus an axis row."""
        counts = [data.get(hour, 0) for hour in range(24)]
        peak = max(counts) if counts else 0
        if peak <= 0:
            return f"[{_MUTED}]no data[/{_MUTED}]"
        primary = TCSS_TOKEN_HEX["$primary"]
        heights = [count / peak * cls.ROWS * 8 for count in counts]
        lines = []
        for row in range(cls.ROWS - 1, -1, -1):
            cells = []
            for hour, height in enumerate(heights):
                eighths = int(min(max(height - row * 8, 0), 8))
                if eighths == 0 and row == 0 and counts[hour] > 0:
                    eighths = 1  # keep nonzero hours visible
                color = primary if counts[hour] == peak else _MUTED
                glyph = cls._LEVELS[eighths]
                cells.append(f"[{color}]{glyph}[/{color}] " if eighths else "  ")
            lines.append("".join(cells).rstrip())
        axis = [" "] * 48
        for hour in (0, 6, 12, 18, 23):
            axis[hour * 2 : hour * 2 + 2] = f"{hour:02d}"
        lines.append(f"[{_MUTED}]{''.join(axis).rstrip()}[/{_MUTED}]")
        return "\n".join(lines)
