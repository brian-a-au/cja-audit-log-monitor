"""Log browser screen for viewing and filtering audit logs."""

from collections.abc import Iterator

from textual.containers import Container, Horizontal
from textual.css.query import NoMatches
from textual.widget import Widget
from textual.widgets import Button, Label, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...formatters import resolve_tcss_markup
from ...models import ActionType, ComponentType
from ..modals import EntryDetailPanel
from ..widgets import FilterBar, LogTable
from .base import ContentView, not_connected_message


class LogBrowserScreen(ContentView):
    """Screen for browsing and filtering audit logs."""

    # Page count from the last load; bounds the n key like the next button.
    _total_pages: int = 1

    BINDINGS = [
        ("enter", "view_details", "details"),
        ("escape", "dismiss_details", "close details"),
        ("n", "next_page", "next page"),
        ("p", "prev_page", "prev page"),
    ]

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area."""
        pagination = Horizontal(
            Button("◀ prev", id="prev-page", compact=True),
            Label("page 1 of 1", id="page-info"),
            Button("next ▶", id="next-page", compact=True),
            Static("", id="entry-count"),
            id="pagination",
        )

        # The table sits side-by-side with the (initially hidden) detail panel.
        table_and_panel = Horizontal(
            LogTable(id="log-table", show_details=False),
            EntryDetailPanel(id="entry-detail-panel"),
            id="log-table-and-panel",
        )

        table_message = Static("", id="table-message", classes="empty-state")
        table_message.display = False

        yield Container(
            FilterBar(id="filter-bar"),
            table_message,
            table_and_panel,
            pagination,
            LoadingIndicator(id="loading"),
            id="log-browser-container",
        )

    def default_focus(self) -> Widget | None:
        """Focus the table so enter / n / p / escape work right away."""
        return self.query_one("#log-table", LogTable)

    def on_content_mounted(self) -> None:
        """Called after compose_content widgets are mounted."""
        self.refresh_data()

    def refresh_data(self) -> None:
        """Refresh log data."""
        self.set_loading(True)
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
            self.app.call_from_thread(self.set_loading, False)

    def _update_table(self, entries: list, total: int) -> None:
        """Update the log table with entries."""
        table = self.query_one("#log-table", LogTable)
        table.load_entries(entries)
        if entries:
            self._set_table_message(None)
        elif self._filters_active():
            self._set_table_message(
                resolve_tcss_markup(
                    "[$text-muted]no entries match these filters · "
                    "change the search or press reset[/$text-muted]"
                )
            )
        else:
            self._set_table_message(
                resolve_tcss_markup("[$text-muted]no audit log entries[/$text-muted]")
            )

        # Update pagination info
        page = self._state.filters.page
        page_size = self._state.filters.page_size
        total_pages = max(1, (total + page_size - 1) // page_size)
        self._total_pages = total_pages

        self.query_one("#page-info", Label).update(f"page {page + 1} of {total_pages}")
        self.query_one("#entry-count", Static).update(f"· {total:,} entries")

        # Enable/disable pagination buttons
        self.query_one("#prev-page", Button).disabled = page == 0
        self.query_one("#next-page", Button).disabled = page >= total_pages - 1

    def _show_error(self, error: str) -> None:
        """Show why the table is empty, above it, so the filters stay usable."""
        self.query_one("#log-table", LogTable).load_entries([])
        self._set_table_message(not_connected_message(error))

    def _set_table_message(self, message: str | None) -> None:
        """Show ``message`` above the table, or hide it when None."""
        widget = self.query_one("#table-message", Static)
        widget.display = message is not None
        widget.update(message or "")

    def _filters_active(self) -> bool:
        filters = self._state.filters
        return bool(
            filters.search_text or filters.user or filters.actions or filters.components
        )


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
        """Go to the next page, if there is one."""
        if self._state.filters.page + 1 >= self._total_pages:
            return
        self._state.filters.page += 1
        self.refresh_data()

    def action_prev_page(self) -> None:
        """Go to previous page."""
        if self._state.filters.page > 0:
            self._state.filters.page -= 1
            self.refresh_data()

    def action_view_details(self) -> None:
        """Toggle the entry detail side panel for the selected row."""
        table = self.query_one("#log-table", LogTable)
        entry = table.get_selected_entry()
        panel = self.query_one("#entry-detail-panel", EntryDetailPanel)
        if entry:
            panel.toggle(entry)
            self.refresh_bindings()
        else:
            self.app.notify("no entry selected", severity="warning")

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool | None:
        """Offer "close details" in the footer only while the panel is open."""
        if action == "dismiss_details":
            try:
                return self.query_one("#entry-detail-panel", EntryDetailPanel).is_visible()
            except NoMatches:
                return False
        return True

    def on_data_table_row_selected(self, event) -> None:
        """Handle DataTable row selection (Enter key)."""
        self.action_view_details()

    def on_data_table_row_highlighted(self, event) -> None:
        """If the panel is visible, update its content as the cursor moves."""
        try:
            panel = self.query_one("#entry-detail-panel", EntryDetailPanel)
        except NoMatches:
            return
        if not panel.is_visible():
            return
        table = self.query_one("#log-table", LogTable)
        entry = table.get_selected_entry()
        if entry is not None:
            panel.show_entry(entry)

    def action_dismiss_details(self) -> None:
        """Hide the entry detail side panel if visible."""
        try:
            panel = self.query_one("#entry-detail-panel", EntryDetailPanel)
        except NoMatches:
            return
        if panel.is_visible():
            panel.hide()
            self.refresh_bindings()
