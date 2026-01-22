"""Main TUI application for CJA Audit Log Monitor."""

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

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

    def compose(self) -> ComposeResult:
        """Create child widgets for the app."""
        yield Header()
        yield Horizontal(
            Vertical(
                Button("Dashboard", id="nav-dashboard", classes="active"),
                Button("Logs", id="nav-logs"),
                Button("Monitor", id="nav-monitor"),
                Button("Stats", id="nav-stats"),
                Button("Alerts", id="nav-alerts"),
                Button("Config", id="nav-settings"),
                id="sidebar",
            ),
            Container(id="main-content"),
        )
        yield Footer()

    async def on_mount(self) -> None:
        """Handle application mount."""
        # Import screens here to avoid circular imports
        from .screens import (
            AlertsScreen,
            DashboardScreen,
            LogBrowserScreen,
            MonitorScreen,
            SettingsScreen,
            StatsScreen,
        )

        # Install screens
        self.install_screen(DashboardScreen(self.state), name="dashboard")
        self.install_screen(LogBrowserScreen(self.state), name="logs")
        self.install_screen(MonitorScreen(self.state), name="monitor")
        self.install_screen(StatsScreen(self.state), name="stats")
        self.install_screen(AlertsScreen(self.state), name="alerts")
        self.install_screen(SettingsScreen(self.state), name="settings")

        # Show dashboard by default
        await self._show_screen("dashboard")

    async def _show_screen(self, screen_name: str) -> None:
        """Show a screen in the main content area.

        Args:
            screen_name: Name of screen to show.
        """
        content = self.query_one("#main-content", Container)
        content.remove_children()

        # Update navigation button states
        for button in self.query("#sidebar Button"):
            button.remove_class("active")
            if button.id == f"nav-{screen_name}":
                button.add_class("active")

        # Get screen widget and mount it
        screen = self.get_screen(screen_name)
        if hasattr(screen, "create_widget"):
            widget = await screen.create_widget()
            await content.mount(widget)
        else:
            # Fallback: push as modal screen
            self.push_screen(screen_name)

        self._current_screen = screen_name

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle navigation button presses."""
        button_id = event.button.id
        if button_id and button_id.startswith("nav-"):
            screen_name = button_id.replace("nav-", "")
            await self._show_screen(screen_name)

    def action_switch_screen(self, screen_name: str) -> None:
        """Switch to a different screen."""
        self.call_later(self._show_screen, screen_name)

    def action_refresh(self) -> None:
        """Refresh current screen data."""
        self.notify("Refreshing...", severity="information")
        # Post refresh message to current screen
        self.post_message(RefreshData())

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


class RefreshData:
    """Message to trigger data refresh."""

    pass


def run_tui(config_path: Path | None = None) -> None:
    """Run the TUI application.

    Args:
        config_path: Optional path to config file.
    """
    app = CJAAuditApp(config_path)
    app.run()
