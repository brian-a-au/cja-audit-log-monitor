"""Base class for the views shown in the main content area."""

import logging
from collections.abc import Callable, Iterator
from typing import Literal, TypeVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widget import Widget
from textual.widgets import LoadingIndicator, Static

from ...auth import AuthenticationError
from ...client import APIError
from ...formatters import literal, resolve_tcss_markup
from ..state import AppState
from ..widgets.stats_panel import ActionBarChart, HourlyChart

logger = logging.getLogger(__name__)

T = TypeVar("T")


def not_connected_message(error: str) -> str:
    """Empty-state copy shown when the API connection fails."""
    return resolve_tcss_markup(
        f"[$danger]●[/$danger] not connected · {literal(error)}\n"
        "[$text-muted]press c to open config, or run: "
        "cja-audit-log-monitor cli verify[/$text-muted]"
    )


ErrorKind = Literal["connection", "access", "rejected", "other"]

_ERROR_COPY: dict[ErrorKind, tuple[str, str]] = {
    "connection": (
        "not connected",
        "press c to open config, or run: cja-audit-log-monitor cli verify",
    ),
    "access": (
        "access denied",
        "check that the API credential has a CJA product profile and the right scopes",
    ),
    "rejected": (
        "request rejected",
        "check the filters or the number of days, then press r",
    ),
    "other": ("could not load data", "press r to try again"),
}


def classify_error(error: Exception) -> ErrorKind:
    """Sort a failed API call into the kind of problem the user has to fix."""
    if isinstance(error, AuthenticationError):
        return "connection"
    if isinstance(error, APIError):
        status = error.status_code
        if status is None or status == 401:
            return "connection"  # network failure, or the token was rejected
        if status == 403:
            return "access"
        if status in (400, 422):
            return "rejected"
    return "other"


def error_message(error: Exception) -> str:
    """Empty-state copy for a failed API call: what went wrong and what to do next."""
    if classify_error(error) == "connection":
        return not_connected_message(str(error))
    headline, hint = _ERROR_COPY[classify_error(error)]
    return resolve_tcss_markup(
        f"[$danger]●[/$danger] {headline} · {literal(str(error))}\n"
        f"[$text-muted]{hint}[/$text-muted]"
    )


def no_activity_message(days: int) -> str:
    """Empty-state copy shown when a time window has no entries."""
    return resolve_tcss_markup(
        f"[$text-muted]no audit activity in the last {days} days[/$text-muted]"
    )


def sample_note_text(shown: int, total: int) -> str | None:
    """Copy for when charts use only the newest entries; None when they use all of them."""
    if total <= shown:
        return None
    return resolve_tcss_markup(
        f"[$text-muted]charts and lists use the newest {shown:,} of {total:,} entries"
        "[/$text-muted]"
    )


def sample_note() -> Static:
    """An initially hidden line under the stat cards for the sample note."""
    note = Static("", classes="sample-note")
    note.display = False
    return note


def show_sample_note(view: Widget, shown: int, total: int) -> None:
    """Show or hide ``view``'s sample note for ``shown`` of ``total`` entries."""
    note = view.query_one(".sample-note", Static)
    text = sample_note_text(shown, total)
    note.display = text is not None
    note.update(text or "")


def stat_card(label: str, value_id: str) -> Vertical:
    """A small card with a muted label above a bold value."""
    return Vertical(
        Static(label, classes="stat-label"),
        Static("-", id=value_id, classes="stat-value"),
        classes="stat-card",
    )


class ContentView(Vertical):
    """A view mounted inside the app's ``#main-content`` ContentSwitcher.

    Views are plain widgets, not ``textual.screen.Screen`` objects: a Screen
    mounted as a child gets a zero-size region and renders nothing.
    """

    DEFAULT_CSS = """
    ContentView {
        width: 1fr;
        height: 1fr;
    }
    """

    def __init__(self, state: AppState, **kwargs) -> None:
        """Initialize the view.

        Args:
            state: Application state.
            **kwargs: Additional arguments for Vertical (e.g. ``id``).
        """
        super().__init__(**kwargs)
        self._state = state
        # Bumped by each run_load; a load whose number is no longer current is stale.
        self._load_generation = 0
        # One fetch thread per view; the newest request waiting for it (see run_load).
        self._fetch_running = False
        self._pending_fetch: Callable[[], None] | None = None

    def compose(self) -> ComposeResult:
        """Compose the view: header, an (initially hidden) empty state, then the body."""
        yield from self.compose_header()
        yield Static("", id="empty-state", classes="empty-state")
        with Vertical(id="view-body"):
            yield from self.compose_content()

    def compose_header(self) -> Iterator[Widget]:
        """Yield widgets that stay visible even when the empty state is shown."""
        yield from ()

    def compose_content(self) -> Iterator[Widget]:
        """Yield the view's widgets."""
        raise NotImplementedError

    def default_focus(self) -> Widget | None:
        """Widget to focus when the view is shown, so the view's own keys work.

        Return None to clear focus (nothing in a hidden view keeps it).
        """
        return None

    def set_empty_state(self, message: str | None) -> None:
        """Show ``message`` in place of the view body, or restore the body when None."""
        empty = self.query_one("#empty-state", Static)
        body = self.query_one("#view-body")
        if message is None:
            empty.display = False
            body.display = True
        else:
            empty.update(message)
            empty.display = True
            body.display = False

    def show_loading(self, loading: bool) -> None:
        """Show or hide the view's loading indicator, and put its charts in "loading…"."""
        for indicator in self.query(LoadingIndicator):
            indicator.display = loading
        for chart in self.query(ActionBarChart):
            chart.show_loading(loading)
        for chart in self.query(HourlyChart):
            chart.show_loading(loading)

    def run_load(
        self,
        fetch: Callable[[], T],
        apply: Callable[[T], None],
        on_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Load data off the UI thread and show it, unless a newer load started since.

        ``fetch`` runs in a thread worker and must not touch the UI. Its result goes
        to ``apply`` (or its exception to ``on_error``, default ``show_load_error``)
        on the UI thread. Each call supersedes the previous one: a superseded load's
        result or error is dropped, and only the newest load hides the loading
        indicator.

        A view runs one fetch at a time. A call made while a fetch runs waits as the
        pending load (replacing an older pending one) and starts when the running fetch
        ends. So a hung request ties up one thread, however often the user refreshes.
        """
        self._load_generation += 1
        generation = self._load_generation
        handle_error = on_error or self.show_load_error
        self.show_loading(True)

        def deliver(callback: Callable, value: object) -> None:
            if generation != self._load_generation:
                return  # superseded by a newer load
            try:
                callback(value)
            except Exception as error:  # a failure while showing data is shown too
                if callback is handle_error:
                    # Showing the error failed (e.g. the view is being rebuilt). Raising
                    # here would end the app, so log it and leave the view as it is.
                    logger.exception("Showing a load error failed")
                    return
                logger.exception("Applying loaded data failed")
                try:
                    handle_error(error)
                except Exception:
                    logger.exception("Showing a load error failed")
            finally:
                self.show_loading(False)

        def work() -> None:
            try:
                try:
                    result = fetch()
                except Exception as error:
                    self.app.call_from_thread(deliver, handle_error, error)
                else:
                    self.app.call_from_thread(deliver, apply, result)
            finally:
                try:
                    self.app.call_from_thread(self._fetch_ended)
                except Exception:  # the app has ended; nothing is left to start
                    pass

        if self._fetch_running:
            self._pending_fetch = work
            return
        self._start_fetch(work)

    def _start_fetch(self, work: Callable[[], None]) -> None:
        self._fetch_running = True
        self.run_worker(work, group="load", thread=True)

    def _fetch_ended(self) -> None:
        """The running fetch ended (UI thread): start the pending one, if any."""
        self._fetch_running = False
        work, self._pending_fetch = self._pending_fetch, None
        if work is not None:
            self._start_fetch(work)

    def cancel_loads(self) -> None:
        """Drop the result of any load in progress (e.g. one sent before a settings reload)."""
        self._load_generation += 1
        self.show_loading(False)

    def show_load_error(self, error: Exception) -> None:
        """Show why a load failed in place of the view body, and in the header."""
        self.app.note_api_error(error)
        self.set_empty_state(error_message(error))

    def on_settings_reloaded(self) -> None:
        """Hook called when the settings were re-read; take the new defaults here."""

    def on_content_mounted(self) -> None:
        """Hook called once, the first time the view is shown."""

    def refresh_data(self) -> bool | None:
        """Reload the view's data (bound to the ``r`` key).

        A view may return False when there was nothing to reload (the monitor does).
        """
