"""Main TUI application for CJA Audit Log Monitor."""

from pathlib import Path
from typing import Literal

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.message import Message
from textual.screen import ModalScreen
from textual.widgets import ContentSwitcher, Footer, Static

from ..formatters import literal, resolve_tcss_markup
from .screens.base import ContentView, classify_error
from .state import AppState

ConnectionStatus = Literal["connecting", "connected", "disconnected"]


HELP_SECTIONS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "views",
        [
            ("d", "dashboard · summary of the last 7 days"),
            ("l", "logs · browse and filter entries"),
            ("m", "monitor · watch for new entries"),
            ("s", "stats · charts for any number of days"),
            ("a", "alerts · alert rules"),
            ("c", "config · current settings"),
        ],
    ),
    (
        "logs",
        [
            ("n", "next page"),
            ("p", "previous page"),
            ("enter", "entry details"),
            ("esc", "close entry details"),
        ],
    ),
    (
        "monitor",
        [
            ("space", "start or stop monitoring"),
        ],
    ),
    (
        "everywhere",
        [
            ("r", "refresh the current view"),
            ("e", "export entries"),
            ("/", "search the logs"),
            ("tab", "move between panels and fields"),
            ("?", "show or close this help"),
            ("esc", "close a dialog"),
            ("q", "quit"),
        ],
    ),
]


class HelpScreen(ModalScreen):
    """Help overlay listing every keyboard shortcut."""

    BINDINGS = [
        Binding("escape", "dismiss", "close"),
        Binding("question_mark", "dismiss", "close"),
    ]

    def compose(self) -> ComposeResult:
        """Compose help screen content."""
        key_width = max(len(key) for _, rows in HELP_SECTIONS for key, _ in rows) + 2
        with Vertical(id="help-overlay"):
            yield Static("keyboard shortcuts", id="help-title", classes="modal-title")
            for title, rows in HELP_SECTIONS:
                yield Static(title.upper(), classes="section-label help-section")
                body = "\n".join(
                    resolve_tcss_markup(f"[$primary]{literal(key):<{key_width}}[/$primary]")
                    + literal(description)
                    for key, description in rows
                )
                yield Static(body, classes="help-section-body")
            yield Static(
                resolve_tcss_markup("[$text-muted]press esc or ? to close[/$text-muted]"),
                id="help-footer",
            )


class CJAAuditApp(App):
    """Main TUI application for CJA Audit Log Monitor."""

    TITLE = "CJA Audit Log Monitor"
    CSS_PATH = "styles.tcss"
    # Width classes on the screen (-narrow / -normal / -wide) drive layout in styles.tcss.
    HORIZONTAL_BREAKPOINTS = [(0, "-narrow"), (100, "-normal"), (160, "-wide")]
    _NARROW_BELOW = 100

    BINDINGS = [
        Binding("d", "switch_screen('dashboard')", "dashboard", show=False),
        Binding("l", "switch_screen('logs')", "logs", show=False),
        Binding("m", "switch_screen('monitor')", "monitor", show=False),
        Binding("s", "switch_screen('stats')", "stats", show=False),
        Binding("a", "switch_screen('alerts')", "alerts", show=False),
        Binding("c", "switch_screen('settings')", "config", show=False),
        Binding("r", "refresh", "refresh"),
        Binding("e", "export", "export"),
        Binding("slash", "focus_search", "search"),
        Binding("question_mark", "show_help", "help"),
        Binding("q", "quit", "quit"),
    ]

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the TUI application.

        Args:
            config_path: Optional path to config file.
        """
        super().__init__()
        self.state = AppState(config_path)
        self._current_screen = "dashboard"
        self._screens: dict[str, ContentView] = {}
        self._mounted_views: set[str] = set()
        self._nav_narrow: bool | None = None

    NAV_KEYS = {
        "nav-dashboard": "d",
        "nav-logs": "l",
        "nav-monitor": "m",
        "nav-stats": "s",
        "nav-alerts": "a",
        "nav-settings": "c",
    }

    NAV_LABELS = {
        "nav-dashboard": "dashboard",
        "nav-logs": "logs",
        "nav-monitor": "monitor",
        "nav-stats": "stats",
        "nav-alerts": "alerts",
        "nav-settings": "config",
    }

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Static(self._status_row_text(), id="status-row")
        yield Horizontal(
            Vertical(
                Static("NAVIGATE", classes="nav-section-label"),
                *(
                    Static(
                        self._nav_text(nav_id, nav_id == "nav-dashboard"),
                        id=nav_id,
                        classes="nav-item active" if nav_id == "nav-dashboard" else "nav-item",
                    )
                    for nav_id in self.NAV_LABELS
                ),
                id="sidebar",
            ),
            ContentSwitcher(id="main-content"),
        )
        yield Footer(show_command_palette=False)

    def _nav_text(self, nav_id: str, active: bool) -> str:
        """Sidebar label: active marker, the view's key, then its name."""
        key = self.NAV_KEYS[nav_id]
        if self.size.width < self._NARROW_BELOW:
            # Compact sidebar: just the key letter (the marker is the active style).
            return resolve_tcss_markup(f"[$primary]{key}[/$primary]")
        prefix = "▸ " if active else "  "
        return prefix + resolve_tcss_markup(
            f"[$primary]{key}[/$primary] {self.NAV_LABELS[nav_id]}"
        )

    _STATUS_DOT = {"connecting": "$warning", "connected": "$success", "disconnected": "$error"}

    def _status_row_text(
        self, status: ConnectionStatus = "connecting", detail: str = ""
    ) -> str:
        """Build the top status row content."""
        org = self.state.settings.org_id  # loads config; may set config_error
        color = self._STATUS_DOT[status]
        if not detail and not self.state.config_error_summary:
            detail = f"org {org}" if org else ""
        text = f"cja-audit-log-monitor · [{color}]●[/{color}] {status}"
        if detail:
            text += f" · [$text-muted]{literal(detail)}[/$text-muted]"
        if self.state.config_error_summary:
            warning = literal(self.state.config_error_summary)
            text += f" · [$warning]⚠ {warning}[/$warning]"
        return text

    _connection_status: ConnectionStatus = "connecting"

    def set_connection_status(self, status: ConnectionStatus, detail: str = "") -> None:
        """Show the API connection state in the header row.

        Args:
            status: One of ``connecting``, ``connected`` or ``disconnected``.
            detail: Org id, or the error when disconnected. Only its first
                line is shown; views show the full error.
        """
        self._connection_status = status
        first_line = detail.strip().splitlines()[0] if detail.strip() else ""
        try:
            row = self.query_one("#status-row", Static)
        except NoMatches:
            return  # the screen is gone (app shutting down): nothing left to update
        row.update(self._status_row_text(status, first_line))

    def note_api_error(self, error: Exception) -> None:
        """Mark the header disconnected when a view's API call failed to connect."""
        if classify_error(error) == "connection":
            self.set_connection_status("disconnected", str(error))

    def note_api_ok(self) -> None:
        """Mark the header connected again after any successful API call."""
        if self._connection_status != "connected":
            self.set_connection_status("connected")

    async def on_mount(self) -> None:
        """Handle application mount."""
        from .screens import (
            AlertsScreen,
            DashboardScreen,
            LogBrowserScreen,
            MonitorScreen,
            SettingsScreen,
            StatsScreen,
        )

        views = {
            "dashboard": DashboardScreen,
            "logs": LogBrowserScreen,
            "monitor": MonitorScreen,
            "stats": StatsScreen,
            "alerts": AlertsScreen,
            "settings": SettingsScreen,
        }
        self._screens = {name: cls(self.state, id=f"view-{name}") for name, cls in views.items()}

        self.state.apply_settings_defaults()

        # Show dashboard by default
        await self._show_screen("dashboard")

    async def _on_resize(self, event: events.Resize) -> None:
        """Re-render the sidebar labels when the width crosses the narrow breakpoint.

        Textual's own handler stops the event before a plain ``on_resize`` would run,
        so this extends it. Nav items are looked up on the base screen, because
        ``App.query`` only sees the active screen (a modal may be open).
        """
        await super()._on_resize(event)
        narrow = event.size.width < self._NARROW_BELOW
        if narrow == self._nav_narrow:
            return
        self._nav_narrow = narrow
        for item in self.screen_stack[0].query("#sidebar .nav-item"):
            item.update(self._nav_text(item.id, item.has_class("active")))

    async def _show_screen(self, screen_name: str) -> None:
        """Show a screen in the main content area.

        Args:
            screen_name: Name of screen to show.
        """
        switcher = self.query_one("#main-content", ContentSwitcher)

        # Update navigation item states (the displayed label may differ from
        # the screen id — e.g. nav-settings shows "config").
        for item in self.query("#sidebar .nav-item"):
            is_active = item.id == f"nav-{screen_name}"
            item.set_class(is_active, "active")
            item.update(self._nav_text(item.id, is_active))

        view = self._screens.get(screen_name)
        if view is None:
            return
        # Mount each view once, on first visit; later visits just switch to it,
        # so state such as the current log page or a running monitor survives.
        if screen_name not in self._mounted_views:
            self._mounted_views.add(screen_name)
            await switcher.add_content(view, set_current=True)
            view.on_content_mounted()
        else:
            switcher.current = view.id

        # Move focus into the shown view (or clear it), so keys never land in
        # an input inside a hidden view, and the view's own bindings work.
        self.set_focus(view.default_focus())

        self._current_screen = screen_name

    async def on_click(self, event: events.Click) -> None:
        """Handle clicks on sidebar nav items.

        Walks ancestors so clicks on any child element of a nav item still
        navigate, not just clicks on the leaf Static itself.
        """
        widget = event.widget
        if widget is None:
            return
        for candidate in widget.ancestors_with_self:
            candidate_id = getattr(candidate, "id", None)
            if candidate_id and candidate_id.startswith("nav-"):
                screen_name = candidate_id.replace("nav-", "")
                await self._show_screen(screen_name)
                return

    def settings_reloaded(self) -> None:
        """Tell the views already shown that the settings were re-read.

        Each one takes the new defaults and reloads its data; views not yet shown pick
        the defaults up when they are first built. The config view redraws itself.
        """
        for name in self._mounted_views:
            if name != "settings":
                self._screens[name].on_settings_reloaded()

    def action_switch_screen(self, screen_name: str) -> None:
        """Switch to a different screen."""
        self.call_later(self._show_screen, screen_name)

    def action_refresh(self) -> None:
        """Refresh current screen data."""
        self.post_message(RefreshData())

    def on_refresh_data(self, event: "RefreshData") -> None:
        """Handle refresh requests by forwarding to the active screen.

        A view's ``refresh_data`` returns False when it did not refresh and has already
        told the user why, so only one toast shows.
        """
        current = self._screens.get(self._current_screen)
        refresh_method = getattr(current, "refresh_data", None)
        if callable(refresh_method) and refresh_method() is not False:
            self.notify("Refreshing...", severity="information")

    def action_export(self) -> None:
        """Show export dialog."""
        from .modals import ExportDialog

        self.push_screen(ExportDialog(self.state))

    async def action_focus_search(self) -> None:
        """Switch to the log browser and focus its search input."""
        if self._current_screen != "logs":
            await self._show_screen("logs")
        try:
            self._screens["logs"].query_one("#filter-search").focus()
        except NoMatches:
            pass

    def action_show_help(self) -> None:
        """Show help overlay."""
        self.push_screen(HelpScreen())

    def action_quit(self) -> None:
        """Quit the application."""
        self.state.close()
        self.exit()


class RefreshData(Message):
    """Message to trigger data refresh."""

    pass


def run_tui(config_path: Path | None = None) -> None:
    """Run the TUI application.

    Args:
        config_path: Optional path to config file.
    """
    app = CJAAuditApp(config_path)
    app.run()
