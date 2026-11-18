"""Export dialog modal for exporting audit logs."""

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static
from textual.worker import get_current_worker

from ...export import export_entries
from ...formatters import resolve_tcss_markup
from ...models import AuditLogEntry
from ..state import AppState

# Most entries "all matching" will fetch (10 requests at the API's page size of 1,000).
EXPORT_MAX = 10_000

FORMAT_EXTENSIONS = {"format-json": ".json", "format-csv": ".csv", "format-tsv": ".tsv"}


class ExportDialog(ModalScreen):
    """Modal dialog for exporting audit log data."""

    BINDINGS = [
        ("escape", "dismiss", "cancel"),
    ]

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize ExportDialog.

        Args:
            state: Application state; ``entries`` is the current page and
                ``filters`` select what "all matching" fetches.
            **kwargs: Additional arguments for ModalScreen.
        """
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        """Compose dialog content."""
        page_count = len(self._state.entries)
        total = max(self._state.total_entries, page_count)
        with Vertical(id="export-box"):
            yield Static("export audit logs", id="export-title", classes="modal-title")

            yield Label("entries", classes="field-label")
            with RadioSet(id="scope-select", compact=True):
                yield RadioButton(
                    f"this page · {page_count:,} entries", value=True, id="scope-page"
                )
                yield RadioButton(
                    f"all matching · {total:,} entries (up to {EXPORT_MAX:,})",
                    id="scope-all",
                )

            yield Label("format", classes="field-label")
            with RadioSet(id="format-select", compact=True):
                yield RadioButton("json", value=True, id="format-json")
                yield RadioButton("csv", id="format-csv")
                yield RadioButton("tsv", id="format-tsv")

            yield Label("file", classes="field-label")
            yield Input(
                placeholder="file path",
                value="audit_logs_export.json",
                id="output-path",
                compact=True,
            )

            yield Horizontal(
                Button("export", id="export-button", variant="primary", compact=True),
                Button("cancel", id="cancel-button", compact=True),
                classes="modal-buttons",
            )

            yield Static("", id="export-status")

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        """Update the file extension when the format changes."""
        ext = FORMAT_EXTENSIONS.get(event.pressed.id or "")
        if ext is None:
            return
        path_input = self.query_one("#output-path", Input)
        path_input.value = str(Path(path_input.value).with_suffix(ext))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-button":
            self.dismiss()
        elif event.button.id == "export-button":
            self._do_export()

    def _set_status(self, markup: str) -> None:
        self.query_one("#export-status", Static).update(resolve_tcss_markup(markup))

    def _selected_format(self) -> str:
        pressed = self.query_one("#format-select", RadioSet).pressed_button
        return (pressed.id if pressed else "format-json").removeprefix("format-")

    def _do_export(self) -> None:
        """Export the chosen entries in a worker, so the UI stays responsive."""
        output_path = Path(self.query_one("#output-path", Input).value).expanduser()
        export_format = self._selected_format()
        fetch_all = self.query_one("#scope-all", RadioButton).value

        if not fetch_all and not self._state.entries:
            self._set_status("[$warning]no entries to export[/$warning]")
            return

        self.query_one("#export-button", Button).disabled = True
        self._set_status(
            "[$text-muted]fetching matching entries…[/$text-muted]"
            if fetch_all
            else "[$text-muted]writing…[/$text-muted]"
        )
        page_entries = list(self._state.entries)
        self.run_worker(
            lambda: self._export_in_worker(fetch_all, page_entries, output_path, export_format),
            thread=True,
            exclusive=True,
        )

    def _export_in_worker(
        self,
        fetch_all: bool,
        page_entries: list[AuditLogEntry],
        output_path: Path,
        export_format: str,
    ) -> None:
        """Worker: fetch (for "all matching"), write the file, then report on the UI thread."""
        worker = get_current_worker()
        if fetch_all:
            try:
                entries, _ = self._state.client.get_logs_sample(
                    self._state.filters.to_query(), max_entries=EXPORT_MAX
                )
            except Exception as e:
                self.app.call_from_thread(self._fail, f"could not fetch entries: {e}")
                return
        else:
            entries = page_entries
        if worker.is_cancelled:
            return
        if not entries:
            self.app.call_from_thread(self._fail, "no entries to export")
            return
        try:
            count = export_entries(entries, output_path, output_format=export_format, pretty=True)
        except Exception as e:
            self.app.call_from_thread(self._fail, f"export failed: {e}")
            return
        if not worker.is_cancelled:
            self.app.call_from_thread(self._done, count, output_path)

    def _fail(self, message: str) -> None:
        self.query_one("#export-button", Button).disabled = False
        self._set_status(f"[$danger]{message}[/$danger]")

    def _done(self, count: int, output_path: Path) -> None:
        """Report a finished export and close the dialog shortly after."""
        self._set_status(f"[$success]exported {count:,} entries to {output_path}[/$success]")
        self.app.notify(f"exported {count:,} entries to {output_path}")
        self.set_timer(1.5, self._close_if_open)

    def _close_if_open(self) -> None:
        """Close the dialog after a successful export, unless the user already did.

        Calls ``dismiss`` without awaiting it: a timer callback runs as this
        screen's own message handler, where awaiting ``dismiss`` raises
        ``ScreenError`` and crashes the app.
        """
        if self.is_attached and self.app.screen is self:
            self.dismiss()
