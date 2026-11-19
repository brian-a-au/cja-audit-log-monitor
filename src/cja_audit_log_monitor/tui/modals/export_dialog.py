"""Export dialog modal for exporting audit logs."""

from pathlib import Path, PurePath

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.content import Content
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, RadioButton, RadioSet, Static
from textual.worker import get_current_worker

from ...export import check_export_path, export_entries
from ...formatters import TCSS_TOKEN_HEX
from ...models import AuditLogEntry
from ..state import AppState

# Most entries "all matching" will fetch (10 requests at the API's page size of 1,000).
EXPORT_MAX = 10_000

FORMAT_EXTENSIONS = {"format-json": ".json", "format-csv": ".csv", "format-tsv": ".tsv"}


def swap_suffix(value: str, ext: str) -> str:
    """Return ``value`` with its export extension set to ``ext``.

    An empty value or a folder path (ending in ``/``) is returned unchanged. A known
    export suffix (``.json``, ``.csv``, ``.tsv``) is replaced; any other suffix, as in
    ``report.v2``, is kept and ``ext`` is appended.
    """
    if not value or value.endswith(("/", "\\")):
        return value
    suffix = PurePath(value).suffix
    if suffix.lower() in FORMAT_EXTENSIONS.values():
        return value[: -len(suffix)] + ext
    return value + ext


def _one_line(error: Exception) -> str:
    """An error message squeezed onto one line for the dialog's status row."""
    return " ".join(str(error).split())


class ExportDialog(ModalScreen):
    """Modal dialog for exporting audit log data."""

    # The app sets AUTO_FOCUS = None for the views; a dialog still focuses its first widget.
    AUTO_FOCUS = "*"

    BINDINGS = [
        ("escape", "dismiss", "cancel"),
    ]

    AUTO_CLOSE_SECONDS: float = 1.5

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize ExportDialog.

        Args:
            state: Application state; ``entries`` is the current page and
                ``filters`` select what "all matching" fetches.
            **kwargs: Additional arguments for ModalScreen.
        """
        super().__init__(**kwargs)
        self._state = state
        # (path, format) the user was asked to confirm overwriting; None when nothing is pending.
        self._overwrite_pending: tuple[str, str] | None = None

    def compose(self) -> ComposeResult:
        """Compose dialog content."""
        page_loaded = self._state.page_loaded
        page_count = len(self._state.entries)
        total = max(self._state.total_entries, page_count)
        with Vertical(id="export-box"):
            yield Static("export audit logs", id="export-title", classes="modal-title")

            yield Label("entries", classes="field-label")
            with RadioSet(id="scope-select", compact=True):
                # Counts are only known once the log browser has loaded a page.
                yield RadioButton(
                    f"this page · {page_count:,} entries" if page_loaded else "this page",
                    value=page_loaded,
                    id="scope-page",
                    disabled=not page_loaded,
                )
                yield RadioButton(
                    f"all matching · {total:,} entries (up to {EXPORT_MAX:,})"
                    if page_loaded
                    else f"all matching (up to {EXPORT_MAX:,})",
                    value=not page_loaded,
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
        path_input.value = swap_suffix(path_input.value, ext)
        self._overwrite_pending = None

    def on_input_changed(self, event: Input.Changed) -> None:
        """A new path needs its own overwrite confirmation."""
        if event.input.id == "output-path":
            self._overwrite_pending = None

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the path field exports, like the export button."""
        if event.input.id == "output-path":
            event.stop()
            self._do_export()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "cancel-button":
            self.dismiss()
        elif event.button.id == "export-button":
            self._do_export()

    def _set_status(self, message: str, token: str = "$text-muted") -> None:
        """Show one status line. ``message`` is literal text, never markup, so a path is safe."""
        self.query_one("#export-status", Static).update(
            Content.styled(message, TCSS_TOKEN_HEX[token])
        )

    def _selected_format(self) -> str:
        pressed = self.query_one("#format-select", RadioSet).pressed_button
        return (pressed.id if pressed else "format-json").removeprefix("format-")

    def _do_export(self) -> None:
        """Export the chosen entries in a worker, so the UI stays responsive."""
        if self.query_one("#export-button", Button).disabled:
            return  # an export is already running
        raw_path = self.query_one("#output-path", Input).value.strip()
        export_format = self._selected_format()
        fetch_all = self.query_one("#scope-all", RadioButton).value

        if not raw_path:
            self._set_status("enter a file path", "$warning")
            return
        output_path, problem, exists = check_export_path(raw_path)
        if problem is not None or output_path is None:
            self._set_status(problem or "cannot use that path", "$danger")
            return
        key = (raw_path, export_format)
        if exists and self._overwrite_pending != key:
            self._overwrite_pending = key
            self._set_status("file exists · press export again to overwrite", "$warning")
            return
        # A pending confirmation is spent by this press: it is the one allowed to replace.
        replace = exists
        self._overwrite_pending = None

        if not fetch_all and not self._state.entries:
            self._set_status("no entries to export", "$warning")
            return

        self.query_one("#export-button", Button).disabled = True
        self._set_status("fetching matching entries…" if fetch_all else "writing…")
        page_entries = list(self._state.entries)
        self.run_worker(
            lambda: self._export_in_worker(
                fetch_all, page_entries, output_path, export_format, replace, key
            ),
            thread=True,
            exclusive=True,
        )

    def _export_in_worker(
        self,
        fetch_all: bool,
        page_entries: list[AuditLogEntry],
        output_path: Path,
        export_format: str,
        overwrite: bool,
        key: tuple[str, str],
    ) -> None:
        """Worker: fetch (for "all matching"), write the file, then report on the UI thread."""
        worker = get_current_worker()
        # Read the app now: once the dialog is closed it is detached and ``self.app`` fails.
        app = self.app
        total: int | None = None
        if fetch_all:
            try:
                entries, total = self._state.client.get_logs_sample(
                    self._state.filters.to_query(), max_entries=EXPORT_MAX
                )
            except Exception as e:
                app.call_from_thread(self._fail, f"could not fetch entries: {_one_line(e)}")
                return
        else:
            entries = page_entries
        if worker.is_cancelled:
            return
        if not entries:
            app.call_from_thread(self._fail, "no entries to export")
            return
        try:
            count = export_entries(
                entries, output_path, output_format=export_format, pretty=True, overwrite=overwrite
            )
        except FileExistsError:
            # The file appeared after the check above; ask before replacing it.
            app.call_from_thread(self._ask_overwrite, key)
            return
        except Exception as e:
            app.call_from_thread(self._fail, f"export failed: {_one_line(e)}")
            return
        # The file is written: report it even if the dialog was closed meanwhile.
        app.call_from_thread(self._done, app, count, total, output_path)

    def _is_live(self) -> bool:
        """True while this dialog is still the open screen (the user has not closed it)."""
        return self.is_attached and self.app.screen is self

    def _ask_overwrite(self, key: tuple[str, str]) -> None:
        if not self._is_live():
            return
        self._overwrite_pending = key
        self.query_one("#export-button", Button).disabled = False
        self._set_status("file exists · press export again to overwrite", "$warning")

    def _fail(self, message: str) -> None:
        if not self._is_live():
            return
        self.query_one("#export-button", Button).disabled = False
        self._set_status(message, "$danger")

    def _done(self, app: App, count: int, total: int | None, output_path: Path) -> None:
        """Report a finished export (also after the dialog closed) and close it shortly after."""
        where = output_path.resolve()
        if total is not None and total > count and count >= EXPORT_MAX:
            summary = f"exported {count:,} of {total:,} (limit reached) to {where}"
        elif total is not None and total > count:
            summary = f"exported {count:,} of {total:,} matching entries to {where}"
        else:
            summary = f"exported {count:,} entries to {where}"
        app.notify(summary, markup=False)
        if not self._is_live():
            return
        self._set_status(summary, "$success")
        self.set_timer(self.AUTO_CLOSE_SECONDS, self._close_if_open)

    def _close_if_open(self) -> None:
        """Close the dialog after a successful export, unless the user already did.

        Calls ``dismiss`` without awaiting it: a timer callback runs as this
        screen's own message handler, where awaiting ``dismiss`` raises
        ``ScreenError`` and crashes the app.
        """
        if self.is_attached and self.app.screen is self:
            self.dismiss()
