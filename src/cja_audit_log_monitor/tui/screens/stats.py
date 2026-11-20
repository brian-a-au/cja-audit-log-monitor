"""Statistics screen for analytics and visualizations."""

from collections.abc import Iterator
from datetime import datetime, timedelta

from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, LoadingIndicator, Static

from ...config import MAX_DAYS
from ...formatters import TCSS_TOKEN_HEX, fit_cells, literal, render_bar
from ...stats import (
    build_date_range_query,
    calculate_stats,
    get_daily_distribution,
    get_hourly_distribution,
    get_user_activity,
)
from ...utils import local_tz_name, zone_label
from ..state import AppState
from ..widgets import ActionBarChart, FittedStatic, HourlyChart
from .base import (
    ContentView,
    no_activity_message,
    sample_note,
    show_sample_note,
    stat_card,
)

STATS_SAMPLE = 5000


class _DaysInput(Input):
    """The days box. Esc leaves it, so the view's keys (d, l, ?, q) work again."""

    BINDINGS = [Binding("escape", "leave", "leave the box", show=False)]

    def action_leave(self) -> None:
        self.screen.set_focus(None)


class StatsView(ContentView):
    """View for viewing statistics and analytics."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize StatsView.

        Args:
            state: Application state.
            **kwargs: Additional arguments for the view.
        """
        super().__init__(state, **kwargs)
        self._daily: list[tuple[str, int]] = []
        self._users: list[tuple[str, int]] = []
        self._lists_loaded = False

    def compose_header(self) -> Iterator[Widget]:
        """Title and window control stay visible, so an empty window can be widened."""
        yield Static("statistics", id="stats-title", classes="section-label view-title")
        yield Horizontal(
            Label("days"),
            _DaysInput(
                value=str(self._state.stats_days), id="days-input", type="integer", compact=True
            ),
            Button("update", id="update-button", variant="primary", compact=True),
            id="stats-controls",
            classes="toolbar",
        )

    def compose_content(self) -> Iterator[Widget]:
        """Yield widgets for the stats body."""
        yield LoadingIndicator(id="stats-loading")
        yield Horizontal(
            stat_card("total entries", "stats-total"),
            stat_card("active users", "stats-users"),
            stat_card("period", "stats-period"),
            classes="dashboard-stats",
        )
        yield sample_note()
        yield Horizontal(
            Vertical(
                Static("ACTION DISTRIBUTION", classes="section-label"),
                ActionBarChart(id="stats-action-chart"),
                classes="stats-column",
            ),
            Vertical(
                Static(
                    f"HOURLY ACTIVITY · {local_tz_name()}",
                    id="stats-hourly-label",
                    classes="section-label",
                ),
                HourlyChart(id="stats-hourly-chart"),
                classes="stats-column",
            ),
            id="stats-charts-row",
            classes="stats-row",
        )
        yield Horizontal(
            Vertical(
                Static(
                    f"DAILY ACTIVITY · {local_tz_name()}",
                    id="stats-daily-label",
                    classes="section-label",
                ),
                FittedStatic(id="daily-chart", redraw=self._render_lists),
                classes="stats-column",
            ),
            Vertical(
                Static("USER RANKING", classes="section-label"),
                FittedStatic(id="user-ranking", redraw=self._render_lists),
                classes="stats-column",
            ),
            classes="stats-row",
        )

    def on_content_mounted(self) -> None:
        """Called after compose_content widgets are mounted."""
        self.refresh_data()

    def refresh_data(self) -> None:
        """Refresh statistics data."""
        days = self._state.stats_days
        self.run_load(lambda: self._fetch(days), lambda load: self._show_load(days, load))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "update-button":
            self._apply_days()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in the days box applies it, like the update button."""
        if event.input.id == "days-input":
            event.stop()
            self._apply_days()

    def on_settings_reloaded(self) -> None:
        """Show the reloaded default days and reload the statistics for them."""
        self.query_one("#days-input", Input).value = str(self._state.stats_days)
        self.refresh_data()

    def _apply_days(self) -> None:
        """Read the days box, show the value actually used, and reload."""
        box = self.query_one("#days-input", Input)
        try:
            days = max(1, int(box.value))
            if days > MAX_DAYS:
                self.app.notify(
                    f"days must be at most {MAX_DAYS:,} · using {MAX_DAYS:,}", severity="warning"
                )
            self._state.stats_days = min(days, MAX_DAYS)
        except ValueError:
            self._state.stats_days = self._state.settings.default_days
        box.value = str(self._state.stats_days)
        self.refresh_data()

    def _fetch(self, days: int) -> tuple | None:
        """Sample and analyze the last ``days`` days (worker thread); None when empty."""
        query = build_date_range_query(days)
        entries, total = self._state.client.get_logs_sample(query, max_entries=STATS_SAMPLE)
        if not entries:
            return None
        return (
            calculate_stats(entries),
            get_hourly_distribution(entries, local=True),
            get_daily_distribution(entries, local=True),
            get_user_activity(entries),
            total,
            zone_label(entry.timestamp for entry in entries),
        )

    def _show_load(self, days: int, load: tuple | None) -> None:
        """Show a finished load, or the no-activity message for an empty window."""
        self.app.note_api_ok()
        if load is None:
            self.set_empty_state(no_activity_message(days))
        else:
            self._update_display(*load)

    def _update_display(
        self,
        stats: dict,
        hourly: dict,
        daily: dict,
        users: list,
        total: int | None = None,
        zone: str | None = None,
    ) -> None:
        """Update all statistics displays."""
        self.set_empty_state(None)

        shown = stats.get("total_entries", 0)
        total = shown if total is None else max(total, shown)
        self.query_one("#stats-total", Static).update(f"{total:,}")
        show_sample_note(self, shown, total)
        self.query_one("#stats-users", Static).update(f"{len(users):,}")
        now = datetime.now().astimezone()
        start = now - timedelta(days=self._state.stats_days)
        self.query_one("#stats-period", Static).update(f"{start:%m-%d} → {now:%m-%d}")

        self.query_one("#stats-action-chart", ActionBarChart).update_data(
            stats.get("action_counts", {}), width=20
        )
        self.query_one("#stats-hourly-chart", HourlyChart).update_data(hourly)
        # The zones of the data: two names when it spans a daylight saving change.
        zone = zone or local_tz_name()
        self.query_one("#stats-hourly-label", Static).update(f"HOURLY ACTIVITY · {zone}")
        self.query_one("#stats-daily-label", Static).update(f"DAILY ACTIVITY · {zone}")

        self._daily = sorted(daily.items())[-14:]
        self._users = list(users[:10])
        self._lists_loaded = True
        self._render_lists()

    def _render_lists(self) -> None:
        """Draw the daily chart and user ranking to fit their columns' current width."""
        if not self._lists_loaded:
            return
        daily_widget = self.query_one("#daily-chart", Static)
        # "MM-DD  " (7) + bar + " " + 5-digit count (6).
        bar_width = max(4, min(24, daily_widget.content_region.width - 13))
        primary = TCSS_TOKEN_HEX["$primary"]
        max_daily = max((count for _, count in self._daily), default=0)
        daily_lines = [
            f"{literal(day[5:])}  "
            f"[{primary}]{render_bar(count, max_daily, bar_width).ljust(bar_width)}"
            f"[/{primary}] {count:>5,}"
            for day, count in self._daily
        ]
        days = self._state.stats_days
        daily_widget.update("\n".join(daily_lines) or no_activity_message(days))

        ranking_widget = self.query_one("#user-ranking", Static)
        # "NN. " (4) + name + " " + 5-digit count (6), plus one blank cell at the edge.
        name_width = max(8, min(32, ranking_widget.content_region.width - 11))
        user_lines = []
        for rank, (user, count) in enumerate(self._users, 1):
            user_lines.append(f"{rank:>2}. {literal(fit_cells(user, name_width))} {count:>5,}")
        ranking_widget.update("\n".join(user_lines) or no_activity_message(days))
