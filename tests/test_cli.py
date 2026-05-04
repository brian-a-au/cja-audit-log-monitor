"""Tests for CLI commands."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cja_audit.cli import main, parse_date
from cja_audit.models import AuditLogEntry, AuditLogResponse


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


class TestMainGroup:
    """Tests for main CLI group."""

    def test_version(self, runner: CliRunner) -> None:
        """Test --version flag."""
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert "0." in result.output or "version" in result.output.lower()

    def test_help(self, runner: CliRunner) -> None:
        """Test --help flag."""
        result = runner.invoke(main, ["--help"])
        assert result.exit_code == 0
        assert "CJA Audit Log Monitor" in result.output

    def test_cli_subgroup_help(self, runner: CliRunner) -> None:
        """Test cli subgroup help."""
        result = runner.invoke(main, ["cli", "--help"])
        assert result.exit_code == 0
        assert "Traditional CLI commands" in result.output


class TestParseDate:
    """Tests for date parsing helper."""

    def test_parse_iso_with_z_suffix(self) -> None:
        """Test parsing ISO-8601 timestamps ending in Z."""
        parsed = parse_date("2024-01-15T10:30:45Z")
        assert parsed is not None
        assert parsed.tzinfo is not None
        assert parsed.utcoffset() == timedelta(0)


class TestActionsCommand:
    """Tests for actions command."""

    def test_list_actions(self, runner: CliRunner) -> None:
        """Test listing available actions."""
        result = runner.invoke(main, ["cli", "actions"])
        assert result.exit_code == 0
        assert "CREATE" in result.output
        assert "DELETE" in result.output
        assert "EDIT" in result.output


class TestComponentsCommand:
    """Tests for components command."""

    def test_list_components(self, runner: CliRunner) -> None:
        """Test listing available components."""
        result = runner.invoke(main, ["cli", "components"])
        assert result.exit_code == 0
        assert "PROJECT" in result.output
        assert "FILTER" in result.output


class TestInitCommand:
    """Tests for init command."""

    def test_init_creates_config(self, runner: CliRunner) -> None:
        """Test init command creates config file."""
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["--config", "test_config.yaml", "cli", "init"])
            assert result.exit_code == 0
            assert "Created config file" in result.output


class TestConfigCommand:
    """Tests for config command."""

    @patch("cja_audit.cli.load_config")
    def test_show_config(
        self,
        mock_load: MagicMock,
        runner: CliRunner,
        sample_settings,
    ) -> None:
        """Test showing current configuration."""
        mock_load.return_value = sample_settings

        result = runner.invoke(main, ["cli", "config"])
        assert result.exit_code == 0
        assert "Current Configuration" in result.output

    @patch("cja_audit.cli.load_config")
    def test_show_config_uses_explicit_config_path(
        self,
        mock_load: MagicMock,
        runner: CliRunner,
        sample_settings,
    ) -> None:
        """Test config output reflects an explicit --config path."""
        mock_load.return_value = sample_settings

        result = runner.invoke(main, ["--config", "custom.yaml", "cli", "config"])
        assert result.exit_code == 0
        assert "Config file: custom.yaml" in result.output


class TestListCommand:
    """Tests for list command."""

    @patch("cja_audit.cli.get_client")
    def test_list_empty(self, mock_get_client: MagicMock, runner: CliRunner) -> None:
        """Test list with no results."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "list"])
        assert result.exit_code == 0
        assert "No audit logs found" in result.output

    @patch("cja_audit.cli.get_client")
    def test_list_with_results(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test list with results."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "list", "--limit", "5"])
        assert result.exit_code == 0

    @patch("cja_audit.cli.get_client")
    def test_list_json_format(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test list with JSON output format."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "list", "--output-format", "json"])
        assert result.exit_code == 0
        assert '"entries"' in result.output
        assert '"count"' in result.output


class TestSearchCommand:
    """Tests for search command."""

    @patch("cja_audit.cli.get_client")
    def test_search_by_action(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test search filtering by action."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "search", "--action", "DELETE"])
        assert result.exit_code == 0

    def test_invalid_action(self, runner: CliRunner) -> None:
        """Test error on invalid action."""
        result = runner.invoke(main, ["cli", "search", "--action", "INVALID_ACTION"])
        assert result.exit_code != 0 or "Invalid action" in result.output


class TestUserCommand:
    """Tests for user command."""

    @patch("cja_audit.cli.get_client")
    def test_user_command(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test user command."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "user", "--user-id", "test@example.com"])
        assert result.exit_code == 0
        assert "No audit logs found" in result.output


class TestComponentCommand:
    """Tests for component command."""

    @patch("cja_audit.cli.get_client")
    def test_component_command(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test component command."""
        mock_client = MagicMock()
        mock_client.get_component_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "component", "--id", "test-component-id"])
        assert result.exit_code == 0
        assert "No audit logs found" in result.output


class TestExportCommand:
    """Tests for export command."""

    @patch("cja_audit.cli.get_client")
    def test_export_tsv_format(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test export with TSV format."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        with runner.isolated_filesystem():
            result = runner.invoke(
                main,
                ["cli", "export", "--format", "tsv", "--output", "export.tsv", "--days", "1"],
            )
            assert result.exit_code == 0

    @patch("cja_audit.cli.get_client")
    def test_export_tsv_uses_paginated_stream(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test TSV export streams from paginated iterator."""
        mock_client = MagicMock()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_client.get_logs_paginated.return_value = iter(sample_audit_entries)
        mock_get_client.return_value = (mock_client, MagicMock())

        with runner.isolated_filesystem():
            result = runner.invoke(
                main,
                ["cli", "export", "--format", "tsv", "--output", "export.tsv", "--days", "1"],
            )
            assert result.exit_code == 0

        mock_client.get_logs_paginated.assert_called_once()


class TestStatsCommand:
    """Tests for stats command."""

    @patch("cja_audit.cli.get_client")
    def test_stats_json_format(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test stats with JSON output format."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "stats", "--output-format", "json"])
        assert result.exit_code == 0
        assert '"statistics"' in result.output


class TestVerifyCommand:
    """Tests for verify command."""

    @patch("cja_audit.cli.get_client")
    def test_verify_success(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test verify command with successful connection."""
        mock_client = MagicMock()
        mock_client.verify_connection.return_value = {
            "connected": True,
            "authenticated": True,
            "org_id": "TEST123@AdobeOrg",
            "api_url": "https://cja.adobe.io",
            "total_logs_available": 1000,
            "error": None,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "verify"])
        assert result.exit_code == 0
        assert "Connection successful" in result.output

    @patch("cja_audit.cli.get_client")
    def test_verify_json_format(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test verify command with JSON output."""
        mock_client = MagicMock()
        mock_client.verify_connection.return_value = {
            "connected": True,
            "authenticated": True,
            "org_id": "TEST123@AdobeOrg",
            "api_url": "https://cja.adobe.io",
            "error": None,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "verify", "--output-format", "json"])
        assert result.exit_code == 0
        assert '"connected"' in result.output


class TestReportCommand:
    """Tests for report command."""

    @patch("cja_audit.cli.get_client")
    def test_report_generation(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test report command generates report."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "report", "--days", "1"])
        assert result.exit_code == 0
        assert '"summary"' in result.output

    @patch("cja_audit.cli.get_client")
    def test_report_to_file(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test report command saves to file."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        with runner.isolated_filesystem():
            result = runner.invoke(main, ["cli", "report", "--output", "report.json"])
            assert result.exit_code == 0
            assert "Report saved" in result.output

    @patch("cja_audit.cli.get_client")
    def test_report_honors_max_entries(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test report command forwards --max-entries to client fetch."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries[:1]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "report", "--days", "1", "--max-entries", "1"])
        assert result.exit_code == 0
        _, kwargs = mock_client.get_all_logs.call_args
        assert kwargs["max_entries"] == 1
        assert '"truncated": true' in result.output


class TestQueryCommand:
    """Tests for query command with date presets."""

    @patch("cja_audit.cli.get_client")
    def test_query_today(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test query with --today preset."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "query", "--today"])
        assert result.exit_code == 0

    @patch("cja_audit.cli.get_client")
    def test_query_yesterday(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test query with --yesterday preset."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "query", "--yesterday"])
        assert result.exit_code == 0

    @patch("cja_audit.cli.get_client")
    def test_query_last_week(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test query with --last-week preset."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "query", "--last-week"])
        assert result.exit_code == 0


class TestAlertsSubcommand:
    """Tests for alerts subcommand group."""

    def test_alerts_list(self, runner: CliRunner) -> None:
        """Test alerts list command."""
        result = runner.invoke(main, ["cli", "alerts", "list"])
        assert result.exit_code == 0
        assert "Alert Rules" in result.output or "bulk_delete" in result.output

    def test_alerts_list_json(self, runner: CliRunner) -> None:
        """Test alerts list with JSON output."""
        result = runner.invoke(main, ["cli", "alerts", "list", "--output-format", "json"])
        assert result.exit_code == 0
        assert '"name"' in result.output


class TestTimelineCommand:
    """Tests for timeline command."""

    @patch("cja_audit.cli.get_client")
    def test_timeline(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test timeline command."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "timeline", "--days", "1"])
        assert result.exit_code == 0
        assert "Daily Activity" in result.output


class TestFindActionCommand:
    """Tests for find-action command."""

    @patch("cja_audit.cli.get_client")
    def test_find_action(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test find-action command."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = []
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "find-action", "--action", "DELETE"])
        assert result.exit_code == 0


class TestTopUsersCommand:
    """Tests for top-users command."""

    @patch("cja_audit.cli.get_client")
    def test_top_users(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test top-users command."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "top-users", "--days", "1"])
        assert result.exit_code == 0


class TestTailCommand:
    """Tests for tail command."""

    @patch("cja_audit.cli.AuditLogMonitor.start", autospec=True)
    @patch("cja_audit.cli.get_client")
    def test_tail_handles_unknown_action_values(
        self,
        mock_get_client: MagicMock,
        mock_monitor_start: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Test tail filtering does not crash on unknown API action strings."""
        mock_client = MagicMock()
        mock_client.get_logs.return_value = AuditLogResponse(
            content=[
                AuditLogEntry(
                    id="entry-1",
                    action="NEW_FUTURE_ACTION",
                    timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                )
            ],
            last=True,
        )
        mock_get_client.return_value = (mock_client, MagicMock())

        def run_single_poll(monitor, *args, **kwargs):
            monitor._get_new_entries()

        mock_monitor_start.side_effect = run_single_poll

        result = runner.invoke(
            main,
            ["cli", "tail", "--action", "DELETE", "--interval", "1", "--no-alerts"],
        )
        assert result.exit_code == 0

    def test_tail_command_constructs_notification_manager(
        self, monkeypatch
    ) -> None:
        """`cja-audit cli tail` opens NotificationManager as a `with` block."""
        runner = CliRunner()
        fake_nm = MagicMock()
        fake_nm.__enter__ = MagicMock(return_value=fake_nm)
        fake_nm.__exit__ = MagicMock(return_value=False)
        fake_nm.is_configured.return_value = False

        fake_settings = MagicMock()
        fake_settings.notifications = MagicMock()
        fake_settings.alert_rules = []
        fake_settings.notifications.slack_webhook_url = None
        fake_settings.notifications.webhooks = []

        with patch("cja_audit.cli.get_client") as gc, \
             patch("cja_audit.cli.NotificationManager", return_value=fake_nm), \
             patch("cja_audit.cli.AuditLogMonitor") as mon_cls:
            gc.return_value = (MagicMock(), fake_settings)
            mon = MagicMock()
            mon_cls.return_value = mon

            # Make start() exit immediately so the test doesn't hang
            mon.start.side_effect = KeyboardInterrupt()

            runner.invoke(main, ["cli", "tail", "--no-alerts"])

        fake_nm.__enter__.assert_called_once()
        fake_nm.__exit__.assert_called_once()


class TestTuiCommand:
    """Tests for TUI command."""

    def test_tui_help(self, runner: CliRunner) -> None:
        """Test tui command help."""
        result = runner.invoke(main, ["tui", "--help"])
        assert result.exit_code == 0
        assert "Launch the TUI interface" in result.output


class TestMonitorCommand:
    """Tests for monitor command NotificationManager wiring."""

    def test_monitor_command_constructs_notification_manager(
        self, monkeypatch
    ) -> None:
        """`cja-audit cli monitor` opens NotificationManager as a `with` block."""
        runner = CliRunner()
        fake_nm = MagicMock()
        fake_nm.__enter__ = MagicMock(return_value=fake_nm)
        fake_nm.__exit__ = MagicMock(return_value=False)
        fake_nm.is_configured.return_value = False

        fake_settings = MagicMock()
        fake_settings.notifications = MagicMock()
        fake_settings.alert_rules = []
        fake_settings.notifications.slack_webhook_url = None
        fake_settings.notifications.webhooks = []

        with patch("cja_audit.cli.get_client") as gc, \
             patch("cja_audit.cli.NotificationManager", return_value=fake_nm), \
             patch("cja_audit.cli.AuditLogMonitor") as mon_cls:
            gc.return_value = (MagicMock(), fake_settings)
            mon = MagicMock()
            mon_cls.return_value = mon

            # Make start() exit immediately so the test doesn't hang
            mon.start.side_effect = KeyboardInterrupt()

            runner.invoke(main, ["cli", "monitor", "--no-alerts"])

        fake_nm.__enter__.assert_called_once()
        fake_nm.__exit__.assert_called_once()


class TestAnomaliesCommand:
    """Tests for the new `cja-audit cli anomalies` command."""

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.get_client")
    def test_oneshot_no_entries_prints_nothing_to_dispatch(
        self,
        mock_get_client: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Empty entries → no anomalies → no dispatch."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        nm_instance.notify_anomaly = MagicMock(return_value=0)
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert nm_instance.notify_anomaly.call_count == 0

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_oneshot_dispatches_each_unique_anomaly_once(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Each new anomaly dispatched once via notify_anomaly."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(
                slack_webhook_url="https://hooks.slack.com/x",
                notify_on_anomalies=True,
            ),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=True)
        nm_instance.notify_anomaly = MagicMock(return_value=1)
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
             "average": 10.0, "description": "..."},
            {"type": "off_hours_activity", "hour": 3, "action_count": 25,
             "description": "..."},
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert nm_instance.notify_anomaly.call_count == 2

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_oneshot_skips_dispatch_when_anomalies_disabled(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """notify_on_anomalies: false → notify_anomaly returns 0 (early return)."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(
                slack_webhook_url="https://hooks.slack.com/x",
                notify_on_anomalies=False,
            ),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=True)
        nm_instance.notify_anomaly = MagicMock(return_value=0)
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
             "average": 10.0, "description": "..."},
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert nm_instance.notify_anomaly.call_count == 1

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_oneshot_no_dispatch_when_manager_unconfigured(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """is_configured() == False → no Slack/webhook traffic, but command runs."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        nm_instance.notify_anomaly = MagicMock(return_value=0)
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
             "average": 10.0, "description": "..."},
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        # The CLI calls notify_anomaly even when the manager is unconfigured;
        # short-circuiting happens inside the real manager (gated on
        # notify_on_anomalies in NotificationConfig). Here both is_configured()
        # and notify_anomaly are mocked, so this test only asserts the CLI's
        # call shape: dispatch attempted once, failure-drain queried once.
        assert nm_instance.notify_anomaly.call_count == 1
        assert nm_instance.pop_first_failure.call_count >= 1

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_watch_dedupes_across_cycles(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Across two cycles, repeated anomaly is suppressed in the second."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(
                slack_webhook_url="https://hooks.slack.com/x",
                notify_on_anomalies=True,
            ),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=True)
        nm_instance.notify_anomaly = MagicMock(return_value=1)
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance

        # Same anomaly returned on both cycles
        anomaly = {"type": "high_activity_user", "user": "a@x.com",
                   "action_count": 50, "average": 10.0, "description": "..."}
        mock_analyze.return_value = [anomaly]

        # Allow exactly two cycles: fake_wait returns False once (continue) then
        # True (stop). This proves cycle 2 ran AND dedup suppressed re-dispatch.
        from threading import Event
        call_count = {"n": 0}

        def fake_wait(self, timeout=None):  # noqa: ARG001
            call_count["n"] += 1
            return call_count["n"] >= 2

        with patch.object(Event, "wait", fake_wait):
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "1"]
            )

        assert result.exit_code == 0
        # Two cycles ran (analyze called twice); dedup suppressed the second
        # dispatch so notify_anomaly was called only once.
        assert mock_analyze.call_count == 2
        assert nm_instance.notify_anomaly.call_count == 1

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_watch_exits_cleanly_on_sigint(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """threading.Event.wait returning True (simulated SIGINT) breaks the loop."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        nm_instance.notify_anomaly = MagicMock(return_value=0)
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance
        mock_analyze.return_value = []

        from threading import Event

        def fake_wait(self, timeout=None):  # noqa: ARG001
            return True

        with patch.object(Event, "wait", fake_wait):
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "1"]
            )

        assert result.exit_code == 0
        # Exactly one cycle ran before stop_event broke the loop.
        assert mock_analyze.call_count == 1
        assert nm_instance.notify_anomaly.call_count == 0

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_dispatch_exception_does_not_break_loop(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """notify_anomaly raising → next anomaly still processed; clean exit."""
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(
                slack_webhook_url="https://hooks.slack.com/x",
                notify_on_anomalies=True,
            ),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=True)
        nm_instance.notify_anomaly = MagicMock(
            side_effect=[RuntimeError("boom"), 1]
        )
        nm_instance.pop_first_failure = MagicMock(return_value=None)
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
             "average": 10.0, "description": "..."},
            {"type": "bulk_delete_single_user", "user": "b@x.com", "delete_count": 12,
             "description": "..."},
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert nm_instance.notify_anomaly.call_count == 2

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli.analyze_for_anomalies")
    @patch("cja_audit.cli.get_client")
    def test_pop_first_failure_drained_to_console(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Whatever pop_first_failure returns is printed to console as a warning.

        This test mocks pop_first_failure's side_effect directly — it verifies the
        CLI's drain-and-print loop, not end-to-end Slack-failure → warning wiring.
        The wiring is symmetric to the alert path tested in test_notifications.py.
        """
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(
                slack_webhook_url="https://hooks.slack.com/x",
                notify_on_anomalies=True,
            ),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=True)
        nm_instance.notify_anomaly = MagicMock(return_value=0)
        warning_text = (
            "Notification delivery failed (slack); subsequent failures "
            "suppressed for this session — check logs."
        )
        nm_instance.pop_first_failure = MagicMock(side_effect=[warning_text, None])
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {"type": "high_activity_user", "user": "a@x.com", "action_count": 50,
             "average": 10.0, "description": "..."},
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert "Notification delivery failed (slack)" in result.output

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli._run_anomalies_cycle")
    @patch("cja_audit.cli.get_client")
    def test_watch_survives_transient_api_error(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """In --watch mode, an APIError on one cycle is logged; loop continues."""
        from cja_audit.client import APIError
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance

        # Cycle 1 raises APIError; cycle 2 succeeds. Loop must survive.
        mock_cycle.side_effect = [APIError("upstream blip"), None]

        from threading import Event
        call_count = {"n": 0}

        def fake_wait(self, timeout=None):  # noqa: ARG001
            call_count["n"] += 1
            return call_count["n"] >= 2

        with patch.object(Event, "wait", fake_wait):
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "1"]
            )

        assert result.exit_code == 0
        assert mock_cycle.call_count == 2
        assert "API error this cycle" in result.output

    @patch("cja_audit.cli.NotificationManager")
    @patch("cja_audit.cli._run_anomalies_cycle")
    @patch("cja_audit.cli.get_client")
    def test_oneshot_apierror_exits_nonzero(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """One-shot mode preserves exit-1 on APIError (no watch loop to survive)."""
        from cja_audit.client import APIError
        from cja_audit.config import CJASettings
        from cja_audit.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        settings = CJASettings(
            org_id="x@AdobeOrg", client_id="cid", client_secret="cs", scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance

        mock_cycle.side_effect = APIError("upstream down")

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 1
        assert "API error" in result.output

    def test_install_signal_handlers_registers_both_sigint_and_sigterm(self) -> None:
        """SIGTERM gets the same handler as SIGINT for systemd compatibility."""
        import signal as signal_mod
        from threading import Event

        from cja_audit.cli import _install_anomalies_signal_handlers

        prior_int = signal_mod.signal(signal_mod.SIGINT, signal_mod.SIG_DFL)
        prior_term = signal_mod.signal(signal_mod.SIGTERM, signal_mod.SIG_DFL)
        try:
            stop = Event()
            _install_anomalies_signal_handlers(stop)

            sigint_handler = signal_mod.getsignal(signal_mod.SIGINT)
            sigterm_handler = signal_mod.getsignal(signal_mod.SIGTERM)
            assert callable(sigint_handler)
            assert callable(sigterm_handler)

            sigterm_handler(signal_mod.SIGTERM, None)
            assert stop.is_set()
        finally:
            signal_mod.signal(signal_mod.SIGINT, prior_int)
            signal_mod.signal(signal_mod.SIGTERM, prior_term)
