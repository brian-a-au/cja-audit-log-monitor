"""Base class for the views shown in the main content area."""

from collections.abc import Iterator
from typing import Literal

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.markup import escape
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static

from ...auth import AuthenticationError
from ...client import APIError
from ...formatters import resolve_tcss_markup
from ..state import AppState


def not_connected_message(error: str) -> str:
    """Empty-state copy shown when the API connection fails."""
    return resolve_tcss_markup(
        f"[$danger]●[/$danger] not connected · {escape(error)}\n"
        "[$text-muted]press c to open config, or run: "
        "cja-audit-log-monitor cli verify[/$text-muted]"
    )


ErrorKind = Literal["connection", "access", "rejected", "other"]

_ERROR_COPY: dict[ErrorKind, tuple[str, str]] = {
    "connection": (
        "not connected",
        "press c to open config, or run: cja-audit-log-monitor cli verify",
    ),
    "access": (
        "access denied",
        "check that the API credential has a CJA product profile and the right scopes",
    ),
    "rejected": (
        "request rejected",
        "check the filters or the number of days, then press r",
    ),
    "other": ("could not load data", "press r to try again"),
}


def classify_error(error: Exception) -> ErrorKind:
    """Sort a failed API call into the kind of problem the user has to fix."""
    if isinstance(error, AuthenticationError):
        return "connection"
    if isinstance(error, APIError):
        status = error.status_code
        if status is None or status == 401:
            return "connection"  # network failure, or the token was rejected
        if status == 403:
            return "access"
        if status in (400, 422):
            return "rejected"
    return "other"


def error_message(error: Exception) -> str:
    """Empty-state copy for a failed API call: what went wrong and what to do next."""
    if classify_error(error) == "connection":
        return not_connected_message(str(error))
    headline, hint = _ERROR_COPY[classify_error(error)]
    return resolve_tcss_markup(
        f"[$danger]●[/$danger] {headline} · {escape(str(error))}\n"
        f"[$text-muted]{hint}[/$text-muted]"
    )


def no_activity_message(days: int) -> str:
    """Empty-state copy shown when a time window has no entries."""
    return resolve_tcss_markup(
        f"[$text-muted]no audit activity in the last {days} days[/$text-muted]"
    )


def sample_note_text(shown: int, total: int) -> str | None:
    """Copy for when charts use only the newest entries; None when they use all of them."""
    if total <= shown:
        return None
    return resolve_tcss_markup(
        f"[$text-muted]charts and lists use the newest {shown:,} of {total:,} entries"
        "[/$text-muted]"
    )


def sample_note() -> Static:
    """An initially hidden line under the stat cards for the sample note."""
    note = Static("", classes="sample-note")
    note.display = False
    return note


def show_sample_note(view: Widget, shown: int, total: int) -> None:
    """Show or hide ``view``'s sample note for ``shown`` of ``total`` entries."""
    note = view.query_one(".sample-note", Static)
    text = sample_note_text(shown, total)
    note.display = text is not None
    note.update(text or "")


def stat_card(label: str, value_id: str) -> Vertical:
    """A small card with a muted label above a bold value."""
    return Vertical(
        Static(label, classes="stat-label"),
        Static("-", id=value_id, classes="stat-value"),
        classes="stat-card",
    )


class ContentView(Vertical):
    """A view mounted inside the app's ``#main-content`` ContentSwitcher.

    Views are plain widgets, not ``textual.screen.Screen`` objects: a Screen
    mounted as a child gets a zero-size region and renders nothing.
    """

    DEFAULT_CSS = """
    ContentView {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize the view.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Vertical (e.g. ``id``).
        """
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        """Compose the view: header, an (initially hidden) empty state, then the body."""
        yield from self.compose_header()
        yield Static("", id="empty-state", classes="empty-state")
        with Vertical(id="view-body"):
            yield from self.compose_content()

    def compose_header(self) -> Iterator[Widget]:
        """Yield widgets that stay visible even when the empty state is shown."""
        yield from ()

    def compose_content(self) -> Iterator[Widget]:
        """Yield the view's widgets."""
        raise NotImplementedError

    def default_focus(self) -> Widget | None:
        """Widget to focus when the view is shown, so the view's own keys work.

        Return None to clear focus (nothing in a hidden view keeps it).
        """
        return None

    def set_empty_state(self, message: str | None) -> None:
        """Show ``message`` in place of the view body, or restore the body when None."""
        empty = self.query_one("#empty-state", Static)
        body = self.query_one("#view-body")
        if message is None:
            empty.display = False
            body.display = True
        else:
            empty.update(message)
            empty.display = True
            body.display = False

    def set_loading(self, loading: bool) -> None:
        """Show or hide the view's loading indicator, if it has one."""
        for indicator in self.query(LoadingIndicator):
            indicator.display = loading

    def on_content_mounted(self) -> None:
        """Hook called once, the first time the view is shown."""

    def refresh_data(self) -> None:
        """Reload the view's data (bound to the ``r`` key)."""
