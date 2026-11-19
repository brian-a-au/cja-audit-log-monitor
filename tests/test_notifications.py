"""Tests for notifications module."""

import json
import logging
from datetime import UTC, datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import httpx
import pytest

from cja_audit_log_monitor.models import AuditLogEntry, NotificationConfig, WebhookConfig
from cja_audit_log_monitor.notifications import NotificationManager, slack_escape


@pytest.fixture(autouse=True)
def _fresh_url_redactor():
    """Each test starts with no remembered webhook URLs, so no test depends on test order."""
    from cja_audit_log_monitor.notifications import _url_redactor

    saved = set(_url_redactor._secret_urls)
    _url_redactor._secret_urls.clear()
    yield
    _url_redactor._secret_urls.clear()
    _url_redactor._secret_urls.update(saved)


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

    def test_is_configured_ignores_disabled_webhooks(self) -> None:
        """Disabled webhook entries do not count as active channels."""
        config = NotificationConfig(
            webhooks=[WebhookConfig(url="https://disabled.example", enabled=False)]
        )
        manager = NotificationManager(config)

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

        assert result == set()

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
        assert config.notify_on_anomalies is False

    def test_active_channels_ignore_disabled_webhooks(self) -> None:
        """Only enabled webhooks count as active channels."""
        config = NotificationConfig(
            webhooks=[
                WebhookConfig(url="https://disabled.example", enabled=False),
                WebhookConfig(url="https://enabled.example", enabled=True),
            ]
        )

        assert config.enabled_webhook_count == 1
        assert config.has_active_channels is True


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

    def test_anomaly_path_tracks_slack_failure(self, httpx_mock):
        """notify_anomaly's Slack path participates in failure tracking."""
        config = NotificationConfig(
            slack_webhook_url="https://hooks.slack.com/x",
            notify_on_anomalies=True,
        )
        manager = NotificationManager(config)
        httpx_mock.add_response(url="https://hooks.slack.com/x", status_code=500)

        manager.notify_anomaly({"type": "test", "description": "test anomaly"})
        warning = manager.pop_first_failure()
        assert warning is not None
        assert "slack" in warning.lower()


class TestAnomalyDedupFilter:
    """Tests for in-memory per-session anomaly dedup."""

    def test_empty_input_returns_empty(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        assert f.suppress_seen([]) == []

    def test_single_anomaly_passes_through_first_time(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        anomaly = {
            "type": "high_activity_user",
            "user": "alice@example.com",
            "action_count": 50,
            "average": 10.0,
            "description": "User alice@example.com has 50 actions (10.0 avg)",
        }
        out = f.suppress_seen([anomaly])
        assert out == [anomaly]

    def test_same_anomaly_suppressed_on_repeat(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        anomaly = {
            "type": "bulk_delete_single_user",
            "user": "bob@example.com",
            "delete_count": 15,
            "description": "Single user performed 15 deletes",
        }
        f.suppress_seen([anomaly])
        assert f.suppress_seen([anomaly]) == []

    def test_count_change_does_not_change_fingerprint(self):
        """Recurring anomaly whose count grew between cycles still dedupes."""
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        first = {
            "type": "bulk_delete_single_user",
            "user": "carol@example.com",
            "delete_count": 12,
            "description": "Single user performed 12 deletes",
        }
        second = {**first, "delete_count": 18, "description": "Single user performed 18 deletes"}
        f.suppress_seen([first])
        assert f.suppress_seen([second]) == []

    def test_different_users_pass_through(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        a1 = {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
              "average": 10.0, "description": "..."}
        a2 = {"type": "high_activity_user", "user": "b@x.com", "action_count": 60,
              "average": 10.0, "description": "..."}
        out = f.suppress_seen([a1, a2])
        assert len(out) == 2

    def test_different_anomaly_types_pass_through(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        a1 = {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
              "average": 10.0, "description": "..."}
        a2 = {"type": "off_hours_activity", "hour": 3, "action_count": 25,
              "description": "..."}
        out = f.suppress_seen([a1, a2])
        assert len(out) == 2

    def test_off_hours_different_hours_pass_through(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        a1 = {"type": "off_hours_activity", "hour": 2, "action_count": 25,
              "description": "..."}
        a2 = {"type": "off_hours_activity", "hour": 4, "action_count": 30,
              "description": "..."}
        out = f.suppress_seen([a1, a2])
        assert len(out) == 2

    def test_missing_fields_fingerprint_stably(self):
        """Anomaly dict shape with missing optional keys still fingerprints; no exception."""
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        a = {"type": "unknown_type"}
        out1 = f.suppress_seen([a])
        out2 = f.suppress_seen([a])
        assert out1 == [a]
        assert out2 == []

    def test_description_only_difference_dedupes(self):
        """Same identity fields, different free-text description → suppressed."""
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter
        f = AnomalyDedupFilter()
        a1 = {"type": "bulk_delete_single_user", "user": "d@x.com", "delete_count": 10,
              "description": "Single user performed 10 deletes"}
        a2 = {**a1, "description": "totally different wording"}
        f.suppress_seen([a1])
        assert f.suppress_seen([a2]) == []

    def test_same_anomaly_keeps_its_fingerprint_across_days(self):
        """The fingerprint holds no date, so a running anomaly is not news at midnight."""
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter

        f = AnomalyDedupFilter()
        a = {"type": "high_activity_user", "user": "e@x.com", "action_count": 50,
             "average": 10.0, "description": "..."}
        first = f.fingerprint(a)
        assert f.fingerprint(dict(a)) == first

    def test_pending_mark_sent_and_forget(self):
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter

        f = AnomalyDedupFilter()
        a = {"type": "bulk_delete_single_user", "user": "m@x.com", "delete_count": 12}
        channels = {"slack", "webhook:1"}
        assert f.pending([a], channels) == [(a, channels)]
        f.mark_sent(a, {"webhook:1"})
        assert f.pending([a], channels) == [(a, {"slack"})]
        f.mark_sent(a, {"slack"})
        assert f.pending([a], channels) == []
        f.forget_missing([])
        assert f.pending([a], channels) == [(a, channels)]


class TestNoSecretLeaks:
    """Failures never expose the secret parts of a webhook URL."""

    def test_slack_failure_hides_secret(self, httpx_mock, caplog):
        url = "https://hooks.slack.com/services/T0/B0/SECRET"
        manager = NotificationManager(NotificationConfig(slack_webhook_url=url))
        httpx_mock.add_response(url=url, status_code=404)

        with caplog.at_level(logging.DEBUG):
            manager.send_slack("rule", "msg")
        assert "SECRET" not in caplog.text
        warning = manager.pop_first_failure()
        assert warning is not None and "SECRET" not in warning

    def test_webhook_failure_hides_secret(self, httpx_mock, caplog):
        url = "https://hook.example.com/h?token=SECRET"
        webhook = WebhookConfig(url=url)
        manager = NotificationManager(NotificationConfig(webhooks=[webhook]))
        httpx_mock.add_response(url=url, status_code=404)

        with caplog.at_level(logging.DEBUG):
            manager.send_webhook(webhook, {"x": 1})
        assert "SECRET" not in caplog.text
        warning = manager.pop_first_failure()
        assert warning is not None and "SECRET" not in warning
        assert "hook.example.com" in warning

    def test_webhook_connection_error_hides_secret(self, httpx_mock, caplog):
        url = "https://hook.example.com/h?token=SECRET"
        webhook = WebhookConfig(url=url)
        manager = NotificationManager(NotificationConfig(webhooks=[webhook]))
        httpx_mock.add_exception(httpx.ConnectError("boom " + url), url=url)

        with caplog.at_level(logging.DEBUG):
            assert manager.send_webhook(webhook, {"x": 1}) is False
        assert "SECRET" not in caplog.text
        assert "SECRET" not in (manager.pop_first_failure() or "")


class TestSlackEscaping:
    """Slack text cannot inject mentions or links; other webhooks are untouched."""

    def test_slack_escape(self):
        assert slack_escape("a & <b>") == "a &amp; &lt;b&gt;"

    def test_slack_payload_escapes_the_component_name(self, httpx_mock):
        url = "https://hooks.slack.com/x"
        manager = NotificationManager(NotificationConfig(slack_webhook_url=url))
        entry = AuditLogEntry(
            id="1", action="DELETE", component_name="<!channel> <https://evil|x>",
            timestamp=datetime.now(UTC),
        )
        httpx_mock.add_response(url=url, status_code=200)

        manager.send_slack("rule", "msg", entry)
        body = httpx_mock.get_requests()[0].content.decode()
        assert "<!channel>" not in body
        assert "&lt;!channel&gt;" in body

    def test_user_name_escaped_in_slack_payload(self, httpx_mock):
        url = "https://hooks.slack.com/x"
        manager = NotificationManager(NotificationConfig(slack_webhook_url=url))
        entry = AuditLogEntry(
            id="1", action="DELETE", user_name="<!channel> <https://evil|x>",
            timestamp=datetime.now(UTC),
        )
        httpx_mock.add_response(url=url, status_code=200)

        manager.send_slack("rule <!here>", "msg <@U1>", entry)
        body = json.loads(httpx_mock.get_requests()[0].content)
        header = body["blocks"][0]["text"]
        assert header == {"type": "plain_text", "text": "CJA Audit Alert: rule <!here>"}
        mrkdwn = json.dumps([b for b in body["blocks"][1:]])
        assert "&lt;!channel&gt; &lt;https://evil|x&gt;" in mrkdwn
        assert "<!channel>" not in mrkdwn and "<@U1>" not in mrkdwn
        assert "msg &lt;@U1&gt;" in mrkdwn

    def test_anomaly_description_escaped(self, httpx_mock):
        url = "https://hooks.slack.com/x"
        manager = NotificationManager(
            NotificationConfig(slack_webhook_url=url, notify_on_anomalies=True)
        )
        httpx_mock.add_response(url=url, status_code=200)

        sent = manager.notify_anomaly({"type": "t", "description": "<!channel> & co"})
        assert sent == {"slack"}
        text = json.dumps(json.loads(httpx_mock.get_requests()[0].content))
        assert "&lt;!channel&gt; &amp; co" in text

    def test_generic_webhook_payload_not_escaped(self, sample_entry):
        manager = NotificationManager()
        payload = manager._build_alert_payload("r", "a <b> & c", sample_entry)
        assert payload["message"] == "a <b> & c"

    def test_slack_timestamp_is_utc(self):
        entry = AuditLogEntry(
            id="1", action="DELETE",
            timestamp=datetime(2026, 1, 1, 12, 0, tzinfo=timezone(timedelta(hours=5))),
        )
        payload = NotificationManager()._build_slack_payload("r", "m", entry)
        assert "2026-01-01 07:00:00 UTC" in json.dumps(payload)


class TestLogFilterAndBadUrls:
    """The httpx log filter covers late URLs and leaves other records alone."""

    def test_url_added_after_client_creation_is_redacted(self, httpx_mock, caplog):
        manager = NotificationManager(NotificationConfig())
        _ = manager.client  # client exists before the webhook does
        url = "https://late.example.com/h?token=SECRET"
        webhook = WebhookConfig(url=url)
        httpx_mock.add_response(url=url, status_code=200)

        with caplog.at_level(logging.DEBUG):
            assert manager.send_webhook(webhook, {"x": 1}) is True
        assert "SECRET" not in caplog.text

    def test_late_slack_url_is_redacted(self, httpx_mock, caplog):
        manager = NotificationManager(NotificationConfig())
        _ = manager.client
        url = "https://hooks.slack.com/services/T0/B0/SECRET"
        manager.config = NotificationConfig(slack_webhook_url=url)
        httpx_mock.add_response(url=url, status_code=200)

        with caplog.at_level(logging.DEBUG):
            assert manager.send_slack("r", "m") is True
        assert "SECRET" not in caplog.text

    def test_other_urls_pass_through_unchanged(self):
        from cja_audit_log_monitor.notifications import _url_redactor

        api = "https://cja.adobe.io/auditlogs/api/v1/auditlogs"
        record = logging.LogRecord(
            "httpx", logging.INFO, "f", 1, "HTTP Request: %s %s", ("GET", api), None
        )
        assert _url_redactor.filter(record) is True
        assert record.args == ("GET", api)

    def test_invalid_webhook_url_is_a_failure_without_leak(self, caplog):
        webhook = WebhookConfig(url="https://hook.example.com/h")
        manager = NotificationManager(NotificationConfig(webhooks=[webhook]))
        manager._client = MagicMock()
        manager._client.request.side_effect = httpx.InvalidURL("SECRET")

        with caplog.at_level(logging.DEBUG):
            assert manager.send_webhook(webhook, {"x": 1}) is False
        assert "SECRET" not in caplog.text
        warning = manager.pop_first_failure()
        assert warning is not None and "SECRET" not in warning

    def test_invalid_slack_url_is_a_failure_without_leak(self, caplog):
        manager = NotificationManager(
            NotificationConfig(slack_webhook_url="https://hooks.slack.com/services/SECRET")
        )
        manager._client = MagicMock()
        manager._client.post.side_effect = httpx.InvalidURL("SECRET")

        with caplog.at_level(logging.DEBUG):
            assert manager.send_slack("r", "m") is False
        assert "SECRET" not in caplog.text
        assert "SECRET" not in (manager.pop_first_failure() or "")


class TestDeliveryDetails:
    """Webhook headers and closing the client (G50)."""

    def test_webhook_sends_its_headers(self, httpx_mock):
        webhook = WebhookConfig(url="https://example.com/hook", headers={"Authorization": "x"})
        manager = NotificationManager(NotificationConfig(webhooks=[webhook]))
        httpx_mock.add_response(url="https://example.com/hook", status_code=200)
        assert manager.send_webhook(webhook, {"a": 1}) is True
        assert httpx_mock.get_requests()[0].headers["Authorization"] == "x"

    def test_close_closes_the_http_client(self):
        manager = NotificationManager(NotificationConfig())
        http = manager.client
        manager.close()
        assert http.is_closed
        assert manager._client is None
