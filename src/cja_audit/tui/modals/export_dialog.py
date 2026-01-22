"""Export dialog modal for exporting audit logs."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static

from ...export import export_entries
from ..state import AppState


class ExportDialog(ModalScreen):
    """Modal dialog for exporting audit log data."""

    BINDINGS = [
        ("escape", "dismiss", "Cancel"),
    ]

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize ExportDialog.

        Args:
            state: Application state containing entries to export.
            **kwargs: Additional arguments for ModalScreen.
        """
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        """Compose dialog content."""
        with Vertical():
            yield Static("[bold]Export Audit Logs[/bold]", classes="modal-title")

            yield Label(f"Entries to export: {len(self._state.entries)}")

            yield Static("\n[bold]Format:[/bold]")
            with RadioSet(id="format-select"):
                yield RadioButton("JSON", value=True, id="format-json")
                yield RadioButton("CSV", id="format-csv")
                yield RadioButton("TSV", id="format-tsv")

            yield Static("\n[bold]Output File:[/bold]")
            yield Input(
                placeholder="Enter file path...",
                value="audit_logs_export.json",
                id="output-path",
            )

            yield Horizontal(
                Button("Export", id="export-button", variant="primary"),
                Button("Cancel", id="cancel-button"),
                classes="modal-buttons",
            )

            yield Static("", id="export-status")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Update file extension when format changes."""
        button_id = event.pressed.id
        if button_id:
            format_map = {
                "format-json": ".json",
                "format-csv": ".csv",
                "format-tsv": ".tsv",
            }
            ext = format_map.get(button_id, ".json")

            path_input = self.query_one("#output-path", Input)
            current_path = Path(path_input.value)
            new_path = current_path.with_suffix(ext)
            path_input.value = str(new_path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-button":
            self.dismiss()
        elif event.button.id == "export-button":
            self._do_export()

    def _do_export(self) -> None:
        """Perform the export."""
        status = self.query_one("#export-status", Static)

        if not self._state.entries:
            status.update("[yellow]No entries to export[/yellow]")
            return

        # Get format
        format_set = self.query_one("#format-select", RadioSet)
        pressed = format_set.pressed_button
        format_map = {
            "format-json": "json",
            "format-csv": "csv",
            "format-tsv": "tsv",
        }
        export_format = format_map.get(pressed.id if pressed else "format-json", "json")

        # Get output path
        output_path = Path(self.query_one("#output-path", Input).value)

        try:
            count = export_entries(
                self._state.entries,
                output_path,
                format=export_format,
                pretty=True,
            )
            status.update(f"[green]Exported {count} entries to {output_path}[/green]")
            self.app.notify(f"Exported {count} entries to {output_path}", severity="information")
            # Dismiss after short delay
            self.set_timer(1.5, self.dismiss)
        except Exception as e:
            status.update(f"[red]Export failed: {e}[/red]")
