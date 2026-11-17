"""Settings screen for viewing configuration."""

from collections.abc import Iterator

from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...formatters import resolve_tcss_markup
from .base import ContentView


class SettingsScreen(ContentView):
    """Screen for viewing and managing settings."""

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the settings content.
        """
        settings = self._state.settings

        # Connection section
        connection_section = Vertical(
            Static("CONNECTION STATUS", classes="section-label"),
            Static(id="connection-status"),
            classes="settings-section",
        )

        # API configuration section
        api_section = Vertical(
            Static("API CONFIGURATION", classes="section-label"),
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
            Static("AUTHENTICATION", classes="section-label"),
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
                    resolve_tcss_markup(
                        "[$success]yes[/$success]"
                        if settings.is_oauth_configured()
                        else "[$danger]no[/$danger]"
                    ),
                    classes="settings-value",
                ),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        # Defaults section
        defaults_section = Vertical(
            Static("DEFAULTS", classes="section-label"),
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

        # Notifications section
        notif = settings.notifications
        slack_state = "configured" if notif.slack_webhook_url else "not configured"
        webhook_count = len(notif.webhooks)
        notifications_section = Vertical(
            Static("NOTIFICATIONS", classes="section-label"),
            Horizontal(
                Static("[bold]Slack:[/bold]", classes="settings-label"),
                Static(slack_state, classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]Webhooks:[/bold]", classes="settings-label"),
                Static(f"{webhook_count} configured", classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]Notify on alerts:[/bold]", classes="settings-label"),
                Static("yes" if notif.notify_on_alerts else "no", classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("[bold]Notify on anomalies:[/bold]", classes="settings-label"),
                Static("yes" if notif.notify_on_anomalies else "no", classes="settings-value"),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        # Alert rules section
        alerts_section = Vertical(
            Static("ALERT RULES", classes="section-label"),
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
            Static("configuration", id="settings-title", classes="section-label"),
            connection_section,
            api_section,
            auth_section,
            defaults_section,
            notifications_section,
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
            self.app.set_connection_status("connected", f"org {result.get('org_id', '')}")
            status.update(
                resolve_tcss_markup(
                    f"[$success]●[/$success] connected\n"
                    f"  organization: {result.get('org_id', 'Unknown')}\n"
                    f"  api url: {result.get('api_url', 'Unknown')}\n"
                    f"  total logs available: {result.get('total_logs_available', 'N/A'):,}"
                )
            )
        else:
            error = result.get("error", "Unknown error")
            self.app.set_connection_status("disconnected", str(error))
            status.update(
                resolve_tcss_markup(f"[$danger]●[/$danger] disconnected\n  error: {error}")
            )

    def _hide_loading(self) -> None:
        """Hide loading indicator."""
        loading = self.query_one("#loading", LoadingIndicator)
        loading.display = False
