"""Chart widgets for statistics."""

from textual.widgets import Static

from ...formatters import ACTION_COLORS, TCSS_TOKEN_HEX, render_bar

_MUTED = TCSS_TOKEN_HEX["$text-muted"]


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
