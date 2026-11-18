"""Alerts management screen."""

from collections.abc import Iterator

from textual.containers import Container, Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Checkbox, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...formatters import resolve_tcss_markup
from ...stats import build_date_range_query
from .base import ContentView


class AlertsScreen(ContentView):
    """Screen for managing alert rules."""

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the alerts content.
        """
        rule_cards = [self._create_rule_card(rule) for rule in self._state.alert_engine.rules]
        rules_list = Vertical(*rule_cards, id="rules-list")

        buttons = Horizontal(
            Button("test rules", id="test-rules", variant="primary", compact=True),
            Button("reset to defaults", id="reset-rules", compact=True),
            classes="toolbar",
        )

        yield Container(
            Static("alert rules", id="alerts-title", classes="section-label view-title"),
            Static(
                resolve_tcss_markup(
                    "[$text-muted]toggle rules on/off or test against recent data[/$text-muted]"
                )
            ),
            rules_list,
            buttons,
            Static("TEST RESULTS", classes="section-label"),
            Static(
                resolve_tcss_markup(
                    "[$text-muted]press test rules to check them against the last 24 hours"
                    "[/$text-muted]"
                ),
                id="test-results",
                classes="card",
            ),
            LoadingIndicator(id="alerts-loading"),
            id="alerts-container",
        )

    def refresh_data(self) -> None:
        """Refresh alert rules display."""
        self.run_worker(
            self._refresh_rules_list(),
            group="alerts-refresh",
            exclusive=True,
        )

    async def _refresh_rules_list(self) -> None:
        """Rebuild the alert rules list safely."""
        rules_list = self.query_one("#rules-list", Vertical)
        await rules_list.remove_children()
        rule_cards = [self._create_rule_card(rule) for rule in self._state.alert_engine.rules]
        if rule_cards:
            await rules_list.mount(*rule_cards)

    def _create_rule_card(self, rule) -> Container:
        """Create a rule card widget.

        Args:
            rule: AlertRule to display.

        Returns:
            Container with rule card content.
        """
        enabled_class = "rule-enabled" if rule.enabled else "rule-disabled"
        actions = (
            ", ".join(a.value for a in rule.actions).lower() if rule.actions else "all actions"
        )
        components = (
            ", ".join(c.value for c in rule.components).lower()
            if rule.components
            else "all components"
        )
        if len(components) > 40:
            components = components[:39] + "…"
        noun = "event" if rule.threshold_count == 1 else "events"
        window = f"{rule.threshold_count} {noun} / {rule.threshold_window_minutes} min"
        details = f"{window} · {actions} · {components}"

        return Vertical(
            Horizontal(
                Checkbox(rule.name, value=rule.enabled, id=f"rule-{rule.name}", compact=True),
                Static(
                    resolve_tcss_markup(f"[$text-muted]{rule.description or ''}[/$text-muted]"),
                    classes="rule-description",
                ),
                classes="rule-header",
            ),
            Static(resolve_tcss_markup(f"[$text-muted]{details}[/$text-muted]")),
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
            self.set_loading(True)
            self.run_worker(self._test_rules(), exclusive=True, thread=True)
        elif event.button.id == "reset-rules":
            self._reset_rules()

    def _reset_rules(self) -> None:
        """Reset rules to defaults."""
        self._state._alert_engine = None  # Force recreation
        self.app.notify("Rules reset to defaults", severity="information")
        self.refresh_data()

    async def _test_rules(self) -> None:
        """Test rules against recent data."""
        worker = get_current_worker()

        try:
            query = build_date_range_query(1)
            entries = self._state.client.get_all_logs(query, max_entries=1000)

            if worker.is_cancelled:
                return

            if not entries:
                self.app.call_from_thread(
                    self._show_results,
                    "[dim]No audit logs found to test against[/dim]",
                )
                return

            fired = self._state.alert_engine.check_batch(entries)

            if fired:
                result_lines = [
                    resolve_tcss_markup(f"[$warning]found {len(fired)} alerts[/$warning]")
                ]
                for fa in fired[:10]:
                    result_lines.append(
                        resolve_tcss_markup(f"  [$danger]⚠[/$danger] {fa.rule_name}: {fa.message}")
                    )
                self.app.call_from_thread(self._show_results, "\n".join(result_lines))
            else:
                self.app.call_from_thread(
                    self._show_results,
                    resolve_tcss_markup(
                        f"[$success]no alerts triggered[/$success] "
                        f"(tested against {len(entries)} entries)"
                    ),
                )

        except Exception as e:
            self.app.call_from_thread(self.app.note_api_error, e)
            self.app.call_from_thread(self._show_error, str(e))
        finally:
            self.app.call_from_thread(self.set_loading, False)

    def _show_results(self, text: str) -> None:
        """Show test results."""
        self.query_one("#test-results", Static).update(text)

    def _show_error(self, error: str) -> None:
        """Show error message."""
        self.app.notify(f"Error: {error}", severity="error")

