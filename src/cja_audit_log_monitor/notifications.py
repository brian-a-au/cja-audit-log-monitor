"""Notification handlers for alert delivery."""

import hashlib
import logging
import socket
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import AuditLogEntry, NotificationConfig, WebhookConfig
from .utils import get_user_identifier, redact_url

logger = logging.getLogger(__name__)


# The longest a Slack send may take, start to end. A webhook uses its own timeout.
SLACK_DEADLINE = 30.0

# Slack's limits: a header holds 150 characters and a section 3,000.
SLACK_HEADER_MAX = 150
SLACK_SECTION_MAX = 3000


def slack_escape(text: str) -> str:
    """Escape ``&``, ``<`` and ``>`` so Slack shows text as is, with no mentions or links.

    Line breaks become spaces, so a name cannot start a line that looks like a field.
    """
    text = text.replace("\r\n", " ").replace("\n", " ").replace("\r", " ")
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _cut(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "\u2026"


class _RedactWebhookUrls(logging.Filter):
    """Replace configured webhook URLs in httpx's own request log lines.

    httpx logs every request URL at INFO, which would put a webhook secret in the logs.
    """

    def __init__(self) -> None:
        super().__init__()
        self._secret_urls: set[str] = set()

    def add(self, url: str) -> None:
        self._secret_urls.add(url)
        try:
            self._secret_urls.add(str(httpx.URL(url)))
        except Exception:
            pass

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and self._secret_urls:
            record.args = tuple(
                redact_url(str(a)) if str(a) in self._secret_urls else a for a in record.args
            )
        return True


_url_redactor = _RedactWebhookUrls()
logging.getLogger("httpx").addFilter(_url_redactor)


def _describe_error(error: Exception) -> str:
    """Describe a request error without its message, which may contain the URL."""
    response = getattr(error, "response", None)
    status = getattr(response, "status_code", None)
    name = type(error).__name__
    return f"{name} (HTTP {status})" if status else name


class _Deadline:
    """Shut a send's socket down once its overall deadline passes.

    httpx timeouts apply to each read, so a server that sends its reply one byte at a
    time never trips them. httpx's ``trace`` hook hands over each new connection's
    stream; when the timer fires, shutting that socket down wakes the blocked read,
    which then fails.
    """

    def __init__(self, seconds: float) -> None:
        self.seconds = seconds
        self.expired = False
        self._lock = threading.Lock()
        self._sockets: list[socket.socket] = []
        self._timer = threading.Timer(seconds, self._expire)
        self._timer.daemon = True

    def __enter__(self) -> "_Deadline":
        self._timer.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self._timer.cancel()

    def trace(self, event: str, info: dict[str, Any]) -> None:
        """httpx trace hook: keep the socket of each connection this send opens."""
        if event not in ("connection.connect_tcp.complete", "connection.start_tls.complete"):
            return
        stream = info.get("return_value")
        sock = stream.get_extra_info("socket") if stream is not None else None
        if sock is None:
            return
        with self._lock:
            self._sockets.append(sock)
            expired = self.expired
        if expired:  # the deadline passed while connecting
            self._shut(sock)

    def _expire(self) -> None:
        with self._lock:
            self.expired = True
            sockets = list(self._sockets)
        for sock in sockets:
            self._shut(sock)

    @staticmethod
    def _shut(sock: socket.socket) -> None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already closed


class NotificationManager:
    """Manages delivery of alert notifications."""

    def __init__(self, config: NotificationConfig | None = None) -> None:
        """Initialize notification manager.

        Args:
            config: Notification configuration.
        """
        self.config = config or NotificationConfig()
        self._client: httpx.Client | None = None
        self._closed = False
        self._failure_warned: dict[str, bool] = {}
        self._pending_warnings: list[str] = []

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            for webhook in self.config.webhooks:
                _url_redactor.add(webhook.url)
            if self.config.slack_webhook_url:
                _url_redactor.add(self.config.slack_webhook_url)
            # No kept-alive connections: each send opens its own, so the deadline's
            # trace hook always sees the socket it may have to shut down.
            self._client = httpx.Client(
                timeout=SLACK_DEADLINE, limits=httpx.Limits(max_keepalive_connections=0)
            )
        return self._client

    def close(self, wait: bool = True) -> None:
        """Close the HTTP client; later sends do nothing.

        With ``wait=False`` (quitting the TUI) a send in progress is left to finish: closing
        its socket would not wake the thread that waits on it.
        """
        self._closed = True
        if self._client and wait:
            self._client.close()
            self._client = None

    def __enter__(self) -> "NotificationManager":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def _mark_failure(self, channel_key: str, label: str) -> None:
        """Record a delivery failure; queue a warning if it's the first this session."""
        if not self._failure_warned.get(channel_key):
            self._failure_warned[channel_key] = True
            self._pending_warnings.append(
                f"Notification delivery failed ({label}). This warning shows again "
                f"if the channel fails after it works again."
            )

    def _mark_success(self, channel_key: str) -> None:
        """Clear failure flag so the next failure surfaces again."""
        self._failure_warned.pop(channel_key, None)

    def _build_alert_payload(
        self,
        rule_name: str,
        message: str,
        entry: AuditLogEntry | None = None,
        include_details: bool = True,
    ) -> dict[str, Any]:
        """Build a standard alert payload.

        Args:
            rule_name: Name of the triggered rule.
            message: Alert message.
            entry: Optional audit log entry that triggered the alert.
            include_details: Whether to include entry details.

        Returns:
            Dictionary payload for the notification.
        """
        payload: dict[str, Any] = {
            "alert_type": "cja_audit_alert",
            "rule_name": rule_name,
            "message": message,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        if entry and include_details:
            payload["entry"] = {
                "id": entry.id,
                "action": entry.action,
                "component_type": entry.component_type,
                "component_id": entry.component_id,
                "component_name": entry.component_name,
                "user": get_user_identifier(entry),
                "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                "description": entry.description,
            }

        return payload

    def _build_slack_payload(
        self,
        rule_name: str,
        message: str,
        entry: AuditLogEntry | None = None,
    ) -> dict[str, Any]:
        """Build a Slack-formatted payload.

        Args:
            rule_name: Name of the triggered rule.
            message: Alert message.
            entry: Optional audit log entry.

        Returns:
            Slack message payload.
        """
        blocks = [
            {
                "type": "header",
                "text": {
                    "type": "plain_text",
                    "text": _cut(f"CJA Audit Alert: {rule_name}", SLACK_HEADER_MAX),
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": _cut(slack_escape(message), SLACK_SECTION_MAX),
                },
            },
        ]

        if entry:
            user = slack_escape(get_user_identifier(entry))
            name = entry.component_name or entry.component_id or "N/A"
            fields = [
                f"*Action:* {slack_escape(str(entry.action or 'N/A'))}",
                f"*User:* {user}",
                f"*Component:* {slack_escape(str(entry.component_type or 'N/A'))}",
                f"*Name:* {slack_escape(str(name))}",
            ]
            blocks.append(
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": "\n".join(fields),
                    },
                }
            )

            if entry.timestamp:
                ts_str = entry.timestamp.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
                blocks.append(
                    {
                        "type": "context",
                        "elements": [
                            {
                                "type": "mrkdwn",
                                "text": f"Occurred at {ts_str}",
                            }
                        ],
                    }
                )

        return {"blocks": blocks}

    def _build_anomaly_payload(
        self,
        anomaly: dict[str, Any],
    ) -> dict[str, Any]:
        """Build payload for an anomaly notification.

        Args:
            anomaly: Anomaly data dictionary.

        Returns:
            Dictionary payload for the notification.
        """
        return {
            "alert_type": "cja_audit_anomaly",
            "anomaly_type": anomaly.get("type"),
            "description": anomaly.get("description"),
            "details": anomaly,
            "timestamp": datetime.now(UTC).isoformat(),
        }

    def _deliver(
        self,
        method: str,
        url: str,
        headers: dict[str, str],
        payload: dict[str, Any],
        timeout: float | None = None,
    ) -> None:
        """Send ``payload`` and raise ``httpx.HTTPStatusError`` unless the status is 2xx.

        Only the status matters, so the response body is never read: a huge body, or one
        that never ends, cannot hold up the poll that raised the alert. Redirects are not
        followed, so a redirect cannot send the alert somewhere else.

        The whole send must end within ``timeout`` (``SLACK_DEADLINE`` when None). Past
        that it raises ``httpx.TimeoutException``, even if the server keeps sending.
        """
        kwargs: dict[str, Any] = {"headers": headers, "json": payload}
        if timeout is not None:
            kwargs["timeout"] = timeout
        deadline = _Deadline(SLACK_DEADLINE if timeout is None else timeout)
        kwargs["extensions"] = {"trace": deadline.trace}
        try:
            with deadline, self.client.stream(method, url, **kwargs) as response:
                response.raise_for_status()
        except httpx.HTTPError:
            if deadline.expired:
                raise httpx.TimeoutException(f"no reply within {deadline.seconds:g}s") from None
            raise

    def send_webhook(
        self,
        webhook: WebhookConfig,
        payload: dict[str, Any],
    ) -> bool:
        """Send notification to a webhook.

        Args:
            webhook: Webhook configuration.
            payload: Payload to send.

        Returns:
            True if successful.
        """
        if not webhook.enabled or self._closed:
            return False

        try:
            headers = {"Content-Type": "application/json"}
            if webhook.headers:
                headers.update(webhook.headers)

            _url_redactor.add(webhook.url)
            self._deliver(webhook.method, webhook.url, headers, payload, webhook.timeout)
            logger.info("Webhook notification sent to %s", redact_url(webhook.url))
            self._mark_success(self._webhook_key(webhook))
            return True

        except (httpx.HTTPError, httpx.InvalidURL) as e:
            # str(e) can embed the full URL, so log only the type, status and host.
            label = redact_url(webhook.url)
            logger.error("Failed to send webhook to %s: %s", label, _describe_error(e))
            key = self._webhook_key(webhook)
            self._mark_failure(key, f"{key.replace(':', ' ')} ({label})")
            return False

    def send_slack(
        self,
        rule_name: str,
        message: str,
        entry: AuditLogEntry | None = None,
    ) -> bool:
        """Send notification to Slack.

        Args:
            rule_name: Name of the triggered rule.
            message: Alert message.
            entry: Optional audit log entry.

        Returns:
            True if successful.
        """
        if not self.config.slack_webhook_url:
            return False

        return self._post_slack(self._build_slack_payload(rule_name, message, entry))

    def _post_slack(self, payload: dict[str, Any]) -> bool:
        """Post a payload to the Slack webhook, tracking failures without leaking the URL."""
        url = self.config.slack_webhook_url
        if not url or self._closed:
            return False
        _url_redactor.add(url)
        try:
            self._deliver("POST", url, {"Content-Type": "application/json"}, payload)
            logger.info("Slack notification sent")
            self._mark_success("slack")
            return True

        except (httpx.HTTPError, httpx.InvalidURL) as e:
            logger.error("Failed to send Slack notification: %s", _describe_error(e))
            self._mark_failure("slack", f"slack ({redact_url(url)})")
            return False

    def notify_alert(
        self,
        rule_name: str,
        message: str,
        entry: AuditLogEntry | None = None,
    ) -> int:
        """Send alert notifications to all configured channels.

        Args:
            rule_name: Name of the triggered rule.
            message: Alert message.
            entry: Optional audit log entry.

        Returns:
            Number of successful notifications sent.
        """
        if not self.config.notify_on_alerts:
            return 0

        sent = 0

        # Send to webhooks
        for webhook in self.config.webhooks:

            def send(webhook: WebhookConfig = webhook) -> bool:
                payload = self._build_alert_payload(
                    rule_name,
                    message,
                    entry,
                    include_details=webhook.include_entry_details,
                )
                return self.send_webhook(webhook, payload)

            if self._guarded(self._webhook_key(webhook), webhook.url, send):
                sent += 1

        # Send to Slack
        url = self.config.slack_webhook_url
        if url and self._guarded("slack", url, lambda: self.send_slack(rule_name, message, entry)):
            sent += 1

        return sent

    def _guarded(self, key: str, url: str, send: Callable[[], bool]) -> bool:
        """Run one channel's send; an unexpected error fails that channel only.

        Only the error type is logged: its message could hold the URL.
        """
        try:
            return send()
        except Exception as e:
            label = f"{key.replace(':', ' ')} ({redact_url(url)})"
            logger.error("Notification to %s failed: %s", label, type(e).__name__)
            self._mark_failure(key, label)
            return False

    def channels(self) -> list[str]:
        """Keys of the active channels: ``webhook:<n>`` (n counts from 1) and ``slack``."""
        keys = [
            f"webhook:{index}"
            for index, webhook in enumerate(self.config.webhooks, 1)
            if webhook.enabled
        ]
        if self.config.slack_webhook_url:
            keys.append("slack")
        return keys

    def notify_anomaly(self, anomaly: dict[str, Any], channels: set[str] | None = None) -> set[str]:
        """Send an anomaly to the active channels, or only to ``channels`` when given.

        Args:
            anomaly: Anomaly data dictionary.
            channels: Channel keys (see ``channels()``) to send to; None means all.

        Returns:
            The keys of the channels that accepted it.
        """
        if not self.config.notify_on_anomalies:
            return set()

        accepted: set[str] = set()
        payload = self._build_anomaly_payload(anomaly)

        for index, webhook in enumerate(self.config.webhooks, 1):
            key = f"webhook:{index}"
            if channels is not None and key not in channels:
                continue
            if self._guarded(key, webhook.url, lambda w=webhook: self.send_webhook(w, payload)):
                accepted.add(key)

        url = self.config.slack_webhook_url
        if url and (channels is None or "slack" in channels):

            def send_slack() -> bool:
                return self._post_slack(self._build_slack_anomaly_payload(anomaly))

            if self._guarded("slack", url, send_slack):
                accepted.add("slack")

        return accepted

    def _build_slack_anomaly_payload(self, anomaly: dict[str, Any]) -> dict[str, Any]:
        """Build a Slack payload for an anomaly, with its text escaped."""
        return {
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": "CJA Audit Anomaly Detected"},
                },
                {
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": slack_escape(str(anomaly.get("description", "Unknown anomaly"))),
                    },
                },
            ]
        }

    def _webhook_key(self, webhook: WebhookConfig) -> str:
        """``webhook:<n>``, n counting from 1 in the config, so two hooks on one host differ."""
        for index, configured in enumerate(self.config.webhooks, 1):
            if configured is webhook:
                return f"webhook:{index}"
        return f"webhook:{redact_url(webhook.url)}"

    def pop_failures(self) -> list[str]:
        """Return and consume every pending failure warning (one per failing channel)."""
        warnings, self._pending_warnings = self._pending_warnings, []
        return warnings

    def is_configured(self) -> bool:
        """Check if any active notification channels are configured.

        Returns:
            True if Slack or at least one enabled webhook is configured.
        """
        return self.config.has_active_channels


class AnomalyDedupFilter:
    """In-memory, per-session anomaly dedup by stable fingerprint, per channel.

    Fingerprint composition: SHA-256 over (anomaly type, all scalar identifying fields
    except description and known quantitative fields). Quantitative fields are excluded
    so a recurring anomaly whose count grew between scans still dedupes.

    An anomaly counts as sent to a channel only once that channel accepted it, so a
    failed channel gets it again next scan. A fingerprint is forgotten when a scan no
    longer reports it, so an anomaly that clears and comes back is sent again.
    """

    _EXCLUDED_FIELDS = frozenset(
        {
            "description",
            "action_count",
            "delete_count",
            "average",
        }
    )

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._sent: dict[str, set[str]] = {}

    def fingerprint(self, anomaly: dict[str, Any]) -> str:
        """Return a stable 16-char hex fingerprint for the anomaly."""
        items = sorted(
            (str(k), str(v)) for k, v in anomaly.items() if k not in self._EXCLUDED_FIELDS
        )
        serialized = "|".join(f"{k}={v}" for k, v in items)
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()[:16]

    def suppress_seen(self, anomalies: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Return only anomalies whose fingerprint is new this session.

        Adds returned items' fingerprints to the seen set as a side effect.
        Total: any dict shape is acceptable; missing fields fingerprint to a
        stable value.
        """
        out: list[dict[str, Any]] = []
        for anomaly in anomalies:
            fp = self.fingerprint(anomaly)
            if fp in self._seen:
                continue
            self._seen.add(fp)
            out.append(anomaly)
        return out

    def pending(
        self, anomalies: list[dict[str, Any]], channels: set[str]
    ) -> list[tuple[dict[str, Any], set[str]]]:
        """Each anomaly with the channels it has not reached yet (anomalies with none left
        are left out)."""
        out = []
        for anomaly in anomalies:
            todo = channels - self._sent.get(self.fingerprint(anomaly), set())
            if todo:
                out.append((anomaly, todo))
        return out

    def mark_sent(self, anomaly: dict[str, Any], channels: set[str]) -> None:
        """Record that ``channels`` accepted ``anomaly``."""
        self._sent.setdefault(self.fingerprint(anomaly), set()).update(channels)

    def forget_missing(self, anomalies: list[dict[str, Any]]) -> None:
        """Forget anomalies this scan did not report, so their return is news again."""
        current = {self.fingerprint(anomaly) for anomaly in anomalies}
        self._seen &= current
        self._sent = {fp: sent for fp, sent in self._sent.items() if fp in current}
