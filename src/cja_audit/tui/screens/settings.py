"""Settings screen for viewing configuration."""

from collections.abc import Iterator

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widget import Widget
from textual.widgets import Button, LoadingIndicator, Static
from textual.worker import get_current_worker

from ..state import AppState


class SettingsScreen(Screen):
    """Screen for viewing and managing settings."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize SettingsScreen.

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
            Widgets for the settings content.
        """
        settings = self._state.settings

        # Connection section
        connection_section = Vertical(
            Static("[bold]Connection Status[/bold]"),
            Static(id="connection-status"),
            classes="settings-section",
        )

        # API configuration section
        api_section = Vertical(
            Static("[bold]API Configuration[/bold]"),
            Horizontal(
                Static("[bold]Config File:[/bold]", classes="settings-label"),
                Static(str(self._state.config_path), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]API Base URL:[/bold]", classes="settings-label"),
                Static(settings.api_base_url, classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]IMS Base URL:[/bold]", classes="settings-label"),
                Static(settings.ims_base_url, classes="settings-value"),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        # Authentication section
        org_display = f"{settings.org_id[:12]}..." if settings.org_id else "(not set)"
        client_display = f"{settings.client_id[:12]}..." if settings.client_id else "(not set)"
        auth_section = Vertical(
            Static("[bold]Authentication[/bold]"),
            Horizontal(
                Static("[bold]Organization ID:[/bold]", classes="settings-label"),
                Static(org_display, classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]Client ID:[/bold]", classes="settings-label"),
                Static(client_display, classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]OAuth Configured:[/bold]", classes="settings-label"),
                Static(
                    "[green]Yes[/green]" if settings.is_oauth_configured() else "[red]No[/red]",
                    classes="settings-value",
                ),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        # Defaults section
        defaults_section = Vertical(
            Static("[bold]Defaults[/bold]"),
            Horizontal(
                Static("[bold]Page Size:[/bold]", classes="settings-label"),
                Static(str(settings.default_page_size), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]Days:[/bold]", classes="settings-label"),
                Static(str(settings.default_days), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]Monitor Interval:[/bold]", classes="settings-label"),
                Static(f"{settings.monitor_interval} seconds", classes="settings-value"),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        # Alert rules section
        alerts_section = Vertical(
            Static("[bold]Alert Rules[/bold]"),
            Horizontal(
                Static("[bold]Configured Rules:[/bold]", classes="settings-label"),
                Static(str(len(settings.alert_rules)), classes="settings-value"),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        buttons = Horizontal(
            Button("Verify Connection", id="verify-button", variant="primary"),
            Button("Refresh Settings", id="refresh-button"),
        )

        yield Container(
            Static("[bold]Configuration[/bold]", id="settings-title"),
            connection_section,
            api_section,
            auth_section,
            defaults_section,
            alerts_section,
            buttons,
            LoadingIndicator(id="loading"),
            id="settings-container",
        )

    def on_content_mounted(self) -> None:
        """Called after compose_content widgets are mounted."""
        self.run_worker(self._check_connection(), exclusive=True, thread=True)

    def refresh_data(self) -> None:
        """Refresh connection status."""
        self.query_one("#loading", LoadingIndicator).display = True
        self.run_worker(self._check_connection(), exclusive=True, thread=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "verify-button":
            self.refresh_data()
        elif event.button.id == "refresh-button":
            self._state.refresh_client()
            self.app.notify("Settings refreshed", severity="information")

    async def _check_connection(self) -> None:
        """Verify API connection."""
        worker = get_current_worker()

        try:
            result = self._state.verify_connection()

            if worker.is_cancelled:
                return

            self.app.call_from_thread(self._update_connection_status, result)

        except Exception as e:
            self.app.call_from_thread(
                self._update_connection_status,
                {"connected": False, "error": str(e)},
            )
        finally:
            self.app.call_from_thread(self._hide_loading)

    def _update_connection_status(self, result: dict) -> None:
        """Update connection status display."""
        status = self.query_one("#connection-status", Static)

        if result.get("connected") and result.get("authenticated"):
            status.update(
                f"[green]● Connected[/green]\n"
                f"  Organization: {result.get('org_id', 'Unknown')}\n"
                f"  API URL: {result.get('api_url', 'Unknown')}\n"
                f"  Total logs available: {result.get('total_logs_available', 'N/A'):,}"
            )
        else:
            error = result.get("error", "Unknown error")
            status.update(f"[red]● Disconnected[/red]\n  Error: {error}")

    def _hide_loading(self) -> None:
        """Hide loading indicator."""
        loading = self.query_one("#loading", LoadingIndicator)
        loading.display = False
