"""Notifications against real local HTTP servers that misbehave.

Each server path acts like a webhook or Slack endpoint that is slow, rate limited,
broken, redirects, or sends a huge or endless body. Every failure must become a queued
warning and a log line, never an exception, a hang, or a log line with the URL secret.
"""

import logging
import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cja_audit_log_monitor.models import AuditLogEntry, NotificationConfig, WebhookConfig
from cja_audit_log_monitor.notifications import NotificationManager

SECRET = "T0KEN-S3CRET-abc123"


class _Handler(BaseHTTPRequestHandler):
    hits: list[str]  # set on the class by the fixture
    stop: threading.Event

    def log_message(self, *args) -> None:  # keep test output quiet
        pass

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        length = int(self.headers.get("Content-Length") or 0)
        self.rfile.read(length)
        kind = self.path.strip("/").split("/")[0]
        type(self).hits.append(kind)
        try:
            getattr(self, f"_{kind}")()
        except (BrokenPipeError, ConnectionResetError):
            pass  # the client hung up, which is what some tests want

    def _send(self, status: int, body: bytes = b"ok", **headers: str) -> None:
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name.replace("_", "-"), value)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _ok(self) -> None:
        self._send(200)

    def _slow(self) -> None:
        type(self).stop.wait(3)  # longer than the webhook timeout in the test
        self._send(200)

    def _limited(self) -> None:
        self._send(429, b"slow down", Retry_After="30")

    def _broken(self) -> None:
        self._send(500, f"internal error for /broken/{SECRET}".encode())

    def _redirect(self) -> None:
        port = self.server.server_address[1]
        self._send(302, b"", Location=f"http://127.0.0.1:{port}/ok/{SECRET}")

    def _huge(self) -> None:
        # 64 MiB announced; the client only needs the status line.
        size = 64 * 1024 * 1024
        self.send_response(200)
        self.send_header("Content-Length", str(size))
        self.end_headers()
        chunk = b"x" * 65536
        for _ in range(size // len(chunk)):
            if type(self).stop.is_set():
                return
            self.wfile.write(chunk)

    def _endless(self) -> None:
        # A body that never ends, one byte at a time, well inside the read timeout.
        self.send_response(200)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        while not type(self).stop.is_set():
            self.wfile.write(b"1\r\nx\r\n")
            self.wfile.flush()
            time.sleep(0.05)


@pytest.fixture
def server() -> Iterator[tuple[str, list[str]]]:
    hits: list[str] = []
    stop = threading.Event()
    handler = type("Handler", (_Handler,), {"hits": hits, "stop": stop})
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}", hits
    finally:
        stop.set()
        httpd.shutdown()
        httpd.server_close()


@pytest.fixture
def entry() -> AuditLogEntry:
    return AuditLogEntry(id="e1", action="DELETE", component_type="PROJECT", user_id="u1")


def _within(seconds: float, call):
    """Run ``call`` on a thread; fail the test if it has not returned in ``seconds``."""
    result: list = []
    errors: list[BaseException] = []

    def run() -> None:
        try:
            result.append(call())
        except BaseException as e:  # noqa: BLE001 (reported below)
            errors.append(e)

    thread = threading.Thread(target=run, daemon=True)
    started = time.monotonic()
    thread.start()
    thread.join(seconds)
    assert not thread.is_alive(), f"still waiting after {seconds}s"
    assert not errors, errors
    return result[0], time.monotonic() - started


def _webhook_manager(url: str, timeout: int = 1) -> NotificationManager:
    return NotificationManager(
        NotificationConfig(webhooks=[WebhookConfig(url=url, timeout=timeout)])
    )


def _slack_manager(url: str) -> NotificationManager:
    return NotificationManager(NotificationConfig(slack_webhook_url=url))


@pytest.fixture
def all_logs(caplog) -> pytest.LogCaptureFixture:
    """Every log line at DEBUG, with httpcore held at WARNING as the CLI sets it up."""
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.WARNING, logger="httpcore")
    return caplog


FAILING = ["slow", "limited", "broken", "redirect"]


@pytest.mark.parametrize("kind", FAILING)
def test_a_failing_webhook_is_a_warning_and_a_log_line(server, entry, all_logs, kind) -> None:
    base, hits = server
    manager = _webhook_manager(f"{base}/{kind}/{SECRET}")
    sent, took = _within(10, lambda: manager.notify_alert("rule", "message", entry))
    assert sent == 0
    assert took < 5
    warnings = manager.pop_failures()
    assert len(warnings) == 1
    assert "127.0.0.1" in warnings[0]
    assert "Failed to send webhook" in all_logs.text
    assert SECRET not in all_logs.text
    assert SECRET not in warnings[0]
    manager.close()


@pytest.mark.parametrize("kind", ["limited", "broken", "redirect"])
def test_a_failing_slack_is_a_warning_and_a_log_line(server, entry, all_logs, kind) -> None:
    base, hits = server
    manager = _slack_manager(f"{base}/{kind}/{SECRET}")
    sent, _ = _within(10, lambda: manager.notify_alert("rule", "message", entry))
    assert sent == 0
    warnings = manager.pop_failures()
    assert len(warnings) == 1 and "slack" in warnings[0]
    assert "Failed to send Slack notification" in all_logs.text
    assert SECRET not in all_logs.text
    manager.close()


def test_a_redirect_is_not_followed(server, entry) -> None:
    """Following it could send the alert, and the next URL's secret, somewhere else."""
    base, hits = server
    manager = _webhook_manager(f"{base}/redirect/{SECRET}")
    _within(10, lambda: manager.notify_alert("rule", "message", entry))
    assert hits == ["redirect"]
    manager.close()


@pytest.mark.parametrize("kind", ["huge", "endless"])
def test_a_huge_or_endless_body_does_not_block_the_send(server, entry, all_logs, kind) -> None:
    """Only the status matters, so the body is never read."""
    base, _ = server
    manager = _webhook_manager(f"{base}/{kind}/{SECRET}", timeout=2)
    sent, took = _within(10, lambda: manager.notify_alert("rule", "message", entry))
    assert sent == 1
    assert took < 5
    assert manager.pop_failures() == []
    assert SECRET not in all_logs.text
    manager.close()


@pytest.mark.parametrize("kind", ["huge", "endless"])
def test_slack_with_a_huge_or_endless_body_does_not_block(server, entry, kind) -> None:
    base, _ = server
    manager = _slack_manager(f"{base}/{kind}/{SECRET}")
    sent, took = _within(10, lambda: manager.notify_alert("rule", "message", entry))
    assert sent == 1
    assert took < 5
    manager.close()


def test_a_good_channel_still_works_after_a_bad_one(server, entry, all_logs) -> None:
    base, hits = server
    manager = NotificationManager(
        NotificationConfig(
            webhooks=[
                WebhookConfig(url=f"{base}/broken/{SECRET}", timeout=1),
                WebhookConfig(url=f"{base}/ok/{SECRET}", timeout=1),
            ],
            slack_webhook_url=f"{base}/limited/{SECRET}",
        )
    )
    sent, _ = _within(10, lambda: manager.notify_alert("rule", "message", entry))
    assert sent == 1
    assert hits == ["broken", "ok", "limited"]
    assert len(manager.pop_failures()) == 2
    assert SECRET not in all_logs.text
    manager.close()


def test_an_anomaly_to_a_failing_server_is_reported(server, all_logs) -> None:
    base, _ = server
    manager = NotificationManager(
        NotificationConfig(
            webhooks=[WebhookConfig(url=f"{base}/broken/{SECRET}", timeout=1)],
            slack_webhook_url=f"{base}/broken/{SECRET}",
            notify_on_anomalies=True,
        )
    )
    anomaly = {"type": "bulk_delete_single_user", "user": "u1", "description": "x"}
    accepted, _ = _within(10, lambda: manager.notify_anomaly(anomaly))
    assert accepted == set()
    assert len(manager.pop_failures()) == 2
    assert SECRET not in all_logs.text
    manager.close()


async def test_tui_monitor_toasts_each_failing_channel_without_the_url(
    server, mock_app_state, monkeypatch, all_logs
) -> None:
    """End to end: a poll fires an alert, every channel fails, the user sees toasts."""
    from rich.panel import Panel

    from cja_audit_log_monitor.alerts import FiredAlert
    from cja_audit_log_monitor.tui.app import CJAAuditApp

    from .test_tui import (
        _drive_poll,
        _monitor_entries,
        _page_zero_batches,
        _start_monitor_without_loop,
        _wait_for,
    )

    base, hits = server
    mock_app_state._notification_manager = NotificationManager(
        NotificationConfig(
            webhooks=[
                WebhookConfig(url=f"{base}/broken/{SECRET}", timeout=1),
                WebhookConfig(url=f"{base}/limited/{SECRET}", timeout=1),
                WebhookConfig(url=f"{base}/endless/{SECRET}", timeout=1),
            ],
            slack_webhook_url=f"{base}/redirect/{SECRET}",
        )
    )
    mock_app_state.client.get_logs.side_effect = _page_zero_batches(
        [_monitor_entries(0, 2), _monitor_entries(2, 1)]
    )
    new_entry = _monitor_entries(2, 1)[0]
    mock_app_state.alert_engine.check_batch.return_value = [
        FiredAlert(rule_name="r", message="m", entry=new_entry, panel=Panel(""), summary="r: 1")
    ]
    app = CJAAuditApp()
    app.state = mock_app_state
    async with app.run_test(size=(140, 40), notifications=True) as pilot:
        screen = await _start_monitor_without_loop(app, pilot, monkeypatch)
        await _drive_poll(screen, pilot)  # the first poll only seeds the seen keys
        await _drive_poll(screen, pilot)
        failures = lambda: [  # noqa: E731
            n.message for n in app._notifications if "Notification delivery failed" in n.message
        ]
        assert await _wait_for(lambda: len(failures()) == 3, pilot)
        assert sorted(hits) == ["broken", "endless", "limited", "redirect"]
        for message in failures():
            assert "127.0.0.1" in message
            assert SECRET not in message
        assert all(SECRET not in n.message for n in app._notifications)
        assert SECRET not in all_logs.text
        screen._stop_monitoring()
