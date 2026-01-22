"""Entry detail modal for viewing full audit log entry details."""

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Static

from ...formatters import ACTION_COLORS, format_timestamp
from ...models import AuditLogEntry
from ...utils import get_user_identifier


class EntryDetailModal(ModalScreen):
    """Modal screen for displaying audit log entry details."""

    BINDINGS = [
        ("escape", "dismiss", "Close"),
    ]

    def __init__(self, entry: AuditLogEntry, **kwargs) -> None:
        """Initialize EntryDetailModal.

        Args:
            entry: Audit log entry to display.
            **kwargs: Additional arguments for ModalScreen.
        """
        super().__init__(**kwargs)
        self._entry = entry

    def compose(self) -> ComposeResult:
        """Compose modal content."""
        entry = self._entry
        action = entry.action or "-"
        action_color = ACTION_COLORS.get(action, "white")

        with Vertical():
            yield Static(
                f"[bold {action_color}]{action}[/bold {action_color}] - "
                f"{entry.component_type or 'Unknown'}",
                classes="modal-title",
            )

            yield Horizontal(
                Static("[bold]ID:[/bold]", classes="detail-label"),
                Static(entry.id or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Timestamp:[/bold]", classes="detail-label"),
                Static(format_timestamp(entry.timestamp), classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]User:[/bold]", classes="detail-label"),
                Static(get_user_identifier(entry, default="-"), classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]User ID:[/bold]", classes="detail-label"),
                Static(entry.user_id or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]User Email:[/bold]", classes="detail-label"),
                Static(entry.user_email or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Action:[/bold]", classes="detail-label"),
                Static(f"[{action_color}]{action}[/{action_color}]", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Component:[/bold]", classes="detail-label"),
                Static(entry.component_type or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Component ID:[/bold]", classes="detail-label"),
                Static(entry.component_id or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Component Name:[/bold]", classes="detail-label"),
                Static(entry.component_name or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Description:[/bold]", classes="detail-label"),
                Static(entry.description or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]IP Address:[/bold]", classes="detail-label"),
                Static(entry.ip_address or "-", classes="detail-value"),
                classes="detail-row",
            )

            yield Horizontal(
                Static("[bold]Org ID:[/bold]", classes="detail-label"),
                Static(entry.org_id or "-", classes="detail-value"),
                classes="detail-row",
            )

            if entry.changes:
                yield Static("[bold]Changes:[/bold]", classes="detail-label")
                import json
                changes_str = json.dumps(entry.changes, indent=2, default=str)
                yield Static(changes_str, classes="detail-changes")

            yield Horizontal(
                Button("Close", id="close-modal", variant="primary"),
                classes="modal-buttons",
            )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "close-modal":
            self.dismiss()
