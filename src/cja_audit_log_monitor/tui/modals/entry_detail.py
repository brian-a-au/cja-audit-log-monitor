"""Entry detail side panel — slides in next to the log table."""

import json

from textual.app import ComposeResult
from textual.containers import Container
from textual.widgets import Static

from ...formatters import format_timestamp, get_action_color, get_action_icon, resolve_tcss_markup
from ...models import AuditLogEntry
from ...utils import get_user_identifier, local_tz_name


class EntryDetailPanel(Container):
    """Side panel that displays a single audit log entry's details.

    Hidden by default. Toggle visibility via the `hidden` class.
    Mount inside a horizontal container next to the log table.
    """

    DEFAULT_ID = "entry-detail-panel"

    def __init__(self, **kwargs) -> None:
        """Initialize EntryDetailPanel."""
        kwargs.setdefault("id", self.DEFAULT_ID)
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
                f"[{color}]{icon} {action}[/{color}] · "
                f"[$text-muted]{entry.component_type or 'unknown'}[/$text-muted]"
            )
        )

        body_lines = [
            self._row("id", entry.id or "-"),
            self._row(
                "timestamp", f"{format_timestamp(entry.timestamp, local=True)} {local_tz_name()}"
            ),
            self._row("user", get_user_identifier(entry, default="-")),
            self._row("user id", entry.user_id or "-"),
            self._row("user email", entry.user_email or "-"),
            self._row("user name", entry.user_name or "-"),
            self._row("action", f"[{color}]{action}[/{color}]"),
            self._row("component", entry.component_type or "-"),
            self._row("component id", entry.component_id or "-"),
            self._row("component name", entry.component_name or "-"),
            self._row("description", entry.description or "-"),
            self._row("ip address", entry.ip_address or "-"),
            self._row("org id", entry.org_id or "-"),
        ]
        if entry.changes:
            body_lines.append("")
            body_lines.append("[$text-muted]changes[/$text-muted]")
            body_lines.append(json.dumps(entry.changes, indent=2, default=str))

        self.query_one("#detail-body", Static).update(
            resolve_tcss_markup("\n".join(body_lines))
        )

    @staticmethod
    def _row(label: str, value: str) -> str:
        return f"[$text-muted]{label:<14}[/$text-muted] {value}"

