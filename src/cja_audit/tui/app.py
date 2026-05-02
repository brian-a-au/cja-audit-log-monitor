"""Main TUI application for CJA Audit Log Monitor."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.message import Message
from textual.screen import Screen
from textual.widgets import Footer, Static

from .state import AppState


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
        Binding("d", "switch_screen('dashboard')", "Dashboard"),
        Binding("l", "switch_screen('logs')", "Logs"),
        Binding("m", "switch_screen('monitor')", "Monitor"),
        Binding("s", "switch_screen('stats')", "Stats"),
        Binding("a", "switch_screen('alerts')", "Alerts"),
        Binding("c", "switch_screen('settings')", "Config"),
        Binding("r", "refresh", "Refresh"),
        Binding("e", "export", "Export"),
        Binding("slash", "focus_search", "Search"),
        Binding("question_mark", "show_help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self, config_path: Path | None = None) -> None:
        """Initialize the TUI application.

        Args:
            config_path: Optional path to config file.
        """
        super().__init__()
        self.state = AppState(config_path)
        self._current_screen = "dashboard"
        self._screens: dict[str, Screen] = {}

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
            Container(id="main-content"),
        )
        yield Footer()

    def _status_row_text(self) -> str:
        """Build the top status row content."""
        org = self.state.settings.org_id or "—"
        return (
            "cja-audit · "
            "[$success]●[/$success] connected · "
            f"[$text-muted]org {org}[/$text-muted]"
        )

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

        self._screens = {
            "dashboard": DashboardScreen(self.state),
            "logs": LogBrowserScreen(self.state),
            "monitor": MonitorScreen(self.state),
            "stats": StatsScreen(self.state),
            "alerts": AlertsScreen(self.state),
            "settings": SettingsScreen(self.state),
        }

        # Show dashboard by default
        await self._show_screen("dashboard")

    async def _show_screen(self, screen_name: str) -> None:
        """Show a screen in the main content area.

        Args:
            screen_name: Name of screen to show.
        """
        content = self.query_one("#main-content", Container)
        await content.remove_children()

        # Update navigation item states (the displayed label may differ from
        # the screen id — e.g. nav-settings shows "config").
        for item in self.query("#sidebar .nav-item"):
            label = self.NAV_LABELS.get(item.id, "")
            is_active = item.id == f"nav-{screen_name}"
            item.set_class(is_active, "active")
            prefix = "▸ " if is_active else "  "
            item.update(f"{prefix}{label}")

        # Mount the screen widget directly so its event handlers and queries work.
        screen = self._screens.get(screen_name)
        if screen:
            await content.mount(screen)
            if hasattr(screen, "on_content_mounted"):
                screen.on_content_mounted()

        self._current_screen = screen_name

    async def on_click(self, event) -> None:
        """Handle clicks on sidebar nav items."""
        widget = event.widget
        if widget is None:
            return
        widget_id = getattr(widget, "id", None)
        if widget_id and widget_id.startswith("nav-"):
            screen_name = widget_id.replace("nav-", "")
            await self._show_screen(screen_name)

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

    def action_focus_search(self) -> None:
        """Focus the search input."""
        try:
            search = self.query_one("FilterBar Input")
            search.focus()
        except Exception:
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
