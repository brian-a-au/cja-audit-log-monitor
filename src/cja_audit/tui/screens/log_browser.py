"""Log browser screen for viewing and filtering audit logs."""

from collections.abc import Iterator

from textual.app import ComposeResult
from textual.containers import Container, Horizontal
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, Label, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...models import ActionType, ComponentType
from ..modals import EntryDetailModal
from ..state import AppState
from ..widgets import FilterBar, LogTable


class LogBrowserScreen(Screen):
    """Screen for browsing and filtering audit logs."""

    BINDINGS = [
        ("enter", "view_details", "View Details"),
        ("n", "next_page", "Next Page"),
        ("p", "prev_page", "Prev Page"),
    ]

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize LogBrowserScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        """Compose the screen."""
        yield from self.compose_content()

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the log browser content.
        """
        pagination = Horizontal(
            Button("◀ Prev", id="prev-page"),
            Label("Page 1 of 1", id="page-info"),
            Button("Next ▶", id="next-page"),
            Static("", id="entry-count"),
            id="pagination",
        )

        yield Container(
            FilterBar(id="filter-bar"),
            LogTable(id="log-table", show_details=False),
            pagination,
            LoadingIndicator(id="loading"),
            id="log-browser-container",
        )

    def on_content_mounted(self) -> None:
        """Called after compose_content widgets are mounted."""
        self.run_worker(self._load_data(), exclusive=True, thread=True)

    def refresh_data(self) -> None:
        """Refresh log data."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.run_worker(self._load_data(), exclusive=True, thread=True)

    async def _load_data(self) -> None:
        """Load log data based on current filters."""
        worker = get_current_worker()

        try:
            entries, total = self._state.fetch_logs_page()

            if worker.is_cancelled:
                return

            self.app.call_from_thread(self._update_table, entries, total)

        except Exception as e:
            self.app.call_from_thread(self._show_error, str(e))
        finally:
            self.app.call_from_thread(self._hide_loading)

    def _update_table(self, entries: list, total: int) -> None:
        """Update the log table with entries."""
        table = self.query_one("#log-table", LogTable)
        table.load_entries(entries)

        # Update pagination info
        page = self._state.filters.page
        page_size = self._state.filters.page_size
        total_pages = max(1, (total + page_size - 1) // page_size)

        self.query_one("#page-info", Label).update(f"Page {page + 1} of {total_pages}")
        self.query_one("#entry-count", Static).update(f"Total: {total:,} entries")

        # Enable/disable pagination buttons
        self.query_one("#prev-page", Button).disabled = page == 0
        self.query_one("#next-page", Button).disabled = page >= total_pages - 1

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.app.notify(f"Error: {error}", severity="error")

    def _hide_loading(self) -> None:
        """Hide loading indicator."""
        self.query_one("#loading").display = False

    def on_filter_bar_filter_changed(self, event: FilterBar.FilterChanged) -> None:
        """Handle filter changes."""
        self._state.filters.user = event.user
        self._state.filters.search_text = event.search

        if event.action:
            try:
                self._state.filters.actions = [ActionType(event.action)]
            except ValueError:
                self._state.filters.actions = []
        else:
            self._state.filters.actions = []

        if event.component:
            try:
                self._state.filters.components = [ComponentType(event.component)]
            except ValueError:
                self._state.filters.components = []
        else:
            self._state.filters.components = []

        # Reset to first page
        self._state.filters.page = 0

        # Reload data
        self.refresh_data()

    def on_filter_bar_filter_reset(self, event: FilterBar.FilterReset) -> None:
        """Handle filter reset."""
        self._state.filters.reset()
        self.refresh_data()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle pagination button presses."""
        if event.button.id == "prev-page":
            self.action_prev_page()
        elif event.button.id == "next-page":
            self.action_next_page()

    def action_next_page(self) -> None:
        """Go to next page."""
        self._state.filters.page += 1
        self.refresh_data()

    def action_prev_page(self) -> None:
        """Go to previous page."""
        if self._state.filters.page > 0:
            self._state.filters.page -= 1
            self.refresh_data()

    def action_view_details(self) -> None:
        """View details of selected entry."""
        table = self.query_one("#log-table", LogTable)
        entry = table.get_selected_entry()
        if entry:
            self.app.push_screen(EntryDetailModal(entry))
        else:
            self.app.notify("No entry selected", severity="warning")

    def on_data_table_row_selected(self, event) -> None:
        """Handle DataTable row selection (Enter key)."""
        self.action_view_details()
