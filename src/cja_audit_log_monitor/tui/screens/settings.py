"""Settings screen for viewing configuration."""

from collections.abc import Iterator

from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, LoadingIndicator, Static

from ...formatters import literal, resolve_tcss_markup
from ...utils import display_path
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
                Static("config file", classes="settings-label"),
                Static(literal(display_path(self._state.config_path)), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("api base url", classes="settings-label"),
                Static(literal(str(settings.api_base_url)), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("ims base url", classes="settings-label"),
                Static(literal(str(settings.ims_base_url)), classes="settings-value"),
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
                Static("organization id", classes="settings-label"),
                Static(literal(org_display), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("client id", classes="settings-label"),
                Static(literal(client_display), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("oauth configured", classes="settings-label"),
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
                Static("page size", classes="settings-label"),
                Static(str(settings.default_page_size), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("days", classes="settings-label"),
                Static(str(settings.default_days), classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("monitor interval", classes="settings-label"),
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
                Static("slack", classes="settings-label"),
                Static(slack_state, classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("webhooks", classes="settings-label"),
                Static(f"{webhook_count} configured", classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("notify on alerts", classes="settings-label"),
                Static("yes" if notif.notify_on_alerts else "no", classes="settings-value"),
                classes="settings-row",
            ),
            Horizontal(
                Static("notify on anomalies", classes="settings-label"),
                Static("yes" if notif.notify_on_anomalies else "no", classes="settings-value"),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        # Alert rules section
        alerts_section = Vertical(
            Static("ALERT RULES", classes="section-label"),
            Horizontal(
                Static("configured rules", classes="settings-label"),
                Static(str(len(settings.alert_rules)), classes="settings-value"),
                classes="settings-row",
            ),
            classes="settings-section",
        )

        buttons = Horizontal(
            Button("verify connection", id="verify-button", variant="primary", compact=True),
            Button("reload settings", id="reload-button", compact=True),
            classes="toolbar",
        )

        yield Container(
            LoadingIndicator(id="settings-loading"),
            Static("configuration", id="settings-title", classes="section-label view-title"),
            Container(
                connection_section,
                api_section,
                auth_section,
                defaults_section,
                notifications_section,
                alerts_section,
                id="settings-grid",
            ),
            buttons,
            id="settings-container",
        )

    def on_content_mounted(self) -> None:
        """Called after compose_content widgets are mounted."""
        self.refresh_data()

    def refresh_data(self) -> None:
        """Refresh connection status."""
        self.run_load(
            self._state.verify_connection,
            self._update_connection_status,
            lambda error: self._update_connection_status(
                {"connected": False, "error": str(error)}
            ),
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "verify-button":
            self.refresh_data()
        elif event.button.id == "reload-button":
            self._state.refresh_client()
            self.app.notify("Settings refreshed", severity="information")

    def _update_connection_status(self, result: dict) -> None:
        """Update connection status display."""
        status = self.query_one("#connection-status", Static)

        if result.get("connected") and result.get("authenticated"):
            self.app.set_connection_status("connected", f"org {result.get('org_id', '')}")
            status.update(
                resolve_tcss_markup(
                    f"[$success]●[/$success] connected\n"
                    f"  organization: {literal(str(result.get('org_id', 'Unknown')))}\n"
                    f"  api url: {literal(str(result.get('api_url', 'Unknown')))}\n"
                    f"  total logs available: {result.get('total_logs_available', 'N/A'):,}"
                )
            )
        else:
            error = result.get("error", "Unknown error")
            self.app.set_connection_status("disconnected", str(error))
            status.update(
                resolve_tcss_markup(
                    f"[$danger]●[/$danger] disconnected\n  error: {literal(str(error))}"
                )
            )

