"""Base class for the views shown in the main content area."""

from collections.abc import Iterator

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget

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
        """Compose the view from ``compose_content``."""
        yield from self.compose_content()

    def compose_content(self) -> Iterator[Widget]:
        """Yield the view's widgets."""
        raise NotImplementedError

    def on_content_mounted(self) -> None:
        """Hook called once, the first time the view is shown."""

    def refresh_data(self) -> None:
        """Reload the view's data (bound to the ``r`` key)."""
