"""Custom DataTable widget for audit log entries."""

from datetime import UTC, datetime

from rich.text import Text
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from ...formatters import cut_cells, format_timestamp, get_action_color, get_action_icon
from ...models import AuditLogEntry
from ...utils import entry_key, get_user_identifier, local_tz_name

# Sort key for an entry with no timestamp: it goes before every timed entry.
_NO_TIME = datetime.min.replace(tzinfo=UTC)


class LogTable(DataTable):
    """DataTable widget for displaying audit log entries.

    Fixed columns keep their preferred width; the ``name`` column takes whatever
    width is left. On narrow terminals ``user`` and ``component`` shrink first.
    """

    COLUMN_WIDTHS = {"timestamp": 19, "user": 28, "action": 13, "component": 18}
    # Narrowest each column may get before it is shrunk or hidden. ``name`` is hidden first,
    # then ``component`` (the type); the other columns always stay.
    MIN_WIDTHS = {"timestamp": 19, "user": 16, "action": 13, "component": 12, "name": 12}
    HIDE_ORDER = ("name", "component")
    # The narrowest the name column gets once every other column has its minimum.
    NAME_FLOOR = 6

    def __init__(self, **kwargs) -> None:
        """Initialize LogTable.

        Args:
            **kwargs: Additional arguments for DataTable.
        """
        super().__init__(**kwargs)
        self._entries: dict[RowKey, AuditLogEntry] = {}
        self._shown: list[str] = []  # keys of the columns currently in the table
        self.cursor_type = "row"
        self.zebra_stripes = False  # quieter rows; severity does the work

    def _all_columns(self) -> list[str]:
        return [*self.COLUMN_WIDTHS, "name"]

    def _add_columns(self, widths: dict[str, int]) -> None:
        labels = {"timestamp": f"time ({local_tz_name()})"}
        for key, width in widths.items():
            self.add_column(labels.get(key, key), width=width, key=key)
        self._shown = list(widths)

    def on_mount(self) -> None:
        """Set up table columns on mount."""
        widths = {**self.COLUMN_WIDTHS, "name": self.MIN_WIDTHS["name"]}
        self._add_columns(widths)
        self._fit_columns()

    def on_resize(self) -> None:
        """Refit columns to the new width."""
        self._fit_columns()

    def _visible_columns(self, available: int) -> list[str]:
        """Column keys that fit in ``available`` cells at their minimum widths."""
        keys = self._all_columns()
        minimum = {**self.COLUMN_WIDTHS, **self.MIN_WIDTHS}

        def needed() -> int:
            return sum(minimum[k] + 2 * self.cell_padding for k in keys)

        for hidden in self.HIDE_ORDER:
            if needed() <= available:
                break
            keys.remove(hidden)
        return keys

    def _fit_columns(self) -> None:
        """Hide columns that cannot fit, then give ``name`` the remaining width.

        ``user`` and ``component`` shrink toward their minimum before ``name`` does.
        Never scrolls sideways: the widths always add up to the available width.
        """
        if not self._shown:
            return  # not mounted yet
        available = self.scrollable_content_region.width
        if available <= 0:
            return
        keys = self._visible_columns(available)
        widths = {k: self.COLUMN_WIDTHS.get(k, 0) for k in keys}
        padding = 2 * self.cell_padding * len(keys)
        free = available - padding - sum(widths.values())
        # Shrink user, then component, until ``name`` has its minimum (or nothing is left over).
        target = self.MIN_WIDTHS["name"] if "name" in keys else 0
        for key in ("user", "component"):
            if key in keys and free < target:
                take = min(widths[key] - self.MIN_WIDTHS[key], target - free)
                widths[key] -= take
                free += take
        if "name" in keys:
            widths["name"] = max(self.NAME_FLOOR, free)
        current = {k: self.columns[k].width for k in self._shown if k in self.columns}
        if keys != self._shown or current != widths:
            self._rebuild(widths)

    def _rebuild(self, widths: dict[str, int]) -> None:
        """Recreate the columns and rows at ``widths``, keeping entries and the cursor row."""
        rows = [(key.value, entry) for key, entry in self._entries.items()]
        cursor = self.cursor_row
        DataTable.clear(self, columns=True)
        self._entries = {}
        self._add_columns(widths)
        for key, entry in rows:
            self._entries[self.add_row(*self._build_row(entry), key=key)] = entry
        if rows:
            self.move_cursor(row=min(cursor, len(rows) - 1), animate=False)
        self.refresh(layout=True)

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        """Shorten ``text`` to ``width`` cells (not characters), ending with an ellipsis if cut.

        Works on the plain string, so square brackets in the text are never markup.
        """
        return cut_cells(text, width)

    def _width_of(self, key: str) -> int:
        """Current width of column ``key``, or its preferred width before the table is laid out."""
        if key in self.columns:
            return self.columns[key].width
        return self.COLUMN_WIDTHS.get(key, self.MIN_WIDTHS.get(key, 0))

    def _format_action_cell(self, action: str | None) -> Text:
        """Render `<icon> <action>` with the severity color as a Rich Text object.

        Returns a ``rich.text.Text`` so the DataTable bypasses ``Text.from_markup``
        and never chokes on markup tokens. ``get_action_color`` returns a hex value
        that both Rich and Textual understand natively.
        """
        action_str = action or "-"
        color = get_action_color(action_str)
        icon = get_action_icon(action_str)
        text = Text(no_wrap=True)
        text.append(f"{icon} {action_str}", style=color)
        return text

    def _build_row(self, entry: AuditLogEntry) -> list:
        """Cells for ``entry``, only for the columns currently shown."""
        cells = {
            "timestamp": Text(format_timestamp(entry.timestamp, local=True), no_wrap=True),
            "user": Text(
                self._truncate(get_user_identifier(entry, default="-"), self._width_of("user")),
                no_wrap=True,
            ),
            "action": self._format_action_cell(entry.action),
            "component": Text(
                self._truncate(entry.component_type or "-", self._width_of("component")),
                no_wrap=True,
            ),
            "name": Text(
                self._truncate(
                    entry.component_name or entry.component_id or "-", self._width_of("name")
                ),
                no_wrap=True,
            ),
        }
        return [cells[key] for key in (self._shown or self._all_columns())]

    def clear(self, columns: bool = False) -> "LogTable":
        """Remove all rows (and the entries behind them)."""
        self._entries.clear()
        return super().clear(columns)

    def load_entries(self, entries: list[AuditLogEntry]) -> None:
        """Load audit log entries into the table; the cursor stays on the same entry.

        Args:
            entries: List of audit log entries to display.
        """
        selected = self.get_selected_entry() if self.row_count else None
        keep = entry_key(selected) if selected is not None else None
        self.clear()
        # Refresh the zone name, which can change (daylight saving) in a long session.
        if "timestamp" in self.columns:
            self.columns["timestamp"].label = Text(f"time ({local_tz_name()})")

        used: dict[str, int] = {}
        cursor_row = 0
        for index, entry in enumerate(entries):
            row_key = self.add_row(*self._build_row(entry), key=_unique_key(entry.id, used))
            self._entries[row_key] = entry
            if keep is not None and entry_key(entry) == keep:
                cursor_row = index
        if cursor_row:
            self.move_cursor(row=cursor_row)
        # Rows may have brought in the vertical scrollbar, narrowing the table.
        self.call_after_refresh(self._fit_columns)

    def get_selected_entry(self) -> AuditLogEntry | None:
        """Get the currently selected entry."""
        if self.cursor_row is None:
            return None
        row_key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        return self._entries.get(row_key)

    def append_entries(self, entries: list[AuditLogEntry], max_rows: int) -> None:
        """Add entries at the bottom, oldest first, keeping at most ``max_rows`` rows.

        Used by the live monitor. Entries already in the table are skipped and the oldest
        rows are dropped past ``max_rows``. If the cursor was on the last row (or the table
        was empty), it moves to the new last row, so the view follows the stream.
        """
        following = self.row_count == 0 or self.cursor_row == self.row_count - 1
        added = False
        for entry in sorted(entries, key=lambda e: e.timestamp or _NO_TIME):
            key = entry_key(entry)
            if key in self.rows:
                continue
            row_key = self.add_row(*self._build_row(entry), key=key)
            self._entries[row_key] = entry
            added = True
        if not added:
            return
        removed = 0
        while self.row_count > max_rows:
            oldest = next(iter(self._entries))
            del self._entries[oldest]
            self.remove_row(oldest)
            removed += 1
        if following:
            self.move_cursor(row=self.row_count - 1)
        elif removed:
            # Keep the cursor on the same entry while older rows go away above it.
            self.move_cursor(row=max(0, self.cursor_row - removed))
        # Rows may have brought in the vertical scrollbar, narrowing the table.
        self.call_after_refresh(self._fit_columns)


def _unique_key(entry_id: str | None, used: dict[str, int]) -> str | None:
    """A row key from the entry id: the id itself the first time, ``<id>~<n>`` after that.

    The API can repeat an id; a repeated row key would fail the whole page.
    """
    if entry_id is None:
        return None
    seen = used.get(entry_id, 0)
    used[entry_id] = seen + 1
    return entry_id if seen == 0 else f"{entry_id}~{seen}"
