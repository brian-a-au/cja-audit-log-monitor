"""Tests for notifications module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from cja_audit.models import AuditLogEntry, NotificationConfig, WebhookConfig
from cja_audit.notifications import NotificationManager


@pytest.fixture
def sample_entry() -> AuditLogEntry:
    """Create a sample audit log entry."""
    return AuditLogEntry(
        id="test-123",
        action="DELETE",
        component_type="PROJECT",
        component_id="proj-456",
        component_name="Test Project",
        user_email="user@example.com",
        timestamp=datetime.now(UTC),
        description="Deleted project",
    )


@pytest.fixture
def webhook_config() -> WebhookConfig:
    """Create a sample webhook configuration."""
    return WebhookConfig(
        url="https://example.com/webhook",
        enabled=True,
        method="POST",
        timeout=30,
    )


@pytest.fixture
def notification_config(webhook_config: WebhookConfig) -> NotificationConfig:
    """Create a sample notification configuration."""
    return NotificationConfig(
        webhooks=[webhook_config],
        slack_webhook_url="https://hooks.slack.com/test",
        notify_on_alerts=True,
        notify_on_anomalies=True,
    )


class TestNotificationManager:
    """Tests for NotificationManager class."""

    def test_init_default_config(self) -> None:
        """Test initialization with default config."""
        manager = NotificationManager()
        assert manager.config is not None
        assert manager.config.webhooks == []

    def test_init_custom_config(self, notification_config: NotificationConfig) -> None:
        """Test initialization with custom config."""
        manager = NotificationManager(notification_config)
        assert len(manager.config.webhooks) == 1

    def test_is_configured_with_webhooks(self, notification_config: NotificationConfig) -> None:
        """Test is_configured returns True when webhooks are set."""
        manager = NotificationManager(notification_config)
        assert manager.is_configured() is True

    def test_is_configured_empty(self) -> None:
        """Test is_configured returns False when no channels configured."""
        manager = NotificationManager(NotificationConfig())
        assert manager.is_configured() is False

    def test_build_alert_payload(self, sample_entry: AuditLogEntry) -> None:
        """Test building alert payload."""
        manager = NotificationManager()
        payload = manager._build_alert_payload(
            rule_name="test_rule",
            message="Test alert message",
            entry=sample_entry,
        )

        assert payload["alert_type"] == "cja_audit_alert"
        assert payload["rule_name"] == "test_rule"
        assert payload["message"] == "Test alert message"
        assert "entry" in payload
        assert payload["entry"]["action"] == "DELETE"

    def test_build_alert_payload_without_details(
        self, sample_entry: AuditLogEntry
    ) -> None:
        """Test building alert payload without entry details."""
        manager = NotificationManager()
        payload = manager._build_alert_payload(
            rule_name="test_rule",
            message="Test alert",
            entry=sample_entry,
            include_details=False,
        )

        assert "entry" not in payload

    def test_build_slack_payload(self, sample_entry: AuditLogEntry) -> None:
        """Test building Slack payload."""
        manager = NotificationManager()
        payload = manager._build_slack_payload(
            rule_name="test_rule",
            message="Test alert",
            entry=sample_entry,
        )

        assert "blocks" in payload
        assert len(payload["blocks"]) >= 2

    def test_build_anomaly_payload(self) -> None:
        """Test building anomaly payload."""
        manager = NotificationManager()
        anomaly = {
            "type": "high_activity_user",
            "user": "user@example.com",
            "description": "High activity detected",
        }
        payload = manager._build_anomaly_payload(anomaly)

        assert payload["alert_type"] == "cja_audit_anomaly"
        assert payload["anomaly_type"] == "high_activity_user"

    @patch("httpx.Client.request")
    def test_send_webhook_success(
        self,
        mock_request: MagicMock,
        webhook_config: WebhookConfig,
    ) -> None:
        """Test successful webhook send."""
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        manager = NotificationManager()
        result = manager.send_webhook(webhook_config, {"test": "payload"})

        assert result is True

    def test_send_webhook_disabled(self, webhook_config: WebhookConfig) -> None:
        """Test disabled webhook is skipped."""
        webhook_config.enabled = False
        manager = NotificationManager()
        result = manager.send_webhook(webhook_config, {"test": "payload"})

        assert result is False

    def test_notify_alert_disabled(
        self, sample_entry: AuditLogEntry
    ) -> None:
        """Test notifications are skipped when disabled."""
        config = NotificationConfig(notify_on_alerts=False)
        manager = NotificationManager(config)
        result = manager.notify_alert("test_rule", "Test message", sample_entry)

        assert result == 0

    def test_notify_anomaly_disabled(self) -> None:
        """Test anomaly notifications are skipped when disabled."""
        config = NotificationConfig(notify_on_anomalies=False)
        manager = NotificationManager(config)
        result = manager.notify_anomaly({"type": "test", "description": "Test"})

        assert result == 0

    def test_context_manager(self) -> None:
        """Test context manager properly closes client."""
        with NotificationManager() as manager:
            assert manager is not None


class TestWebhookConfig:
    """Tests for WebhookConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = WebhookConfig(url="https://example.com")
        assert config.enabled is True
        assert config.method == "POST"
        assert config.timeout == 30
        assert config.include_entry_details is True

    def test_custom_headers(self) -> None:
        """Test custom headers configuration."""
        config = WebhookConfig(
            url="https://example.com",
            headers={"Authorization": "Bearer token"},
        )
        assert config.headers["Authorization"] == "Bearer token"


class TestNotificationConfig:
    """Tests for NotificationConfig model."""

    def test_default_values(self) -> None:
        """Test default configuration values."""
        config = NotificationConfig()
        assert config.webhooks == []
        assert config.slack_webhook_url is None
        assert config.notify_on_alerts is True
        assert config.notify_on_anomalies is True


class TestFailureWarning:
    """Tests for one-time-per-channel failure warnings."""

    def test_first_slack_failure_returns_warning(self, httpx_mock):
        """First Slack failure surfaces a warning string."""
        config = NotificationConfig(slack_webhook_url="https://hooks.slack.com/x")
        manager = NotificationManager(config)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)

        manager.send_slack("rule", "msg")
        warning = manager.pop_first_failure()
        assert warning is not None
        assert "slack" in warning.lower()

    def test_second_slack_failure_returns_none(self, httpx_mock):
        """Second Slack failure during the same session is suppressed."""
        config = NotificationConfig(slack_webhook_url="https://hooks.slack.com/x")
        manager = NotificationManager(config)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)

        manager.send_slack("rule", "msg")
        manager.pop_first_failure()  # consumes the first warning
        manager.send_slack("rule", "msg")
        assert manager.pop_first_failure() is None

    def test_recovery_clears_flag(self, httpx_mock):
        """A successful send clears the warned flag so next failure surfaces again."""
        config = NotificationConfig(slack_webhook_url="https://hooks.slack.com/x")
        manager = NotificationManager(config)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=200)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)

        manager.send_slack("rule", "msg")
        manager.pop_first_failure()  # consume
        manager.send_slack("rule", "msg")  # success → clears flag
        manager.send_slack("rule", "msg")  # fails again
        assert manager.pop_first_failure() is not None

    def test_per_channel_isolation(self, httpx_mock):
        """Slack failure flag does not affect webhook failure tracking."""
        webhook = WebhookConfig(url="https://hook.example.com/h")
        config = NotificationConfig(
            slack_webhook_url="https://hooks.slack.com/x",
            webhooks=[webhook],
        )
        manager = NotificationManager(config)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)
        httpx_mock.add_response(url="https://hook.example.com/h", status_code=500)

        manager.send_slack("rule", "msg")
        manager.pop_first_failure()  # consume Slack warning
        manager.send_webhook(webhook, {"x": 1})
        warning = manager.pop_first_failure()
        assert warning is not None
        assert "hook.example.com" in warning
