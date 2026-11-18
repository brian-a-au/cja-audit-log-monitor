"""Alerts management screen."""

from collections.abc import Iterator

from textual.containers import Container, Horizontal, Vertical
from textual.markup import escape
from textual.widget import Widget
from textual.widgets import Button, Checkbox, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...formatters import resolve_tcss_markup
from ...stats import build_date_range_query
from .base import ContentView


class AlertsScreen(ContentView):
    """Screen for managing alert rules."""

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        # Widget ids are positional (rule-0, rule-1...) so any rule name is safe.
        self._rule_names: dict[str, str] = {}

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for embedding in main content area.

        Yields:
            Widgets for the alerts content.
        """
        rule_cards = self._build_rule_cards()
        rules_list = Vertical(*rule_cards, id="rules-list")

        buttons = Horizontal(
            Button("test rules", id="test-rules", variant="primary", compact=True),
            Button("reset rules", id="reset-rules", compact=True),
            classes="toolbar",
        )

        yield Container(
            Static("alert rules", id="alerts-title", classes="section-label view-title"),
            Static(
                resolve_tcss_markup(
                    "[$text-muted]toggle rules on/off or test against recent data[/$text-muted]"
                )
            ),
            Static(
                resolve_tcss_markup("[$text-muted]changes last until you quit[/$text-muted]")
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
        focused = self.app.focused
        focused_id = focused.id if focused is not None else None
        await rules_list.remove_children()
        rule_cards = self._build_rule_cards()
        if rule_cards:
            await rules_list.mount(*rule_cards)
        if focused_id and focused_id in self._rule_names:
            # Rebuilding drops focus; put it back on the same rule's checkbox.
            self.query_one(f"#{focused_id}", Checkbox).focus()

    def _build_rule_cards(self) -> list[Container]:
        """Build one card per live rule and refresh the id-to-name map."""
        rules = list(self._state.alert_engine.rules)
        self._rule_names = {f"rule-{i}": rule.name for i, rule in enumerate(rules)}
        return [self._create_rule_card(i, rule) for i, rule in enumerate(rules)]

    def _create_rule_card(self, index: int, rule) -> Container:
        """Create a rule card widget.

        Args:
            index: Position of the rule in the engine; used for widget ids.
            rule: AlertRule to display.

        Returns:
            Container with rule card content.
        """
        enabled_class = "rule-enabled" if rule.enabled else "rule-disabled"
        actions = (
            ", ".join(rule.actions).lower() if rule.actions else "all actions"
        )
        components = (
            ", ".join(rule.components).lower()
            if rule.components
            else "all components"
        )
        if len(components) > 40:
            components = components[:39] + "…"
        name = escape(rule.name)
        noun = "event" if rule.threshold_count == 1 else "events"
        window = f"{rule.threshold_count} {noun} / {rule.threshold_window_minutes} min"
        details = escape(f"{window} · {actions} · {components}")

        return Vertical(
            Horizontal(
                Checkbox(name, value=rule.enabled, id=f"rule-{index}", compact=True),
                Static(
                    resolve_tcss_markup(
                        f"[$text-muted]{escape(rule.description or '')}[/$text-muted]"
                    ),
                    classes="rule-description",
                ),
                classes="rule-header",
            ),
            Static(resolve_tcss_markup(f"[$text-muted]{details}[/$text-muted]")),
            classes=f"rule-card {enabled_class}",
            id=f"card-{index}",
        )

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        """Handle rule enable/disable toggle."""
        checkbox_id = event.checkbox.id
        if checkbox_id not in self._rule_names:
            return
        index = int(checkbox_id.removeprefix("rule-"))
        rules = self._state.alert_engine.rules
        if index >= len(rules):
            return
        rules[index].enabled = event.value
        verb = "Enabled" if event.value else "Disabled"
        self.app.notify(f"{verb} rule: {self._rule_names[checkbox_id]}", severity="information")

        # Update card styling
        card = self.query_one(f"#card-{index}")
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
        """Rebuild the rules from settings, undoing this session's toggles."""
        self._state.reset_alert_rules()
        self.app.notify("Rules reset", severity="information")
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

            fired = self._state.new_test_engine().check_batch(entries)

            if fired:
                result_lines = [
                    resolve_tcss_markup(f"[$warning]found {len(fired)} alerts[/$warning]")
                ]
                for fa in fired[:10]:
                    result_lines.append(
                        resolve_tcss_markup(
                            f"  [$danger]⚠[/$danger] "
                            f"{escape(fa.rule_name)}: {escape(fa.message)}"
                        )
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
        """Show a failed test run in the results box, plus a toast."""
        self._show_results(
            resolve_tcss_markup(f"[$danger]test failed:[/$danger] {escape(error)}")
        )
        self.app.notify(f"Error: {error}", severity="error")
