"""Alert card widget for displaying alert notifications."""

from textual.app import ComposeResult
from textual.widgets import Static

from ...formatters import format_timestamp
from ...models import AuditLogEntry
from ...utils import get_user_identifier


class AlertCard(Static):
    """Widget for displaying a single alert notification."""

    def __init__(
        self,
        alert_name: str,
        message: str,
        entry: AuditLogEntry | None = None,
        **kwargs,
    ) -> None:
        """Initialize AlertCard.

        Args:
            alert_name: Name of the triggered alert rule.
            message: Alert message.
            entry: Optional related audit log entry.
            **kwargs: Additional arguments for Static.
        """
        super().__init__(**kwargs)
        self._alert_name = alert_name
        self._message = message
        self._entry = entry

    def compose(self) -> ComposeResult:
        """Compose alert card widgets."""
        yield Static(f"[bold red]⚠ {self._alert_name}[/bold red]", classes="alert-title")
        yield Static(self._message, classes="alert-message")

        if self._entry:
            yield Static(
                f"Time: {format_timestamp(self._entry.timestamp)}\n"
                f"User: {get_user_identifier(self._entry, default='-')}\n"
                f"Action: {self._entry.action}\n"
                f"Component: {self._entry.component_type} - "
                f"{self._entry.component_name or self._entry.component_id}",
                classes="alert-details",
            )


class AlertSummary(Static):
    """Widget for displaying alert summary."""

    def __init__(self, **kwargs) -> None:
        """Initialize AlertSummary."""
        super().__init__(**kwargs)
        self._alerts: list[tuple[str, str]] = []

    def add_alert(self, name: str, message: str) -> None:
        """Add an alert to the summary.

        Args:
            name: Alert rule name.
            message: Alert message.
        """
        self._alerts.append((name, message))
        # Keep only last 10
        self._alerts = self._alerts[-10:]
        self._refresh_display()

    def clear_alerts(self) -> None:
        """Clear all alerts."""
        self._alerts.clear()
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the alert display."""
        if not self._alerts:
            self.update("[dim]No recent alerts[/dim]")
            return

        lines = [f"[bold]Recent Alerts ({len(self._alerts)})[/bold]"]
        for name, message in reversed(self._alerts):
            lines.append(f"  [red]⚠[/red] {name}: {message[:50]}...")
        self.update("\n".join(lines))
