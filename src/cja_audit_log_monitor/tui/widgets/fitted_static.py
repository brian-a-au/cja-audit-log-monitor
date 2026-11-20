"""A Static that redraws itself to fit whenever its size changes."""

from collections.abc import Callable

from textual import events
from textual.widgets import Static


class FittedStatic(Static):
    """Static whose content depends on its width, e.g. truncated names or bars.

    ``redraw`` is called whenever the widget's size changes, including when a
    scrollbar appears beside it, so the content always fits the final width.
    """

    def __init__(self, *args, redraw: Callable[[], None] | None = None, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self._redraw = redraw

    def on_resize(self, event: events.Resize) -> None:
        """Redraw for the new width."""
        if self._redraw is not None:  # pragma: no branch - every use passes redraw
            self._redraw()
