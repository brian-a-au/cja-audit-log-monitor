"""Custom DataTable widget for audit log entries."""

from textual.widgets import DataTable
from textual.widgets.data_table import RowKey

from ...formatters import format_timestamp
from ...models import AuditLogEntry
from ...utils import get_user_identifier


class LogTable(DataTable):
    """DataTable widget for displaying audit log entries."""

    # Map action types to CSS classes
    ACTION_STYLES = {
        "CREATE": "green",
        "DELETE": "red",
        "EDIT": "yellow",
        "EXPORT": "cyan",
        "SHARE": "blue",
        "UNSHARE": "magenta",
        "APPROVE": "green",
        "UNAPPROVE": "yellow",
        "TRANSFER": "blue",
        "EMBARGO": "red",
        "REFRESH": "cyan",
        "ORG_CHANGE": "magenta",
        "API_REQUEST": "dim",
    }

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
        self.zebra_stripes = True

    def on_mount(self) -> None:
        """Set up table columns on mount."""
        self.add_column("Timestamp", width=20, key="timestamp")
        self.add_column("User", width=25, key="user")
        self.add_column("Action", width=12, key="action")
        self.add_column("Component", width=18, key="component")
        self.add_column("Name", width=30, key="name")

        if self._show_details:
            self.add_column("Description", width=35, key="description")
            self.add_column("IP", width=15, key="ip")

    def load_entries(self, entries: list[AuditLogEntry]) -> None:
        """Load audit log entries into the table.

        Args:
            entries: List of audit log entries to display.
        """
        self.clear()
        self._entries.clear()

        for entry in entries:
            row_key = self._add_entry_row(entry)
            self._entries[row_key] = entry

    def _add_entry_row(self, entry: AuditLogEntry) -> RowKey:
        """Add a single entry row to the table.

        Args:
            entry: Audit log entry to add.

        Returns:
            Row key for the added row.
        """
        action = entry.action or "-"
        action_style = self.ACTION_STYLES.get(action, "")
        action_text = f"[{action_style}]{action}[/{action_style}]" if action_style else action

        row_data = [
            format_timestamp(entry.timestamp),
            get_user_identifier(entry, default="-"),
            action_text,
            entry.component_type or "-",
            entry.component_name or entry.component_id or "-",
        ]

        if self._show_details:
            row_data.extend([
                (entry.description or "-")[:35],
                entry.ip_address or "-",
            ])

        return self.add_row(*row_data, key=entry.id)

    def get_selected_entry(self) -> AuditLogEntry | None:
        """Get the currently selected entry.

        Returns:
            Selected AuditLogEntry or None if no selection.
        """
        if self.cursor_row is None:
            return None

        row_key = self.coordinate_to_cell_key(self.cursor_coordinate).row_key
        return self._entries.get(row_key)

    def append_entry(self, entry: AuditLogEntry) -> None:
        """Append a new entry to the top of the table.

        Args:
            entry: Audit log entry to append.
        """
        # For real-time updates, add to top
        action = entry.action or "-"
        action_style = self.ACTION_STYLES.get(action, "")
        action_text = f"[{action_style}]{action}[/{action_style}]" if action_style else action

        row_data = [
            format_timestamp(entry.timestamp),
            get_user_identifier(entry, default="-"),
            action_text,
            entry.component_type or "-",
            entry.component_name or entry.component_id or "-",
        ]

        if self._show_details:
            row_data.extend([
                (entry.description or "-")[:35],
                entry.ip_address or "-",
            ])

        # Add row at position 0 (top)
        row_key = self.add_row(*row_data, key=entry.id)
        self._entries[row_key] = entry
