"""Alert card widget for displaying alert notifications."""

from textual.markup import escape
from textual.widgets import Static

from ...formatters import format_timestamp, resolve_tcss_markup
from ...models import AuditLogEntry
from ...utils import get_user_identifier, local_tz_name


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
        content = resolve_tcss_markup(f"[$danger]⚠ {alert_name}[/$danger]\n{message}")
        if entry:
            content += (
                f"\nTime: {format_timestamp(entry.timestamp, local=True)} {local_tz_name()}"
                f"\nUser: {get_user_identifier(entry, default='-')}"
                f"\nAction: {entry.action}"
                f"\nComponent: {entry.component_type} - "
                f"{entry.component_name or entry.component_id}"
            )
        super().__init__(content, **kwargs)


class AlertSummary(Static):
    """Widget for displaying alert summary."""

    def __init__(self, **kwargs) -> None:
        """Initialize AlertSummary."""
        super().__init__(**kwargs)
        self._alerts: list[tuple[str, str]] = []

    def on_mount(self) -> None:
        """Say there are no alerts until one arrives."""
        self._refresh_display()

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
            self.update(resolve_tcss_markup("[$text-muted]no alerts yet[/$text-muted]"))
            return

        lines = [f"recent alerts ({len(self._alerts)})"]
        for name, message in reversed(self._alerts):
            short = message if len(message) <= 60 else message[:59] + "…"
            lines.append(
                resolve_tcss_markup(f"[$danger]⚠[/$danger] {escape(name)}: {escape(short)}")
            )
        self.update("\n".join(lines))
