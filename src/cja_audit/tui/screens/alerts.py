"""Alerts management screen."""

from textual.app import ComposeResult
from textual.containers import Container, Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, Checkbox, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...stats import build_date_range_query
from ..state import AppState


class AlertsScreen(Screen):
    """Screen for managing alert rules."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize AlertsScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(**kwargs)
        self._state = state

    def compose(self) -> ComposeResult:
        """Compose alerts screen widgets."""
        with Container(id="alerts-container"):
            yield Static("[bold]Alert Rules Management[/bold]", id="alerts-title")

            yield Static("[dim]Toggle rules on/off or test against recent data[/dim]")

            with Vertical(id="rules-list"):
                for rule in self._state.alert_engine.rules:
                    yield self._create_rule_card(rule)

            with Horizontal():
                yield Button("Test Rules", id="test-rules", variant="primary")
                yield Button("Reset to Defaults", id="reset-rules")

            yield Static("[bold]Test Results[/bold]")
            yield Static(id="test-results")

            yield LoadingIndicator(id="loading")

    def _create_rule_card(self, rule) -> Container:
        """Create a rule card widget.

        Args:
            rule: AlertRule to display.

        Returns:
            Container with rule card content.
        """
        enabled_class = "rule-enabled" if rule.enabled else "rule-disabled"
        actions_str = ", ".join(a.value for a in rule.actions) if rule.actions else "All"
        components_str = ", ".join(c.value for c in rule.components) if rule.components else "All"

        return Vertical(
            Horizontal(
                Checkbox(rule.name, value=rule.enabled, id=f"rule-{rule.name}"),
                Static(f"[dim]{rule.description or ''}[/dim]"),
            ),
            Static(
                f"  Threshold: {rule.threshold_count} events in "
                f"{rule.threshold_window_minutes} minutes"
            ),
            Static(f"  Actions: {actions_str}"),
            Static(
                f"  Components: {components_str[:50]}"
                f"{'...' if len(components_str) > 50 else ''}"
            ),
            classes=f"rule-card {enabled_class}",
            id=f"card-{rule.name}",
        )

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle rule enable/disable toggle."""
        checkbox_id = event.checkbox.id
        if checkbox_id and checkbox_id.startswith("rule-"):
            rule_name = checkbox_id.replace("rule-", "")
            if event.value:
                self._state.alert_engine.enable_rule(rule_name)
                self.app.notify(f"Enabled rule: {rule_name}", severity="information")
            else:
                self._state.alert_engine.disable_rule(rule_name)
                self.app.notify(f"Disabled rule: {rule_name}", severity="information")

            # Update card styling
            card = self.query_one(f"#card-{rule_name}")
            card.remove_class("rule-enabled", "rule-disabled")
            card.add_class("rule-enabled" if event.value else "rule-disabled")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "test-rules":
            self.query_one("#loading").display = True
            self.run_worker(self._test_rules(), exclusive=True)
        elif event.button.id == "reset-rules":
            self._reset_rules()

    def _reset_rules(self) -> None:
        """Reset rules to defaults."""
        # Reset engine with default rules
        self._state._alert_engine = None  # Force recreation
        self.app.notify("Rules reset to defaults", severity="information")

        # Refresh display
        rules_list = self.query_one("#rules-list")
        rules_list.remove_children()
        for rule in self._state.alert_engine.rules:
            rules_list.mount(self._create_rule_card(rule))

    async def _test_rules(self) -> None:
        """Test rules against recent data."""
        worker = get_current_worker()

        try:
            # Fetch last day of data
            query = build_date_range_query(1)
            entries = self._state.client.get_all_logs(query, max_entries=1000)

            if worker.is_cancelled:
                return

            if not entries:
                self.call_from_thread(
                    self._show_results,
                    "[dim]No audit logs found to test against[/dim]",
                )
                return

            # Test rules
            alerts = self._state.alert_engine.check_batch(entries)

            if alerts:
                result_lines = [f"[yellow]Found {len(alerts)} alerts:[/yellow]"]
                for alert in alerts[:10]:
                    # Extract alert name from panel title
                    result_lines.append("  [red]⚠[/red] Alert triggered")
                self.call_from_thread(self._show_results, "\n".join(result_lines))
            else:
                self.call_from_thread(
                    self._show_results,
                    f"[green]No alerts triggered[/green] "
                    f"(tested against {len(entries)} entries)",
                )

        except Exception as e:
            self.call_from_thread(self._show_error, str(e))
        finally:
            self.call_from_thread(self._hide_loading)

    def _show_results(self, text: str) -> None:
        """Show test results."""
        self.query_one("#test-results", Static).update(text)

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.app.notify(f"Error: {error}", severity="error")

    def _hide_loading(self) -> None:
        """Hide loading indicator."""
        self.query_one("#loading").display = False

    async def compose_content(self):
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the alerts content.
        """
        # Build rules list
        rule_cards = [self._create_rule_card(rule) for rule in self._state.alert_engine.rules]
        rules_list = Vertical(*rule_cards, id="rules-list")

        buttons = Horizontal(
            Button("Test Rules", id="test-rules", variant="primary"),
            Button("Reset to Defaults", id="reset-rules"),
        )

        container = Container(
            Static("[bold]Alert Rules Management[/bold]", id="alerts-title"),
            Static("[dim]Toggle rules on/off or test against recent data[/dim]"),
            rules_list,
            buttons,
            Static("[bold]Test Results[/bold]"),
            Static(id="test-results"),
            LoadingIndicator(id="loading"),
            id="alerts-container",
        )

        yield container
