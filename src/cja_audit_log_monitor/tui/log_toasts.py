"""Show the package's warning log lines as toasts while the TUI runs.

The TUI has no log file, and Textual owns the terminal, so log lines on stderr would never
be seen. This handler shows each warning (the config file permission warning, unknown
settings, failed deliveries) in the app instead.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from textual.app import App

PACKAGE_LOGGER = "cja_audit_log_monitor"
# The same text is shown at most once in this many seconds.
REPEAT_SECONDS = 10.0


class ToastLogHandler(logging.Handler):
    """Send WARNING and higher records from the package logger to ``app.notify``.

    Records that arrive before the app is ready are kept and shown by ``flush_pending``.
    Records from worker threads reach the UI thread through ``app.call_from_thread``.
    """

    def __init__(self, app: App, pending: list[tuple[str, str]] | None = None) -> None:
        super().__init__(level=logging.WARNING)
        self.app = app
        self.ready = False
        self._pending: list[tuple[str, str]] = list(pending or [])
        self._last_shown: dict[str, float] = {}
        self._ui_thread = threading.get_ident()

    def emit(self, record: logging.LogRecord) -> None:
        toast = _as_toast(record)
        if toast is None:
            return
        text, severity = toast
        if not self.ready:
            self._pending.append((text, severity))
            return
        if threading.get_ident() == self._ui_thread:
            self._show(text, severity)
            return
        try:
            self.app.call_from_thread(self._show, text, severity)
        except Exception:  # the app is shutting down; nowhere to show it
            pass

    def flush_pending(self) -> None:
        """Mark the app ready (call on the UI thread) and show what was logged before."""
        self._ui_thread = threading.get_ident()
        self.ready = True
        pending, self._pending = self._pending, []
        for text, severity in pending:
            self._show(text, severity)

    def _show(self, text: str, severity: str) -> None:
        now = time.monotonic()
        last = self._last_shown.get(text)
        if last is not None and now - last < REPEAT_SECONDS:
            return
        self._last_shown[text] = now
        self.app.notify(text, severity=severity, markup=False)  # type: ignore[arg-type]


def _as_toast(record: logging.LogRecord) -> tuple[str, str] | None:
    """The text and severity of the toast for ``record``; None when it has no text."""
    try:
        text = record.getMessage()
    except Exception:
        return None
    return text, "error" if record.levelno >= logging.ERROR else "warning"


class _Collector(logging.Handler):
    """Keep each warning as the text and severity of a toast."""

    def __init__(self) -> None:
        super().__init__(level=logging.WARNING)
        self.found: list[tuple[str, str]] = []

    def emit(self, record: logging.LogRecord) -> None:
        toast = _as_toast(record)
        if toast is not None:
            self.found.append(toast)


@contextmanager
def collect() -> Iterator[list[tuple[str, str]]]:
    """Keep the package's warnings that are logged before the app exists.

    The settings are loaded before the TUI opens. The list goes to ``install`` as
    ``pending``, so those warnings show as toasts once the app is ready.
    """
    collector = _Collector()
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.addHandler(collector)
    try:
        yield collector.found
    finally:
        logger.removeHandler(collector)


def install(app: App, pending: list[tuple[str, str]] | None = None) -> ToastLogHandler:
    """Add a handler for ``app`` to the package logger and return it."""
    handler = ToastLogHandler(app, pending)
    logger = logging.getLogger(PACKAGE_LOGGER)
    logger.addHandler(handler)
    if logger.getEffectiveLevel() > logging.WARNING:
        logger.setLevel(logging.WARNING)
    return handler


def uninstall(handler: ToastLogHandler) -> None:
    """Remove ``handler`` from the package logger."""
    logging.getLogger(PACKAGE_LOGGER).removeHandler(handler)
