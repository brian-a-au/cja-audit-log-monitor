"""Chart widgets for statistics."""

from textual.css.scalar import Unit
from textual.widgets import Static

from ...formatters import ACTION_COLORS, TCSS_TOKEN_HEX, literal, render_bar

_MUTED = TCSS_TOKEN_HEX["$text-muted"]
LOADING_MARKUP = f"[{_MUTED}]loading…[/{_MUTED}]"


class ActionBarChart(Static):
    """Horizontal bar chart of action counts, colored by action severity."""

    def __init__(self, **kwargs) -> None:
        """Initialize ActionBarChart."""
        super().__init__(**kwargs)
        self._data: dict[str, int] = {}
        self._max_width = 30
        self._loading = False

    def update_data(self, data: dict[str, int], width: int = 30) -> None:
        """Update chart data.

        Args:
            data: Mapping of action name to count.
            width: Width in cells of the longest bar.
        """
        self._data = data
        self._max_width = width
        self._redraw()

    def set_loading(self, loading: bool) -> None:
        """Show "loading…" in place of the chart while a load runs."""
        self._loading = loading
        self._redraw()

    def on_resize(self) -> None:
        """Redraw so bars fit the new width."""
        self._redraw()

    def _redraw(self) -> None:
        if self._loading:
            self.update(LOADING_MARKUP)
            return
        available = self.content_region.width
        width = self._max_width
        if available > 0 and self._data:
            label_width = max(len(action) for action in self._data)
            # label, 2 spaces, bar, space, 5-digit count, 2 spaces, 5-char pct
            width = max(4, min(width, available - label_width - 15))
        self.update(self.build_markup(self._data, width))

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
                f"[{color}]{literal(f'{action:<{label_width}}')}[/{color}]  "
                f"[{color}]{bar}[/{color}] "
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
        self._loading = False

    def update_data(self, data: dict[int, int]) -> None:
        """Update chart data.

        Args:
            data: Mapping of hour (0-23) to count.
        """
        self._data = data
        self._redraw()

    def set_loading(self, loading: bool) -> None:
        """Show "loading…" in place of the chart while a load runs."""
        self._loading = loading
        self._redraw()

    def on_resize(self) -> None:
        """Redraw with narrow columns when the widget is too small for wide ones."""
        self._redraw()

    def _redraw(self) -> None:
        if self._loading:
            self.update(LOADING_MARKUP)
            return
        available = self.content_region.width
        cell = 1 if 0 < available < 48 else 2
        if self.screen.has_class("-wide"):
            # Scale bars with the column's allotted width (never with the content, which would
            # feed back into the layout).
            cell = max(cell, (available - 1) // 24)
        # A widget sized in fractions (1fr) fills its height with bar rows, minus the axis row.
        # An auto-height one keeps ROWS: its height follows its content, so reading it back
        # would feed on itself.
        height = self.styles.height
        fills = height is not None and height.unit == Unit.FRACTION
        rows = max(self.ROWS, self.content_region.height - 1) if fills else self.ROWS
        self.update(self.build_markup(self._data, cell, rows))

    @classmethod
    def build_markup(cls, data: dict[int, int], cell: int = 2, rows: int | None = None) -> str:
        """Build the chart as Rich markup: ``ROWS`` bar rows plus an axis row.

        Each hour takes ``cell`` columns: 1 (bar only), or ``cell - 1`` bar columns plus a gap.
        ``rows`` defaults to ``ROWS``.
        """
        rows = rows or cls.ROWS
        counts = [data.get(hour, 0) for hour in range(24)]
        peak = max(counts) if counts else 0
        if peak <= 0:
            return f"[{_MUTED}]no data[/{_MUTED}]"
        primary = TCSS_TOKEN_HEX["$primary"]
        heights = [count / peak * rows * 8 for count in counts]
        lines = []
        for row in range(rows - 1, -1, -1):
            cells = []
            for hour, height in enumerate(heights):
                eighths = int(min(max(height - row * 8, 0), 8))
                if eighths == 0 and row == 0 and counts[hour] > 0:
                    eighths = 1  # keep nonzero hours visible
                color = primary if counts[hour] == peak else _MUTED
                glyph = cls._LEVELS[eighths]
                bar_width = max(1, cell - 1)
                gap = " " * (cell - bar_width)
                cells.append(
                    f"[{color}]{glyph * bar_width}[/{color}]{gap}" if eighths else " " * cell
                )
            lines.append("".join(cells).rstrip())
        axis = [" "] * (24 * cell + 1)
        for hour in (0, 6, 12, 18, 23):
            start = hour * cell
            if cell == 1 and hour == 23:
                start = 22  # one cell per hour: end the label under hour 23
            axis[start : start + 2] = f"{hour:02d}"
        lines.append(f"[{_MUTED}]{''.join(axis).rstrip()}[/{_MUTED}]")
        return "\n".join(lines)
