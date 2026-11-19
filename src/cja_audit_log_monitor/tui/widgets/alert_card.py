"""Alert summary widget for the monitor view."""

from textual.widgets import Static

from ...formatters import literal, resolve_tcss_markup


class AlertSummary(Static):
    """Widget for displaying alert summary."""

    def __init__(self, **kwargs) -> None:
        """Initialize AlertSummary."""
        super().__init__(**kwargs)
        self._alerts: list[str] = []

    def on_mount(self) -> None:
        """Say there are no alerts until one arrives."""
        self._refresh_display()

    def add_alert(self, summary: str) -> None:
        """Add an alert's one line summary (``FiredAlert.summary``)."""
        self._alerts.append(summary)
        # Keep only last 10
        self._alerts = self._alerts[-10:]
        self._refresh_display()

    def _refresh_display(self) -> None:
        """Refresh the alert display."""
        if not self._alerts:
            self.update(resolve_tcss_markup("[$text-muted]no alerts yet[/$text-muted]"))
            return

        lines = [f"recent alerts ({len(self._alerts)})"]
        # "⚠ " takes 2 cells; cut each line to the width the widget has.
        room = max(20, (self.content_region.width or 62) - 2)
        for summary in reversed(self._alerts):
            short = summary if len(summary) <= room else summary[: room - 1] + "…"
            lines.append(resolve_tcss_markup(f"[$danger]⚠[/$danger] {literal(short)}"))
        self.update("\n".join(lines))

    def on_resize(self) -> None:
        """Cut the lines again for the new width."""
        if self._alerts:
            self._refresh_display()
