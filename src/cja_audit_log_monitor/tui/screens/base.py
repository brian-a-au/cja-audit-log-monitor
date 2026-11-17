"""Base class for the views shown in the main content area."""

from collections.abc import Iterator

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static

from ..state import AppState


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
        """Compose the view: an (initially hidden) empty state, then the body."""
        yield Static("", id="empty-state", classes="empty-state")
        with Vertical(id="view-body"):
            yield from self.compose_content()

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
