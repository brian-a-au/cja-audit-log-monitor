"""Entry detail side panel — slides in next to the log table."""

import json

from rich.console import Group, RenderableType
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Static

from ...formatters import (
    TCSS_TOKEN_HEX,
    format_timestamp,
    get_action_color,
    get_action_icon,
    literal,
    resolve_tcss_markup,
)
from ...models import AuditLogEntry
from ...utils import get_user_identifier, local_tz_name

LABEL_WIDTH = 14


def build_detail_table(entry: AuditLogEntry) -> Table:
    """Every field of ``entry`` as a two-column grid.

    Long values wrap inside the value column (and long ids break mid-word)
    instead of running back under the labels.
    """
    action = entry.action or "-"
    color = get_action_color(action)
    rows = [
        ("id", entry.id or "-"),
        ("timestamp", f"{format_timestamp(entry.timestamp, local=True)} {local_tz_name()}"),
        ("user", get_user_identifier(entry, default="-")),
        ("user id", entry.user_id or "-"),
        ("user email", entry.user_email or "-"),
        ("user name", entry.user_name or "-"),
        ("action", Text(action, style=color)),
        ("component", entry.component_type or "-"),
        ("component id", entry.component_id or "-"),
        ("component name", entry.component_name or "-"),
        ("description", entry.description or "-"),
        ("ip address", entry.ip_address or "-"),
        ("org id", entry.org_id or "-"),
    ]
    muted = TCSS_TOKEN_HEX["$text-muted"]
    table = Table.grid(padding=(0, 1))
    table.add_column(width=LABEL_WIDTH, no_wrap=True, style=muted)
    table.add_column(ratio=1, overflow="fold")
    for label, value in rows:
        table.add_row(label, value if isinstance(value, Text) else Text(value))
    return table


class EntryDetailPanel(VerticalScroll):
    """Side panel that displays a single audit log entry's details.

    Focusable, so the keyboard can scroll a long entry. Hidden by default.
    Toggle visibility via the `hidden` class.
    Mount inside a horizontal container next to the log table.
    """

    def __init__(self, **kwargs) -> None:
        """Initialize EntryDetailPanel."""
        kwargs.setdefault("id", "entry-detail-panel")
        super().__init__(**kwargs)
        self._entry: AuditLogEntry | None = None
        self.add_class("hidden")

    def compose(self) -> ComposeResult:
        """Compose the (initially empty) panel layout."""
        yield Static("", id="detail-title", classes="modal-title")
        yield Static("", id="detail-body")

    def show_entry(self, entry: AuditLogEntry) -> None:
        """Display the given entry and reveal the panel."""
        self._entry = entry
        self._render_entry()
        self.remove_class("hidden")

    def hide(self) -> None:
        """Hide the panel without clearing the entry."""
        self.add_class("hidden")

    def is_visible(self) -> bool:
        """Return True if the panel is currently visible."""
        return "hidden" not in self.classes

    def toggle(self, entry: AuditLogEntry | None = None) -> None:
        """Show with the given entry, or hide if already showing the same entry."""
        if entry is not None:
            same = self._entry is not None and self._entry.id == entry.id
            if self.is_visible() and same:
                self.hide()
                return
            self.show_entry(entry)
        else:
            if self.is_visible():
                self.hide()

    def _render_entry(self) -> None:
        """Render the current entry into the panel body."""
        entry = self._entry
        if entry is None:
            return

        action = entry.action or "-"
        color = get_action_color(action)
        icon = get_action_icon(action)

        title = self.query_one("#detail-title", Static)
        title.update(
            resolve_tcss_markup(
                f"[{color}]{literal(f'{icon} {action}')}[/{color}] · "
                f"[$text-muted]{literal(entry.component_type or 'unknown')}[/$text-muted]"
            )
        )

        body: RenderableType = build_detail_table(entry)
        if entry.changes:
            muted = TCSS_TOKEN_HEX["$text-muted"]
            body = Group(
                body,
                Text(""),
                Text("changes", style=muted),
                Text(json.dumps(entry.changes, indent=2, default=str)),
            )
        self.query_one("#detail-body", Static).update(body)
