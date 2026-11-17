"""Main TUI application for CJA Audit Log Monitor."""

from pathlib import Path
from typing import Literal

from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.css.query import NoMatches
from textual.markup import escape
from textual.message import Message
from textual.screen import Screen
from textual.widgets import ContentSwitcher, Footer, Static

from .screens.base import ContentView
from .state import AppState

ConnectionStatus = Literal["connecting", "connected", "disconnected"]


class HelpScreen(Screen):
    """Help overlay showing keybindings."""

    BINDINGS = [
        Binding("escape", "dismiss", "Close"),
        Binding("?", "dismiss", "Close"),
    ]

    def compose(self) -> ComposeResult:
        """Compose help screen content."""
        yield Vertical(
            Static("[bold]CJA Audit Log Monitor - Help[/bold]\n", classes="help-title"),
            Static("[bold]Navigation[/bold]", classes="help-section"),
            Horizontal(
                Static("d", classes="help-key"),
                Static("Dashboard - Summary view", classes="help-description"),
            ),
            Horizontal(
                Static("l", classes="help-key"),
                Static("Logs - Browse audit log entries", classes="help-description"),
            ),
            Horizontal(
                Static("m", classes="help-key"),
                Static("Monitor - Real-time log monitoring", classes="help-description"),
            ),
            Horizontal(
                Static("s", classes="help-key"),
                Static("Stats - Statistics and analytics", classes="help-description"),
            ),
            Horizontal(
                Static("a", classes="help-key"),
                Static("Alerts - Manage alert rules", classes="help-description"),
            ),
            Horizontal(
                Static("c", classes="help-key"),
                Static("Config - View settings", classes="help-description"),
            ),
            Static("\n[bold]Actions[/bold]", classes="help-section"),
            Horizontal(
                Static("/", classes="help-key"),
                Static("Focus search/filter", classes="help-description"),
            ),
            Horizontal(
                Static("r", classes="help-key"),
                Static("Refresh data", classes="help-description"),
            ),
            Horizontal(
                Static("e", classes="help-key"),
                Static("Export current data", classes="help-description"),
            ),
            Horizontal(
                Static("Enter", classes="help-key"),
                Static("View entry details", classes="help-description"),
            ),
            Static("\n[bold]General[/bold]", classes="help-section"),
            Horizontal(
                Static("?", classes="help-key"),
                Static("Show this help", classes="help-description"),
            ),
            Horizontal(
                Static("Esc", classes="help-key"),
                Static("Close modal/dialog", classes="help-description"),
            ),
            Horizontal(
                Static("q", classes="help-key"),
                Static("Quit application", classes="help-description"),
            ),
            Static("\n[dim]Press Esc or ? to close[/dim]"),
            id="help-overlay",
        )


class CJAAuditApp(App):
    """Main TUI application for CJA Audit Log Monitor."""

    TITLE = "CJA Audit Log Monitor"
    CSS_PATH = "styles.tcss"

    BINDINGS = [
        Binding("d", "switch_screen('dashboard')", "dashboard"),
        Binding("l", "switch_screen('logs')", "logs"),
        Binding("m", "switch_screen('monitor')", "monitor"),
        Binding("s", "switch_screen('stats')", "stats"),
        Binding("a", "switch_screen('alerts')", "alerts"),
        Binding("c", "switch_screen('settings')", "config"),
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
                Static("▸ dashboard", id="nav-dashboard", classes="nav-item active"),
                Static("  logs", id="nav-logs", classes="nav-item"),
                Static("  monitor", id="nav-monitor", classes="nav-item"),
                Static("  stats", id="nav-stats", classes="nav-item"),
                Static("  alerts", id="nav-alerts", classes="nav-item"),
                Static("  config", id="nav-settings", classes="nav-item"),
                id="sidebar",
            ),
            ContentSwitcher(id="main-content"),
        )
        yield Footer()

    _STATUS_DOT = {"connecting": "$warning", "connected": "$success", "disconnected": "$danger"}

    def _status_row_text(
        self, status: ConnectionStatus = "connecting", detail: str = ""
    ) -> str:
        """Build the top status row content."""
        color = self._STATUS_DOT[status]
        if not detail:
            org = self.state.settings.org_id
            detail = f"org {org}" if org else ""
        text = f"cja-audit-log-monitor · [{color}]●[/{color}] {status}"
        if detail:
            text += f" · [$text-muted]{escape(detail)}[/$text-muted]"
        return text

    def set_connection_status(self, status: ConnectionStatus, detail: str = "") -> None:
        """Show the API connection state in the header row.

        Args:
            status: One of ``connecting``, ``connected`` or ``disconnected``.
            detail: Org id, or the error when disconnected.
        """
        self.query_one("#status-row", Static).update(self._status_row_text(status, detail))

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

        # Show dashboard by default
        await self._show_screen("dashboard")

    async def _show_screen(self, screen_name: str) -> None:
        """Show a screen in the main content area.

        Args:
            screen_name: Name of screen to show.
        """
        switcher = self.query_one("#main-content", ContentSwitcher)

        # Update navigation item states (the displayed label may differ from
        # the screen id — e.g. nav-settings shows "config").
        for item in self.query("#sidebar .nav-item"):
            label = self.NAV_LABELS.get(item.id, "")
            is_active = item.id == f"nav-{screen_name}"
            item.set_class(is_active, "active")
            prefix = "▸ " if is_active else "  "
            item.update(f"{prefix}{label}")

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

    def action_switch_screen(self, screen_name: str) -> None:
        """Switch to a different screen."""
        self.call_later(self._show_screen, screen_name)

    def action_refresh(self) -> None:
        """Refresh current screen data."""
        self.notify("Refreshing...", severity="information")
        self.post_message(RefreshData())

    def on_refresh_data(self, event: "RefreshData") -> None:
        """Handle refresh requests by forwarding to the active screen."""
        current = self._screens.get(self._current_screen)
        refresh_method = getattr(current, "refresh_data", None)
        if callable(refresh_method):
            refresh_method()

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
