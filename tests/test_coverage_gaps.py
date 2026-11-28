"""Tests for paths the rest of the suite did not reach (CLI, config, client, models, more)."""

import io
import logging
import signal
import sys
import threading
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner
from pydantic import ValidationError

from cja_audit_log_monitor import cli as cli_module
from cja_audit_log_monitor.auth import AuthenticationError
from cja_audit_log_monitor.cli import main
from cja_audit_log_monitor.client import AuditLogsClient
from cja_audit_log_monitor.config import ConfigError, load_config
from cja_audit_log_monitor.models import (
    AlertRule,
    AuditLogEntry,
    NotificationConfig,
    WebhookConfig,
)
from cja_audit_log_monitor.notifications import NotificationManager

SLACK_URL = "https://hooks.slack.com/services/T000/B000/XXXX"
HOOK_URL = "https://hooks.example.com/alert"
HOOK2_URL = "https://hooks.example.com/second"


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """Some commands install process signal handlers; put the old ones back."""
    sigs = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        sigs.append(signal.SIGHUP)
    saved = {sig: signal.getsignal(sig) for sig in sigs}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def _settings(**notifications) -> MagicMock:
    """Stand-in settings with real defaults for what commands read."""
    return MagicMock(
        default_days=7,
        default_page_size=100,
        monitor_interval=60,
        notifications=NotificationConfig(**notifications),
    )


def _client(entries=None) -> MagicMock:
    client = MagicMock()
    client.__enter__.return_value = client
    client.get_all_logs.return_value = entries if entries is not None else []
    client.get_component_logs.return_value = entries if entries is not None else []
    return client


def _patch_client(client, settings=None):
    return patch.object(cli_module, "get_client", return_value=(client, settings or _settings()))


def _bare_entry(**fields) -> AuditLogEntry:
    """An entry the API sent with fields missing: no time, no action, no type."""
    return AuditLogEntry(id=fields.pop("id", "bare-1"), user_id="user-1", **fields)


# ---------------------------------------------------------------------------
# cli.py
# ---------------------------------------------------------------------------


class TestCliErrorHandling:
    @pytest.mark.parametrize(
        ("network", "label"),
        [(False, "Authentication error"), (True, "Network error")],
    )
    def test_authentication_error_is_one_line(self, runner, network, label):
        client = _client()
        client.get_all_logs.side_effect = AuthenticationError("token refused", network=network)
        with _patch_client(client):
            result = runner.invoke(main, ["cli", "list"])
        assert result.exit_code == 1
        assert f"{label}: token refused" in result.output
        assert "Traceback" not in result.output


class TestCliStreams:
    def test_streams_without_reconfigure_are_left_alone(self, monkeypatch):
        """A plain text stream (e.g. when embedded) has no reconfigure; nothing breaks."""
        out, err = io.StringIO(), io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        monkeypatch.setattr(sys, "stderr", err)
        cli_module._tolerate_narrow_encodings()
        print("still works", file=out)
        assert out.getvalue() == "still works\n"

    def test_utf8_stdout_uses_a_text_stream_as_is(self, monkeypatch):
        out = io.StringIO()
        monkeypatch.setattr(sys, "stdout", out)
        with cli_module.utf8_stdout() as stream:
            assert stream is out
            stream.write("日本")
        assert out.getvalue() == "日本"


class TestExitOnTermination:
    def test_sigterm_runs_cleanup_as_a_normal_exit(self):
        cleaned = []
        with pytest.raises(SystemExit) as info:
            try:
                with cli_module.exit_on_termination():
                    signal.raise_signal(signal.SIGTERM)
                    pytest.fail("the SIGTERM handler did not run")
            finally:
                cleaned.append(True)
        assert info.value.code == 128 + signal.SIGTERM
        assert cleaned == [True]

    def test_platform_without_sighup(self, monkeypatch):
        """Windows has no SIGHUP: only SIGTERM is handled, and it is put back after."""
        monkeypatch.delattr(signal, "SIGHUP", raising=False)
        before = signal.getsignal(signal.SIGTERM)
        with cli_module.exit_on_termination():
            assert signal.getsignal(signal.SIGTERM) is not before
        assert signal.getsignal(signal.SIGTERM) is before

    def test_off_the_main_thread_installs_nothing(self):
        before = signal.getsignal(signal.SIGTERM)
        seen, errors = [], []

        def run():
            try:
                with cli_module.exit_on_termination():
                    seen.append(signal.getsignal(signal.SIGTERM))
            except Exception as e:  # pragma: no cover - only runs if the test fails
                errors.append(e)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        assert errors == []
        assert seen == [before]

    def test_anomaly_handlers_off_the_main_thread_install_nothing(self):
        before = signal.getsignal(signal.SIGINT)
        errors = []

        def run():
            try:
                cli_module._install_anomalies_signal_handlers()
            except Exception as e:  # pragma: no cover - only runs if the test fails
                errors.append(e)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        assert errors == []
        assert signal.getsignal(signal.SIGINT) is before


class TestNoSubcommandLaunchesTui:
    def test_no_arguments_runs_the_tui(self, runner, tmp_path):
        config = tmp_path / "c.yaml"
        with patch.object(cli_module, "run_tui") as run_tui:
            result = runner.invoke(main, ["--config", str(config)])
        assert result.exit_code == 0
        run_tui.assert_called_once_with(config, None)


class TestEmptyJsonResults:
    def test_search_json_with_no_matches(self, runner):
        import json

        with _patch_client(_client([])):
            result = runner.invoke(main, ["cli", "search", "-a", "DELETE", "-F", "json"])
        assert result.exit_code == 0
        assert json.loads(result.output) == {"entries": [], "count": 0}

    def test_component_json_with_no_matches(self, runner):
        import json

        with _patch_client(_client([])):
            result = runner.invoke(main, ["cli", "component", "--id", "c-1", "-F", "json"])
        assert result.exit_code == 0
        data = json.loads(result.output)
        assert data["component_id"] == "c-1"
        assert data["count"] == 0


class TestEntriesWithMissingFields:
    def test_stats_without_any_action_skips_the_action_table(self, runner):
        with _patch_client(_client([_bare_entry(), _bare_entry(id="bare-2")])):
            result = runner.invoke(main, ["cli", "stats"])
        assert result.exit_code == 0
        assert "user-1" in result.output
        assert "Action Distribution" not in result.output

    def test_timeline_without_any_timestamp_shows_no_daily_bars(self, runner):
        with _patch_client(_client([_bare_entry()])):
            result = runner.invoke(main, ["cli", "timeline"])
        assert result.exit_code == 0
        assert "Daily Activity" in result.output
        assert "█" not in result.output.split("Hourly Distribution")[0]

    def test_stats_helpers_skip_missing_fields(self):
        from cja_audit_log_monitor import stats

        entries = [_bare_entry()]
        result = stats.calculate_stats(entries)
        assert result["action_counts"] == {}
        assert result["component_counts"] == {}
        assert result["date_range"] is None
        assert sum(stats.get_hourly_distribution(entries).values()) == 0
        assert stats.get_daily_distribution(entries) == {}
        assert stats.get_action_distribution(entries) == {}
        assert stats.get_component_distribution(entries) == {}
        timed = _bare_entry(id="t", timestamp=datetime.now(UTC))
        assert stats.get_trend([timed], days=7) == {}


class TestMonitorCommand:
    def test_explicit_interval_is_used(self, runner):
        with (
            _patch_client(_client()),
            patch.object(cli_module, "AuditLogMonitor") as monitor_cls,
        ):
            monitor_cls.return_value.successful_polls = 1
            result = runner.invoke(main, ["cli", "monitor", "-i", "10", "--no-alerts"])
        assert result.exit_code == 0, result.output
        assert monitor_cls.call_args.kwargs["interval"] == 10

    def test_slack_only_channel_summary(self, runner):
        settings = _settings(slack_webhook_url=SLACK_URL)
        with (
            _patch_client(_client(), settings),
            patch.object(cli_module, "AuditLogMonitor") as monitor_cls,
        ):
            monitor_cls.return_value.successful_polls = 1
            result = runner.invoke(main, ["cli", "monitor", "--no-alerts", "--duration", "1"])
        assert result.exit_code == 0, result.output
        assert "Notification channels: Slack" in result.output
        assert "webhook" not in result.output


class TestAnomaliesCommand:
    def test_json_output_prints_no_bullets(self, runner):
        import json

        anomaly = {"type": "bulk_delete", "description": "many deletes"}
        with (
            _patch_client(_client([])),
            patch.object(cli_module, "analyze_for_anomalies", return_value=[anomaly]),
        ):
            result = runner.invoke(main, ["cli", "anomalies", "-F", "json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output)["count"] == 1
        assert "•" not in result.output


class TestInitCommand:
    def test_overwrite_when_confirmed(self, runner, tmp_path):
        config = tmp_path / "c.yaml"
        config.write_text("old: true\n")
        result = runner.invoke(main, ["-c", str(config), "cli", "init"], input="y\n")
        assert result.exit_code == 0
        assert "Created config file" in result.output
        assert "old: true" not in config.read_text()


class TestQueryQuiet:
    def test_quiet_with_no_entries_prints_nothing(self, runner):
        with _patch_client(_client([])):
            result = runner.invoke(main, ["cli", "query", "--today", "-q"])
        assert result.exit_code == 0
        assert result.output == ""

    def test_quiet_with_entries_prints_only_the_table(self, runner, sample_audit_entry):
        with _patch_client(_client([sample_audit_entry])):
            result = runner.invoke(main, ["cli", "query", "--today", "-q"])
        assert result.exit_code == 0
        assert "Found" not in result.output
        assert "Querying" not in result.output


# ---------------------------------------------------------------------------
# client.py
# ---------------------------------------------------------------------------


def test_component_logs_without_type_has_no_component_filter(sample_settings):
    client = AuditLogsClient(sample_settings)
    with patch.object(client, "get_all_logs", return_value=[]) as get_all_logs:
        assert client.get_component_logs("c-1") == []
    query = get_all_logs.call_args.args[0]
    assert query.component_id == "c-1"
    assert query.components is None
    client.close()


# ---------------------------------------------------------------------------
# config.py
# ---------------------------------------------------------------------------


class TestConfigFile:
    def test_other_read_error_is_one_line(self, tmp_path, monkeypatch):
        """An I/O error other than permission or folder (e.g. EIO) is reported plainly."""
        import errno

        from cja_audit_log_monitor import config as config_module

        path = tmp_path / "c.yaml"
        path.write_text("monitor_interval: 30\n")
        path.chmod(0o600)

        def broken_open(*args, **kwargs):
            raise OSError(errno.EIO, "Input/output error")

        monkeypatch.setattr(config_module, "open", broken_open, raising=False)
        with pytest.raises(ConfigError) as info:
            load_config(path)
        assert "cannot be read (Input/output error)" in str(info.value)

    def test_no_permission_warning_on_windows(self, tmp_path, monkeypatch, caplog):
        path = tmp_path / "c.yaml"
        path.write_text("monitor_interval: 30\n")
        path.chmod(0o644)
        monkeypatch.setattr(sys, "platform", "win32")
        with caplog.at_level(logging.WARNING, logger="cja_audit_log_monitor"):
            settings = load_config(path)
        assert settings.monitor_interval == 30
        assert "readable by other users" not in caplog.text


# ---------------------------------------------------------------------------
# export.py
# ---------------------------------------------------------------------------


def test_export_path_stat_error_is_reported(tmp_path, monkeypatch):
    """Python 3.11 and 3.12 raise from is_dir (e.g. a folder with no search permission)."""
    from cja_audit_log_monitor.export import check_export_path

    def refuse(self):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "is_dir", refuse)
    path, problem, exists = check_export_path(str(tmp_path / "out.json"))
    assert path is None
    assert problem == "cannot use that path (Permission denied)"
    assert exists is False


# ---------------------------------------------------------------------------
# models.py
# ---------------------------------------------------------------------------


class TestModels:
    def test_null_timestamp_from_the_api(self):
        entry = AuditLogEntry.model_validate({"id": "x", "dateCreated": None})
        assert entry.timestamp is None

    def test_rule_with_actions_explicitly_none(self):
        assert AlertRule(name="r", actions=None).actions is None

    def test_rule_actions_must_be_a_list(self):
        with pytest.raises(ValidationError):
            AlertRule(name="r", actions="DELETE")

    def test_rule_action_that_is_not_text(self):
        with pytest.raises(ValidationError):
            AlertRule(name="r", actions=[1])

    def test_rule_users_must_be_a_list(self):
        with pytest.raises(ValidationError):
            AlertRule(name="r", users="alice")


# ---------------------------------------------------------------------------
# monitor.py
# ---------------------------------------------------------------------------


def test_log_line_that_cannot_be_printed_does_not_stop_the_monitor(monkeypatch):
    from cja_audit_log_monitor.monitor import AuditLogMonitor

    monitor = AuditLogMonitor(MagicMock(), console=MagicMock(), interval=60)
    calls = []

    def broken_print(text):
        calls.append(text)
        raise OSError("stderr closed")

    monkeypatch.setattr(monitor, "_print_warning", broken_print)
    handled = []
    monkeypatch.setattr(logging.Handler, "handleError", lambda self, record: handled.append(record))
    with monitor._logs_around_status():
        logging.getLogger("cja_audit_log_monitor").warning("delivery failed")
    assert calls == ["delivery failed"]
    assert len(handled) == 1


# ---------------------------------------------------------------------------
# notifications.py
# ---------------------------------------------------------------------------


class TestNotifications:
    def test_malformed_webhook_url_does_not_break_setup(self):
        """httpx cannot parse this URL (an unclosed IPv6 host); setup still works."""
        nm = NotificationManager(NotificationConfig(webhooks=[WebhookConfig(url="https://[::1")]))
        assert nm.client is not None
        nm.close()

    def test_slack_alert_without_timestamp_has_no_time_line(self, httpx_mock, sample_audit_entry):
        httpx_mock.add_response(url=SLACK_URL, status_code=200)
        entry = sample_audit_entry.model_copy(update={"timestamp": None})
        with NotificationManager(NotificationConfig(slack_webhook_url=SLACK_URL)) as nm:
            assert nm.send_slack("rule", "message", entry) is True
        import json

        blocks = json.loads(httpx_mock.get_requests()[0].content)["blocks"]
        assert [b["type"] for b in blocks] == ["header", "section", "section"]

    def test_send_slack_without_url(self):
        with NotificationManager(NotificationConfig()) as nm:
            assert nm.send_slack("rule", "message") is False

    def test_closed_manager_sends_no_slack_anomaly(self):
        config = NotificationConfig(slack_webhook_url=SLACK_URL, notify_on_anomalies=True)
        nm = NotificationManager(config)
        nm.close()
        assert nm.notify_anomaly({"type": "bulk_delete", "description": "d"}) == set()

    def test_alert_counts_a_webhook_that_accepts(self, httpx_mock):
        httpx_mock.add_response(url=HOOK_URL, status_code=200)
        config = NotificationConfig(webhooks=[WebhookConfig(url=HOOK_URL)])
        with NotificationManager(config) as nm:
            assert nm.notify_alert("rule", "message") == 1

    def test_anomaly_tries_the_next_webhook_after_one_fails(self, httpx_mock):
        httpx_mock.add_response(url=HOOK_URL, status_code=500)
        httpx_mock.add_response(url=HOOK2_URL, status_code=200)
        config = NotificationConfig(
            webhooks=[WebhookConfig(url=HOOK_URL), WebhookConfig(url=HOOK2_URL)],
            notify_on_anomalies=True,
        )
        with NotificationManager(config) as nm:
            accepted = nm.notify_anomaly({"type": "bulk_delete", "description": "d"})
        assert accepted == {"webhook:2"}


# ---------------------------------------------------------------------------
# tui/state.py and tui/log_toasts.py (no running app needed)
# ---------------------------------------------------------------------------


class TestAppStateLifecycle:
    def test_reload_replaces_the_notification_manager(self, tmp_path):
        from cja_audit_log_monitor.tui.state import AppState

        config = tmp_path / "c.yaml"
        config.write_text("monitor_interval: 30\n")
        config.chmod(0o600)
        state = AppState(config)
        old = state.notification_manager
        state.reload_settings()
        assert old._closed is True
        assert state.notification_manager is not old
        state.close()

    def test_close_before_any_client_was_built(self):
        from cja_audit_log_monitor.tui.state import AppState

        state = AppState()
        nm = state.notification_manager
        state.close()
        assert state._client is None
        assert nm._closed is True


class TestLogToasts:
    def test_record_with_broken_format_args_is_dropped(self):
        from cja_audit_log_monitor.tui.log_toasts import ToastLogHandler

        handler = ToastLogHandler(MagicMock())
        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "%d", ("text",), None)
        handler.emit(record)
        assert handler._pending == []

    def test_collect_keeps_the_warnings_logged_inside_it(self):
        from cja_audit_log_monitor.tui import log_toasts

        logger = logging.getLogger(log_toasts.PACKAGE_LOGGER)
        with log_toasts.collect() as found:
            logger.warning("kept %s", "one")
            logger.error("kept two")
        logger.warning("after the block")
        assert found == [("kept one", "warning"), ("kept two", "error")]

    def test_the_collector_drops_a_record_with_broken_format_args(self):
        from cja_audit_log_monitor.tui.log_toasts import _Collector

        collector = _Collector()
        collector.emit(logging.LogRecord("x", logging.WARNING, __file__, 1, "%d", ("text",), None))
        assert collector.found == []

    def test_record_from_a_thread_after_the_app_ended(self):
        from cja_audit_log_monitor.tui.log_toasts import ToastLogHandler

        app = MagicMock()
        app.call_from_thread.side_effect = RuntimeError("app is not running")
        handler = ToastLogHandler(app)
        handler.ready = True
        record = logging.LogRecord("x", logging.WARNING, __file__, 1, "late", None, None)
        errors = []

        def run():
            try:
                handler.emit(record)
            except Exception as e:  # pragma: no cover - only runs if the test fails
                errors.append(e)

        thread = threading.Thread(target=run)
        thread.start()
        thread.join()
        assert errors == []
        app.notify.assert_not_called()

    def test_install_lowers_a_quieter_package_level(self):
        from cja_audit_log_monitor.tui import log_toasts

        logger = logging.getLogger(log_toasts.PACKAGE_LOGGER)
        old_level = logger.level
        logger.setLevel(logging.ERROR)
        handler = log_toasts.install(MagicMock())
        try:
            assert logger.level == logging.WARNING
        finally:
            log_toasts.uninstall(handler)
            logger.setLevel(old_level)


def test_hourly_chart_keeps_a_tiny_hour_visible():
    from cja_audit_log_monitor.tui.widgets.stats_panel import HourlyChart

    markup = HourlyChart.build_markup({0: 1000, 5: 1}, cell=1, rows=4)
    bottom_bar_row = markup.split("\n")[-2]
    from rich.text import Text

    plain = Text.from_markup(bottom_bar_row).plain
    assert plain[5] != " "
    assert plain[4] == " "


def test_refreshing_a_key_that_is_not_remembered_adds_nothing() -> None:
    from datetime import UTC, datetime

    from cja_audit_log_monitor.utils import RecentIds

    seen = RecentIds(5)
    seen.refresh("never-added", datetime(2026, 1, 1, tzinfo=UTC))
    assert "never-added" not in seen
    assert len(seen) == 0
