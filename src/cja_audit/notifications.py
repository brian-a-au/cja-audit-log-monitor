"""Notification handlers for alert delivery."""

import logging
from datetime import UTC, datetime
from typing import Any

import httpx

from .models import AuditLogEntry, NotificationConfig, WebhookConfig
from .utils import get_user_identifier

logger = logging.getLogger(__name__)


class NotificationError(Exception):
    """Raised when notification delivery fails."""

    pass


class NotificationManager:
    """Manages delivery of alert notifications."""

    def __init__(self, config: NotificationConfig | None = None) -> None:
        """Initialize notification manager.

        Args:
            config: Notification configuration.
        """
        self.config = config or NotificationConfig()
        self._client: httpx.Client | None = None
        self._failure_warned: dict[str, bool] = {}
        self._pending_warnings: list[str] = []

    @property
    def client(self) -> httpx.Client:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.Client(timeout=30.0)
        return self._client

    def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
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
                f"Notification delivery failed ({label}); "
                f"subsequent failures suppressed for this session — check logs."
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
                    "text": f"CJA Audit Alert: {rule_name}",
                },
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": message,
                },
            },
        ]

        if entry:
            user = get_user_identifier(entry)
            fields = [
                f"*Action:* {entry.action or 'N/A'}",
                f"*User:* {user}",
                f"*Component:* {entry.component_type or 'N/A'}",
                f"*Name:* {entry.component_name or entry.component_id or 'N/A'}",
            ]
            blocks.append({
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": "\n".join(fields),
                },
            })

            if entry.timestamp:
                ts_str = entry.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')
                blocks.append({
                    "type": "context",
                    "elements": [
                        {
                            "type": "mrkdwn",
                            "text": f"Occurred at {ts_str}",
                        }
                    ],
                })

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
        if not webhook.enabled:
            return False

        try:
            headers = {"Content-Type": "application/json"}
            if webhook.headers:
                headers.update(webhook.headers)

            response = self.client.request(
                method=webhook.method,
                url=webhook.url,
                headers=headers,
                json=payload,
                timeout=webhook.timeout,
            )
            response.raise_for_status()
            logger.info("Webhook notification sent to %s", webhook.url)
            self._mark_success(webhook.url)
            return True

        except httpx.HTTPError as e:
            logger.error("Failed to send webhook to %s: %s", webhook.url, e)
            self._mark_failure(webhook.url, webhook.url)
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

        payload = self._build_slack_payload(rule_name, message, entry)

        try:
            response = self.client.post(
                self.config.slack_webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )
            response.raise_for_status()
            logger.info("Slack notification sent")
            self._mark_success("slack")
            return True

        except httpx.HTTPError as e:
            logger.error("Failed to send Slack notification: %s", e)
            self._mark_failure("slack", "slack")
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
            payload = self._build_alert_payload(
                rule_name,
                message,
                entry,
                include_details=webhook.include_entry_details,
            )
            if self.send_webhook(webhook, payload):
                sent += 1

        # Send to Slack
        if self.config.slack_webhook_url:
            if self.send_slack(rule_name, message, entry):
                sent += 1

        return sent

    def notify_anomaly(self, anomaly: dict[str, Any]) -> int:
        """Send anomaly notifications to all configured channels.

        Args:
            anomaly: Anomaly data dictionary.

        Returns:
            Number of successful notifications sent.
        """
        if not self.config.notify_on_anomalies:
            return 0

        sent = 0
        payload = self._build_anomaly_payload(anomaly)

        # Send to webhooks
        for webhook in self.config.webhooks:
            if self.send_webhook(webhook, payload):
                sent += 1

        # Send to Slack
        if self.config.slack_webhook_url:
            slack_payload = {
                "blocks": [
                    {
                        "type": "header",
                        "text": {
                            "type": "plain_text",
                            "text": "CJA Audit Anomaly Detected",
                        },
                    },
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": anomaly.get("description", "Unknown anomaly"),
                        },
                    },
                ]
            }
            try:
                response = self.client.post(
                    self.config.slack_webhook_url,
                    json=slack_payload,
                    headers={"Content-Type": "application/json"},
                )
                response.raise_for_status()
                self._mark_success("slack")
                sent += 1
            except httpx.HTTPError as e:
                logger.error("Failed to send Slack anomaly notification: %s", e)
                self._mark_failure("slack", "slack")

        return sent

    def pop_first_failure(self) -> str | None:
        """Return and consume the next pending failure warning, or None.

        Returns:
            Warning string the first time per-session per-channel a failure occurred,
            otherwise None. Call after each notify_alert / notify_anomaly batch.
        """
        if self._pending_warnings:
            return self._pending_warnings.pop(0)
        return None

    def is_configured(self) -> bool:
        """Check if any notification channels are configured.

        Returns:
            True if at least one channel is configured.
        """
        return bool(self.config.webhooks) or bool(self.config.slack_webhook_url)
