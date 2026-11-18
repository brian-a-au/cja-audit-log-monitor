"""Alert summary widget for the monitor view."""

from textual.widgets import Static

from ...formatters import literal, resolve_tcss_markup


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

    def _refresh_display(self) -> None:
        """Refresh the alert display."""
        if not self._alerts:
            self.update(resolve_tcss_markup("[$text-muted]no alerts yet[/$text-muted]"))
            return

        lines = [f"recent alerts ({len(self._alerts)})"]
        for name, message in reversed(self._alerts):
            short = message if len(message) <= 60 else message[:59] + "…"
            lines.append(
                resolve_tcss_markup(f"[$danger]⚠[/$danger] {literal(name)}: {literal(short)}")
            )
        self.update("\n".join(lines))
