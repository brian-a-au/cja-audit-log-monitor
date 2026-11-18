"""Custom DataTable widget for audit log entries."""

from rich.text import Text
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from ...formatters import format_timestamp, get_action_color, get_action_icon
from ...models import AuditLogEntry
from ...utils import get_user_identifier, local_tz_name


class LogTable(DataTable):
    """DataTable widget for displaying audit log entries.

    Fixed columns keep their preferred width; the ``name`` column takes whatever
    width is left. On narrow terminals ``user`` and ``component`` shrink first.
    """

    COLUMN_WIDTHS = {"timestamp": 19, "user": 28, "action": 13, "component": 18}
    DETAIL_WIDTHS = {"description": 35, "ip": 15}
    MIN_WIDTHS = {"user": 16, "component": 12, "name": 12}
    NAME_FLOOR = 6

    def __init__(self, show_details: bool = False, **kwargs) -> None:
        """Initialize LogTable.

        Args:
            show_details: Whether to show additional columns.
            **kwargs: Additional arguments for DataTable.
        """
        super().__init__(**kwargs)
        self._show_details = show_details
        self._entries: dict[RowKey, AuditLogEntry] = {}
        self.cursor_type = "row"
        self.zebra_stripes = False  # quieter rows; severity does the work

    def on_mount(self) -> None:
        """Set up table columns on mount."""
        labels = {"timestamp": f"time ({local_tz_name()})"}
        for key, width in self.COLUMN_WIDTHS.items():
            self.add_column(labels.get(key, key), width=width, key=key)
        self.add_column("name", width=self.MIN_WIDTHS["name"], key="name")
        if self._show_details:
            for key, width in self.DETAIL_WIDTHS.items():
                self.add_column(key, width=width, key=key)
        self._fit_columns()

    def on_resize(self) -> None:
        """Refit columns to the new width."""
        self._fit_columns()

    def _fit_columns(self) -> None:
        """Give ``name`` the remaining width; shrink user/component when space is short."""
        if "name" not in self.columns:
            return
        available = self.scrollable_content_region.width
        if available <= 0:
            return
        widths = dict(self.COLUMN_WIDTHS)
        if self._show_details:
            widths.update(self.DETAIL_WIDTHS)
        padding = 2 * self.cell_padding * (len(widths) + 1)
        free = available - padding - sum(widths.values())
        for key in ("user", "component"):
            if free >= self.MIN_WIDTHS["name"]:
                break
            take = min(widths[key] - self.MIN_WIDTHS[key], self.MIN_WIDTHS["name"] - free)
            widths[key] -= take
            free += take
        # Never scroll sideways: below the preferred minimum, name gets what's left.
        widths["name"] = max(self.NAME_FLOOR, free)
        changed = False
        for key, width in widths.items():
            column = self.columns[key]
            if column.width != width or column.auto_width:
                column.width = width
                column.auto_width = False
                changed = True
        if changed:
            self._require_update_dimensions = True
            self.refresh(layout=True)

    @staticmethod
    def _truncate(text: str, width: int) -> str:
        """Shorten ``text`` to ``width`` cells, ending with an ellipsis when cut."""
        return text if len(text) <= width else text[: width - 1] + "…"

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
        row_data = [
            format_timestamp(entry.timestamp, local=True),
            self._truncate(get_user_identifier(entry, default="-"), self.COLUMN_WIDTHS["user"]),
            self._format_action_cell(entry.action),
            entry.component_type or "-",
            entry.component_name or entry.component_id or "-",
        ]
        if self._show_details:
            row_data.extend([
                (entry.description or "-")[:35],
                entry.ip_address or "-",
            ])
        return row_data

    def load_entries(self, entries: list[AuditLogEntry]) -> None:
        """Load audit log entries into the table.

        Args:
            entries: List of audit log entries to display.
        """
        self.clear()
        self._entries.clear()
        # Refresh the zone name, which can change (daylight saving) in a long session.
        if "timestamp" in self.columns:
            self.columns["timestamp"].label = Text(f"time ({local_tz_name()})")

        for entry in entries:
            row_key = self.add_row(*self._build_row(entry), key=entry.id)
            self._entries[row_key] = entry
        # Rows may have brought in the vertical scrollbar, narrowing the table.
        self.call_after_refresh(self._fit_columns)

    def get_selected_entry(self) -> AuditLogEntry | None:
        """Get the currently selected entry."""
        if self.cursor_row is None:
            return None
        row_key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        return self._entries.get(row_key)

    def append_entry(self, entry: AuditLogEntry) -> None:
        """Append a new entry to the table (used by live monitor)."""
        row_key = self.add_row(*self._build_row(entry), key=entry.id)
        self._entries[row_key] = entry
        self.call_after_refresh(self._fit_columns)
