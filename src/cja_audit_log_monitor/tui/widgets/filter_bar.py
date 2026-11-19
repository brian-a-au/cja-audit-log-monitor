"""Filter bar widget for log filtering."""

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input, Select, Static

from ...models import ActionType, ComponentType


class FilterBar(Static):
    """Filter bar widget for searching and filtering logs."""

    class FilterChanged(Message):
        """Message emitted when filters change."""

        def __init__(
            self,
            user: str,
            action: str | None,
            component: str | None,
            search: str,
        ) -> None:
            super().__init__()
            self.user = user
            self.action = action
            self.component = component
            self.search = search

    class FilterReset(Message):
        """Message emitted when filters are reset."""

        pass

    def compose(self) -> ComposeResult:
        """Compose the filter bar: a text row and a select row.

        Side by side on one line normally; stacked as two lines under ``-narrow``.
        """
        with Horizontal(id="filter-text-row"):
            yield Input(placeholder="search", id="filter-search", compact=True)
            yield Input(placeholder="user", id="filter-user", compact=True)
        with Horizontal(id="filter-select-row"):
            yield Select(
                [(a.value, a.value) for a in ActionType],
                prompt="action",
                allow_blank=True,
                compact=True,
                id="filter-action",
            )
            yield Select(
                [(c.value, c.value) for c in ComponentType],
                prompt="component",
                allow_blank=True,
                compact=True,
                id="filter-component",
            )
            yield Button("reset", id="filter-reset", compact=True)

    def on_key(self, event: events.Key) -> None:
        """Escape leaves a filter input for the view's main widget, keeping what was typed."""
        if event.key != "escape":
            return
        focused = self.screen.focused
        if focused is not None and any(
            isinstance(widget, Select) and widget.expanded for widget in focused.ancestors_with_self
        ):
            return  # the open dropdown closes itself; the next Escape leaves the bar
        event.stop()  # not also the view's "close details"
        event.prevent_default()
        for ancestor in self.ancestors:
            default_focus = getattr(ancestor, "default_focus", None)
            if callable(default_focus):
                self.screen.set_focus(default_focus())
                return
        self.screen.set_focus(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle filter button presses."""
        if event.button.id == "filter-reset":
            self._reset_filters()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key in input fields."""
        self._emit_filter_changed()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Auto-apply when the action or component dropdown changes."""
        self._emit_filter_changed()

    def _emit_filter_changed(self) -> None:
        """Emit filter changed message with current values."""
        search = self.query_one("#filter-search", Input).value
        user = self.query_one("#filter-user", Input).value
        action_select = self.query_one("#filter-action", Select)
        component_select = self.query_one("#filter-component", Select)

        action = action_select.value if action_select.value != Select.BLANK else None
        component = component_select.value if component_select.value != Select.BLANK else None

        self.post_message(self.FilterChanged(user, action, component, search))

    def _reset_filters(self) -> None:
        """Reset all filter inputs."""
        self.query_one("#filter-search", Input).value = ""
        self.query_one("#filter-user", Input).value = ""
        self.query_one("#filter-action", Select).value = Select.BLANK
        self.query_one("#filter-component", Select).value = Select.BLANK
        self.post_message(self.FilterReset())
