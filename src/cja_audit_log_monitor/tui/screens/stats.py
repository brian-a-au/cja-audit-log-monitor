"""Statistics screen for analytics and visualizations."""

from collections.abc import Iterator
from datetime import datetime, timedelta

from textual.containers import Horizontal, Vertical
from textual.widget import Widget
from textual.widgets import Button, Input, Label, LoadingIndicator, Static
from textual.worker import get_current_worker

from ...formatters import TCSS_TOKEN_HEX, render_bar
from ...stats import (
    build_date_range_query,
    calculate_stats,
    get_daily_distribution,
    get_hourly_distribution,
    get_user_activity,
)
from ...utils import local_tz_name
from ..state import AppState
from ..widgets import ActionBarChart, FittedStatic, HourlyChart
from .base import (
    ContentView,
    error_message,
    no_activity_message,
    sample_note,
    show_sample_note,
    stat_card,
)

STATS_SAMPLE = 5000


class StatsScreen(ContentView):
    """Screen for viewing statistics and analytics."""

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize StatsScreen.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Screen.
        """
        super().__init__(state, **kwargs)
        self._days = 7
        self._daily: list[tuple[str, int]] = []
        self._users: list[tuple[str, int]] = []
        self._lists_loaded = False

    def compose_header(self) -> Iterator[Widget]:
        """Title and window control stay visible, so an empty window can be widened."""
        yield Static("statistics", id="stats-title", classes="section-label view-title")
        yield Horizontal(
            Label("days"),
            Input(value="7", id="days-input", type="integer", compact=True),
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
        self.set_loading(True)
        self.run_worker(self._load_data(), exclusive=True, thread=True)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "update-button":
            try:
                self._days = int(self.query_one("#days-input", Input).value)
                if self._days < 1:
                    self._days = 1
            except ValueError:
                self._days = 7

            self.refresh_data()

    async def _load_data(self) -> None:
        """Load statistics data."""
        worker = get_current_worker()

        try:
            query = build_date_range_query(self._days)
            entries, total = self._state.client.get_logs_sample(query, max_entries=STATS_SAMPLE)

            if worker.is_cancelled:
                return

            if not entries:
                self.app.call_from_thread(self.app.note_api_ok)
                self.app.call_from_thread(self.set_empty_state, no_activity_message(self._days))
                return

            # Calculate all statistics
            stats = calculate_stats(entries)
            hourly = get_hourly_distribution(entries, local=True)
            daily = get_daily_distribution(entries, local=True)
            users = get_user_activity(entries)

            self.app.call_from_thread(self.app.note_api_ok)
            self.app.call_from_thread(self._update_display, stats, hourly, daily, users, total)

        except Exception as e:
            self.app.call_from_thread(self._show_error, e)
        finally:
            self.app.call_from_thread(self.set_loading, False)

    def _show_error(self, error: Exception) -> None:
        """Report a failed API call in the view, and in the header if it was a connection."""
        self.app.note_api_error(error)
        self.set_empty_state(error_message(error))

    def _update_display(
        self,
        stats: dict,
        hourly: dict,
        daily: dict,
        users: list,
        total: int | None = None,
    ) -> None:
        """Update all statistics displays."""
        self.set_empty_state(None)

        shown = stats.get("total_entries", 0)
        total = shown if total is None else max(total, shown)
        self.query_one("#stats-total", Static).update(f"{total:,}")
        show_sample_note(self, shown, total)
        self.query_one("#stats-users", Static).update(f"{len(users):,}")
        now = datetime.now().astimezone()
        start = now - timedelta(days=self._days)
        self.query_one("#stats-period", Static).update(f"{start:%Y-%m-%d} → {now:%Y-%m-%d}")

        self.query_one("#stats-action-chart", ActionBarChart).update_data(
            stats.get("action_counts", {}), width=20
        )
        self.query_one("#stats-hourly-chart", HourlyChart).update_data(hourly)
        # Refresh the zone name, which can change (daylight saving) in a long session.
        zone = local_tz_name()
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
            f"{day[5:]}  [{primary}]{render_bar(count, max_daily, bar_width).ljust(bar_width)}"
            f"[/{primary}] {count:>5,}"
            for day, count in self._daily
        ]
        daily_widget.update("\n".join(daily_lines) or no_activity_message(self._days))

        ranking_widget = self.query_one("#user-ranking", Static)
        # "NN. " (4) + name + " " + 5-digit count (6).
        name_width = max(8, min(32, ranking_widget.content_region.width - 10))
        user_lines = []
        for rank, (user, count) in enumerate(self._users, 1):
            name = user if len(user) <= name_width else user[: name_width - 1] + "…"
            user_lines.append(f"{rank:>2}. {name:<{name_width}} {count:>5,}")
        ranking_widget.update("\n".join(user_lines) or no_activity_message(self._days))




