"""Custom DataTable widget for audit log entries."""

from rich.text import Text
from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from ...formatters import format_timestamp, get_action_color, get_action_icon
from ...models import AuditLogEntry
from ...utils import get_user_identifier


class LogTable(DataTable):
    """DataTable widget for displaying audit log entries."""

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
        self.add_column("timestamp", width=20, key="timestamp")
        self.add_column("user", width=25, key="user")
        self.add_column("action", width=14, key="action")
        self.add_column("component", width=18, key="component")
        self.add_column("name", width=30, key="name")

        if self._show_details:
            self.add_column("description", width=35, key="description")
            self.add_column("ip", width=15, key="ip")

    # Map Textual CSS design tokens → Rich-compatible hex colors (from styles.tcss).
    _TOKEN_TO_HEX: dict[str, str] = {
        "$success": "#7fc896",
        "$warning": "#e8c547",
        "$danger": "#e07a7a",
        "$text-muted": "#6e7480",
    }

    def _format_action_cell(self, action: str | None) -> Text:
        """Render `<icon> <action>` with the severity color as a Rich Text object.

        Returns a ``rich.text.Text`` so the DataTable bypasses ``Text.from_markup``
        and never chokes on Textual CSS variable tokens (e.g. ``$success``).
        """
        action_str = action or "-"
        token = get_action_color(action_str)
        icon = get_action_icon(action_str)
        rich_color = self._TOKEN_TO_HEX.get(token, "#6e7480")
        text = Text(no_wrap=True)
        text.append(f"{icon} {action_str}", style=rich_color)
        return text

    def _build_row(self, entry: AuditLogEntry) -> list:
        row_data = [
            format_timestamp(entry.timestamp),
            get_user_identifier(entry, default="-"),
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

        for entry in entries:
            row_key = self.add_row(*self._build_row(entry), key=entry.id)
            self._entries[row_key] = entry

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
