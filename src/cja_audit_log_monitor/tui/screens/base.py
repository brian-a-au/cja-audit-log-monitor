"""Base class for the views shown in the main content area."""

from collections.abc import Iterator

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static

from ...formatters import resolve_tcss_markup
from ..state import AppState


def not_connected_message(error: str) -> str:
    """Empty-state copy shown when the API connection fails."""
    return resolve_tcss_markup(
        f"[$danger]●[/$danger] not connected · {error}\n"
        "[$text-muted]press c to open config, or run: "
        "cja-audit-log-monitor cli verify[/$text-muted]"
    )


def no_activity_message(days: int) -> str:
    """Empty-state copy shown when a time window has no entries."""
    return resolve_tcss_markup(
        f"[$text-muted]no audit activity in the last {days} days[/$text-muted]"
    )


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
