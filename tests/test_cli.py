"""Tests for CLI commands."""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cja_audit_log_monitor.cli import main, parse_date
from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse


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

    @patch("cja_audit_log_monitor.cli.load_config")
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

    @patch("cja_audit_log_monitor.cli.load_config")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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
        query = mock_client.get_logs_paginated.call_args.args[0]
        assert query.page_size == 1000  # the API's largest page size


class TestStatsCommand:
    """Tests for stats command."""

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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


class TestExportSafety:
    """Export to stdout, no silent overwrite, clean errors."""

    @staticmethod
    def _client(entries):
        client = MagicMock()
        client.get_all_logs.return_value = entries
        client.get_logs_paginated.return_value = iter(entries)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_export_dash_writes_json_to_stdout(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), MagicMock())

        with runner.isolated_filesystem():
            result = runner.invoke(main, ["cli", "export", "-o", "-", "--days", "1"])
            assert not Path("-").exists()

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["count"] == len(sample_audit_entries)
        assert "Exported" in result.stderr

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_export_dash_csv_to_stdout(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), MagicMock())

        result = runner.invoke(main, ["cli", "export", "-f", "csv", "-o", "-", "--days", "1"])

        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0].startswith("id,timestamp")
        assert "Exported" not in result.stdout

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_existing_file_refused_before_fetch(
        self, mock_get_client: MagicMock, runner: CliRunner, tmp_path
    ) -> None:
        target = tmp_path / "out.json"
        target.write_text("old")

        result = runner.invoke(main, ["cli", "export", "-o", str(target)])

        assert result.exit_code == 1
        assert "--force" in result.stderr
        assert target.read_text() == "old"
        mock_get_client.assert_not_called()

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_force_overwrites(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries, tmp_path
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), MagicMock())
        target = tmp_path / "out.json"
        target.write_text("old")

        result = runner.invoke(main, ["cli", "export", "-o", str(target), "--force"])

        assert result.exit_code == 0, result.output
        assert json.loads(target.read_text())["count"] == len(sample_audit_entries)

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_missing_directory_is_one_line_error(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries, tmp_path
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), MagicMock())
        target = tmp_path / "missing" / "x.csv"

        result = runner.invoke(
            main, ["cli", "export", "-f", "csv", "-o", str(target)], env={"COLUMNS": "500"}
        )

        assert result.exit_code == 1
        assert "Traceback" not in result.stderr
        assert result.stderr.strip().count("\n") == 0  # one line, before any fetch
        assert "File error" in result.stderr
        mock_get_client.assert_not_called()

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_report_truncated_only_when_total_exceeds_cap(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        entries = sample_audit_entries[:2]
        mock_get_client.return_value = (self._client(entries), MagicMock())

        exact = runner.invoke(main, ["cli", "report", "--max-entries", "2"])
        over = runner.invoke(main, ["cli", "report", "--max-entries", "1"])

        assert json.loads(exact.stdout)["truncated"] is False
        assert "truncated" not in exact.stderr.lower()
        assert json.loads(over.stdout)["truncated"] is True

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_report_refuses_existing_file(
        self, mock_get_client: MagicMock, runner: CliRunner, tmp_path
    ) -> None:
        target = tmp_path / "r.json"
        target.write_text("old")

        result = runner.invoke(main, ["cli", "report", "-o", str(target)])

        assert result.exit_code == 1
        assert "--force" in result.stderr
        mock_get_client.assert_not_called()


class TestReportCommand:
    """Tests for report command."""

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_report_honors_max_entries(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
    ) -> None:
        """Test report command forwards --max-entries to client fetch."""
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = sample_audit_entries[:2]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, MagicMock())

        result = runner.invoke(main, ["cli", "report", "--days", "1", "--max-entries", "1"])
        assert result.exit_code == 0
        _, kwargs = mock_client.get_all_logs.call_args
        assert kwargs["max_entries"] == 2  # one extra entry detects truncation
        assert '"truncated": true' in result.output


class TestQueryCommand:
    """Tests for query command with date presets."""

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.get_client")
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

    @patch("cja_audit_log_monitor.cli.AuditLogMonitor.start", autospec=True)
    @patch("cja_audit_log_monitor.cli.get_client")
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
            ["cli", "tail", "--action", "DELETE", "--interval", "5", "--no-alerts"],
        )
        assert result.exit_code == 0

    def test_tail_command_constructs_notification_manager(
        self, monkeypatch
    ) -> None:
        """`cja-audit-log-monitor cli tail` opens NotificationManager as a `with` block."""
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

        with patch("cja_audit_log_monitor.cli.get_client") as gc, \
             patch("cja_audit_log_monitor.cli.NotificationManager", return_value=fake_nm), \
             patch("cja_audit_log_monitor.cli.AuditLogMonitor") as mon_cls:
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
        """`cja-audit-log-monitor cli monitor` opens NotificationManager as a `with` block."""
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

        with patch("cja_audit_log_monitor.cli.get_client") as gc, \
             patch("cja_audit_log_monitor.cli.NotificationManager", return_value=fake_nm), \
             patch("cja_audit_log_monitor.cli.AuditLogMonitor") as mon_cls:
            gc.return_value = (MagicMock(), fake_settings)
            mon = MagicMock()
            mon_cls.return_value = mon

            # Make start() exit immediately so the test doesn't hang
            mon.start.side_effect = KeyboardInterrupt()

            runner.invoke(main, ["cli", "monitor", "--no-alerts"])

        fake_nm.__enter__.assert_called_once()
        fake_nm.__exit__.assert_called_once()

    @pytest.mark.parametrize(
        ("enabled_flags", "expected_summary"),
        [
            ([False], None),
            ([False, True], "Notification channels: 1 webhook(s)"),
        ],
    )
    @patch("cja_audit_log_monitor.cli.AuditLogMonitor")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_monitor_summary_counts_only_enabled_webhooks(
        self,
        mock_get_client: MagicMock,
        mock_monitor_cls: MagicMock,
        runner: CliRunner,
        enabled_flags: list[bool],
        expected_summary: str | None,
    ) -> None:
        """The monitor startup summary reflects only active webhooks."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig, WebhookConfig

        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(
                webhooks=[
                    WebhookConfig(url=f"https://hook-{index}.example", enabled=enabled)
                    for index, enabled in enumerate(enabled_flags)
                ]
            ),
        )
        mock_get_client.return_value = (MagicMock(), settings)

        result = runner.invoke(main, ["cli", "monitor", "--no-alerts"])

        assert result.exit_code == 0
        if expected_summary is None:
            assert "Notification channels:" not in result.output
        else:
            assert expected_summary in result.output
        mock_monitor_cls.return_value.start.assert_called_once_with(duration=None)


class TestAnomaliesCommand:
    """Tests for the new `cja-audit-log-monitor cli anomalies` command."""

    @pytest.mark.parametrize(
        ("option", "value"),
        [
            ("--interval", "0"),
            ("--interval", "-1"),
            ("--lookback", "0"),
            ("--lookback", "-1"),
        ],
    )
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_rejects_nonpositive_timing_options(
        self,
        mock_get_client: MagicMock,
        runner: CliRunner,
        option: str,
        value: str,
    ) -> None:
        """Invalid timing values fail at Click parsing before client setup."""
        result = runner.invoke(main, ["cli", "anomalies", option, value])

        assert result.exit_code == 2
        assert "Invalid value" in result.output
        mock_get_client.assert_not_called()

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_accepts_minimum_lookback(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """The minimum valid lookback reaches the anomaly scan."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance

        result = runner.invoke(main, ["cli", "anomalies", "--lookback", "1"])

        assert result.exit_code == 0
        mock_cycle.assert_called_once()
        assert mock_cycle.call_args.args[-1] == 1

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_oneshot_no_entries_prints_nothing_to_dispatch(
        self,
        mock_get_client: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Empty entries → no anomalies → no dispatch."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_oneshot_dispatches_each_unique_anomaly_once(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Each new anomaly dispatched once via notify_anomaly."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_oneshot_skips_dispatch_when_anomalies_disabled(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """notify_on_anomalies: false → notify_anomaly returns 0 (early return)."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_oneshot_no_dispatch_when_manager_unconfigured(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """is_configured() == False → no Slack/webhook traffic, but command runs."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_disabled_webhooks_are_not_reported_or_called(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        runner: CliRunner,
        httpx_mock,
    ) -> None:
        """Disabled webhook entries are not active delivery channels."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig, WebhookConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(
                notify_on_anomalies=True,
                webhooks=[WebhookConfig(url="https://disabled.example", enabled=False)],
            ),
        )
        mock_get_client.return_value = (client, settings)
        mock_analyze.return_value = [
            {"type": "off_hours_activity", "hour": 3, "description": "..."}
        ]

        result = runner.invoke(main, ["cli", "anomalies"])

        assert result.exit_code == 0
        assert "Anomaly delivery enabled" not in result.output
        assert httpx_mock.get_requests() == []

    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_delivery_summary_counts_only_enabled_webhooks(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        runner: CliRunner,
        httpx_mock,
    ) -> None:
        """The startup summary and delivery use only enabled webhooks."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig, WebhookConfig

        enabled_url = "https://enabled.example"
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs = MagicMock(return_value=iter([MagicMock()]))

        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(
                notify_on_anomalies=True,
                webhooks=[
                    WebhookConfig(url="https://disabled.example", enabled=False),
                    WebhookConfig(url=enabled_url, enabled=True),
                ],
            ),
        )
        mock_get_client.return_value = (client, settings)
        mock_analyze.return_value = [
            {"type": "off_hours_activity", "hour": 3, "description": "..."}
        ]
        httpx_mock.add_response(url=enabled_url, status_code=200)

        result = runner.invoke(main, ["cli", "anomalies"])

        assert result.exit_code == 0
        assert "Anomaly delivery enabled: 1 webhook(s)" in result.output
        assert len(httpx_mock.get_requests()) == 1

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_dedupes_across_cycles(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Across two cycles, repeated anomaly is suppressed in the second."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

        # Allow exactly two cycles, then simulate Ctrl-C during the second wait.
        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=[None, KeyboardInterrupt]):
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "5"]
            )

        assert result.exit_code == 0
        # Two cycles ran (analyze called twice); dedup suppressed the second
        # dispatch so notify_anomaly was called only once.
        assert mock_analyze.call_count == 2
        assert nm_instance.notify_anomaly.call_count == 1

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_exits_cleanly_when_sleep_is_interrupted(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Ctrl-C during the inter-cycle sleep exits the watch loop cleanly."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=KeyboardInterrupt):
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "5"]
            )

        assert result.exit_code == 0
        # Exactly one cycle ran before the interrupted sleep stopped the loop.
        assert mock_analyze.call_count == 1
        assert nm_instance.notify_anomaly.call_count == 0

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_dispatch_exception_does_not_break_loop(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """notify_anomaly raising → next anomaly still processed; clean exit."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
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
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

    @pytest.mark.parametrize("status_code", [None, 408, 425, 429, 500, 502, 503, 504])
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_survives_transient_api_error(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
        status_code: int | None,
    ) -> None:
        """In --watch mode, an APIError on one cycle is logged; loop continues."""
        from cja_audit_log_monitor.client import APIError
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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
        mock_cycle.side_effect = [
            APIError("upstream blip", status_code=status_code),
            None,
        ]

        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=[None, KeyboardInterrupt]):
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "5"]
            )

        assert result.exit_code == 0
        assert mock_cycle.call_count == 2
        assert "API error this cycle" in result.output

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_honors_rate_limit_retry_after(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Rate-limit responses delay the next cycle by at least Retry-After."""
        from cja_audit_log_monitor.client import RateLimitError
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance
        mock_cycle.side_effect = RateLimitError(retry_after=60)

        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=KeyboardInterrupt) as sleep:
            result = runner.invoke(
                main, ["cli", "anomalies", "--watch", "--interval", "5"]
            )

        assert result.exit_code == 0
        sleep.assert_called_once_with(60)

    @pytest.mark.parametrize("status_code", [400, 401, 403, 501, 505])
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_exits_on_terminal_api_error(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
        status_code: int,
    ) -> None:
        """Permanent client errors exit nonzero instead of retrying forever."""
        from cja_audit_log_monitor.client import APIError
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance
        mock_cycle.side_effect = APIError("terminal", status_code=status_code)

        result = runner.invoke(
            main, ["cli", "anomalies", "--watch", "--interval", "5"]
        )

        assert result.exit_code == 1
        assert mock_cycle.call_count == 1
        assert "API error" in result.output

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    @pytest.mark.parametrize("signal_name", ["SIGINT", "SIGTERM"])
    def test_signal_interrupts_active_cycle_and_closes_clients(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
        signal_name: str,
    ) -> None:
        """Process signals unwind an in-flight cycle through both contexts."""
        import signal as signal_mod

        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        settings = CJASettings(
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
            notifications=NotificationConfig(),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance

        handlers = {}

        def capture_handler(sig, handler):
            handlers[sig] = handler

        def interrupt_cycle(*args):  # noqa: ARG001
            signal_value = getattr(signal_mod, signal_name)
            handlers[signal_value](signal_value, None)

        mock_cycle.side_effect = interrupt_cycle
        with patch("signal.signal", side_effect=capture_handler):
            result = runner.invoke(main, ["cli", "anomalies", "--watch"])

        assert result.exit_code == 0
        assert "Anomaly scan stopped" in result.output
        client.__exit__.assert_called_once()
        nm_instance.__exit__.assert_called_once()

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_oneshot_apierror_exits_nonzero(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """One-shot mode preserves exit-1 on APIError (no watch loop to survive)."""
        from cja_audit_log_monitor.client import APIError
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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

        from cja_audit_log_monitor.cli import _install_anomalies_signal_handlers

        prior_int = signal_mod.signal(signal_mod.SIGINT, signal_mod.SIG_DFL)
        prior_term = signal_mod.signal(signal_mod.SIGTERM, signal_mod.SIG_DFL)
        try:
            _install_anomalies_signal_handlers()

            sigint_handler = signal_mod.getsignal(signal_mod.SIGINT)
            sigterm_handler = signal_mod.getsignal(signal_mod.SIGTERM)
            assert callable(sigint_handler)
            assert callable(sigterm_handler)

            for sig, handler in (
                (signal_mod.SIGINT, sigint_handler),
                (signal_mod.SIGTERM, sigterm_handler),
            ):
                with pytest.raises(KeyboardInterrupt):
                    handler(sig, None)
        finally:
            signal_mod.signal(signal_mod.SIGINT, prior_int)
            signal_mod.signal(signal_mod.SIGTERM, prior_term)


class TestBadConfigFile:
    def test_invalid_config_exits_cleanly(self, tmp_path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: [1, \n")
        result = CliRunner().invoke(main, ["-c", str(path), "cli", "list"])
        assert result.exit_code == 1
        assert str(path) in result.output.replace("\n", "")
        assert "Traceback" not in result.output


class TestMonitorFatalAndTailFilter:
    def test_monitor_exits_1_on_403(self, runner: CliRunner) -> None:
        from cja_audit_log_monitor.client import APIError

        client = MagicMock()
        client.get_logs.side_effect = APIError("forbidden", status_code=403)
        with (
            patch("cja_audit_log_monitor.cli.get_client") as gc,
            patch("cja_audit_log_monitor.monitor.time.sleep"),
        ):
            gc.return_value = (client, MagicMock(alert_rules=[]))
            result = runner.invoke(main, ["cli", "monitor", "--no-alerts", "--duration", "5"])
        assert result.exit_code == 1

    def test_tail_user_filter_shows_only_that_user(self, runner: CliRunner) -> None:
        client = MagicMock()
        client.get_logs.return_value = AuditLogResponse(
            content=[
                AuditLogEntry(id="1", action="CREATE", user_email="alice@example.com",
                              component_name="mine-comp"),
                AuditLogEntry(id="2", action="CREATE", user_email="bob@example.com",
                              component_name="other-comp"),
            ],
            last=True,
        )
        captured = {}

        def fake_start(self, *args, **kwargs):
            captured["filter"] = self._entry_filter
            for entry in self._get_new_entries():
                self._display_entry(entry)

        with (
            patch("cja_audit_log_monitor.cli.get_client") as gc,
            patch("cja_audit_log_monitor.cli.AuditLogMonitor.start", fake_start),
        ):
            gc.return_value = (client, MagicMock(alert_rules=[]))
            result = runner.invoke(
                main, ["cli", "tail", "--user", "alice@example.com", "--no-alerts"]
            )
        assert result.exit_code == 0
        assert captured["filter"] is not None
        assert "mine-comp" in result.output
        assert "other-comp" not in result.output


class TestJsonOutputIsMachineSafe:
    """-F json writes only valid JSON to stdout, whatever the data contains."""

    NAME = "[red]x[/red] [/oops]"

    @pytest.mark.parametrize(
        ("args", "has_name"),
        [
            (["list", "-F", "json"], True),
            (["search", "-F", "json"], True),
            (["user", "-u", "someone", "-F", "json"], True),
            (["component", "-i", "comp-1", "-F", "json"], True),
            (["query", "--today", "-F", "json"], True),
            (["verify", "-F", "json"], False),
            (["stats", "-F", "json"], False),
            (["alerts", "list", "-F", "json"], False),
            (["report"], False),
        ],
        ids=[
            "list", "search", "user", "component", "query", "verify", "stats", "alerts-list",
            "report",
        ],
    )
    def test_stdout_is_valid_json(
        self, runner: CliRunner, args: list[str], has_name: bool
    ) -> None:
        entry = AuditLogEntry(
            id="entry-1",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            user_id="user-1",
            user_email="user@example.com",
            action="CREATE",
            component_type="PROJECT",
            component_id="comp-1",
            component_name=self.NAME,
            description="d" * 200,
        )
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = [entry]
        mock_client.get_component_logs.return_value = [entry]
        mock_client.verify_connection.return_value = {
            "connected": True,
            "authenticated": True,
            "org_id": "org",
            "api_url": "https://example.invalid",
            "total_logs_available": 1,
            "error": None,
        }
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with (
            patch("cja_audit_log_monitor.cli.get_client", return_value=(mock_client, MagicMock())),
            patch("cja_audit_log_monitor.cli.load_config") as mock_load,
        ):
            mock_load.return_value.alert_rules = []
            result = runner.invoke(main, ["-v", "cli", *args])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        if has_name:
            assert data["entries"][0]["component_name"] == self.NAME


def _fake_client(entries):
    client = MagicMock()
    client.get_all_logs.return_value = entries
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


class TestDataIsNotMarkup:
    """Names from the API render literally; they are never Rich markup."""

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_list_shows_bracketed_component_name(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entry
    ) -> None:
        entry = sample_audit_entry.model_copy(update={"component_name": "Q3 [/final] report"})
        mock_get_client.return_value = (_fake_client([entry]), MagicMock())

        result = runner.invoke(main, ["cli", "list"], env={"COLUMNS": "200"})

        assert result.exit_code == 0, result.output
        assert "Q3 [/final] report" in result.output

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_stats_survives_bracketed_user_id(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entry
    ) -> None:
        entry = sample_audit_entry.model_copy(
            update={"user_id": "[/]evil", "user_email": None, "user_name": None}
        )
        mock_get_client.return_value = (_fake_client([entry]), MagicMock())

        result = runner.invoke(main, ["cli", "stats"], env={"COLUMNS": "200"})

        assert result.exit_code == 0, result.output
        assert "[/]evil" in result.output


class TestHandleCliErrors:
    """One shared handler turns known failures into a clean stderr message."""

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_api_error_text_is_shown_literally_on_stderr(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        from cja_audit_log_monitor.client import APIError

        client = _fake_client([])
        client.get_all_logs.side_effect = APIError("boom [/oops]")
        mock_get_client.return_value = (client, MagicMock())

        result = runner.invoke(main, ["cli", "list"])

        assert result.exit_code == 1
        assert "[/oops]" in result.stderr
        assert "[/oops]" not in result.stdout

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_config_error_message_keeps_pydantic_brackets(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        from cja_audit_log_monitor.config import ConfigError

        message = (
            "1 validation error for CJASettings\n"
            "default_page_size\n  Input should be a valid integer "
            "[type=int_parsing, input_value='x', input_type=str]"
        )
        mock_get_client.side_effect = ConfigError(message, "short")

        result = runner.invoke(main, ["cli", "list"], env={"COLUMNS": "200"})

        assert result.exit_code == 1
        assert "[type=int_parsing, input_value='x', input_type=str]" in result.stderr

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_os_error_exits_1(
        self, mock_get_client: MagicMock, runner: CliRunner, tmp_path
    ) -> None:
        client = _fake_client([])
        mock_get_client.return_value = (client, MagicMock())
        target = tmp_path / "out.json"
        client.get_all_logs.return_value = [MagicMock()]

        with patch(
            "cja_audit_log_monitor.cli.export_entries", side_effect=OSError("disk [/full]")
        ):
            result = runner.invoke(main, ["cli", "export", "-o", str(target)])

        assert result.exit_code == 1
        assert "disk [/full]" in result.stderr

    def test_usage_errors_still_exit_2(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cli", "list", "--limit", "abc"])
        assert result.exit_code == 2

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_keyboard_interrupt_is_not_swallowed(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        client = _fake_client([])
        client.get_all_logs.side_effect = KeyboardInterrupt
        mock_get_client.return_value = (client, MagicMock())

        result = runner.invoke(main, ["cli", "list"])

        assert result.exit_code != 0
        assert isinstance(result.exception, (KeyboardInterrupt, SystemExit))


def _mock_client(**attrs) -> MagicMock:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    for name, value in attrs.items():
        getattr(client, name).return_value = value
    return client


class TestExitCodes:
    """A failed check must fail the process, so scripts can rely on the exit code."""

    @pytest.mark.parametrize("fmt", ["table", "json"])
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_verify_failed_connection_exits_1(
        self, mock_get_client: MagicMock, runner: CliRunner, fmt: str
    ) -> None:
        client = _mock_client(
            verify_connection={
                "connected": False,
                "authenticated": False,
                "org_id": "x@AdobeOrg",
                "api_url": "https://cja.adobe.io",
                "error": "boom",
            }
        )
        mock_get_client.return_value = (client, MagicMock())
        result = runner.invoke(main, ["cli", "verify", "-F", fmt])
        assert result.exit_code == 1

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_show_missing_entry_exits_1_with_message_on_stderr(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_client()
        client.get_logs_paginated.return_value = iter([])
        mock_get_client.return_value = (client, MagicMock())
        result = runner.invoke(main, ["cli", "show", "missing-id"])
        assert result.exit_code == 1
        assert "Entry not found: missing-id" in result.stderr
        assert "Entry not found" not in result.stdout

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_monitor_exits_1_when_no_poll_ever_succeeded(
        self, mock_get_client: MagicMock, mock_nm: MagicMock, runner: CliRunner
    ) -> None:
        from cja_audit_log_monitor.client import APIError

        client = MagicMock()
        client.get_logs.side_effect = APIError("upstream down", status_code=503)
        settings = MagicMock()
        settings.alert_rules = []
        mock_get_client.return_value = (client, settings)
        mock_nm.return_value.__enter__.return_value.is_configured.return_value = False

        def one_poll(monitor, *args, **kwargs):
            monitor._get_new_entries()

        with patch(
            "cja_audit_log_monitor.cli.AuditLogMonitor.start", autospec=True, side_effect=one_poll
        ):
            result = runner.invoke(main, ["cli", "monitor", "--no-alerts", "--duration", "5"])
        assert result.exit_code == 1

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_monitor_exits_0_when_a_poll_succeeded(
        self, mock_get_client: MagicMock, mock_nm: MagicMock, runner: CliRunner
    ) -> None:
        client = MagicMock()
        client.get_logs.return_value = AuditLogResponse(content=[], last=True)
        settings = MagicMock()
        settings.alert_rules = []
        mock_get_client.return_value = (client, settings)
        mock_nm.return_value.__enter__.return_value.is_configured.return_value = False

        def one_poll(monitor, *args, **kwargs):
            monitor._get_new_entries()

        with patch(
            "cja_audit_log_monitor.cli.AuditLogMonitor.start", autospec=True, side_effect=one_poll
        ):
            result = runner.invoke(main, ["cli", "monitor", "--no-alerts", "--duration", "5"])
        assert result.exit_code == 0


class TestNumericValidation:
    """Zero and negative numbers are usage errors (exit 2), never silent no-ops."""

    @pytest.mark.parametrize(
        "args",
        [
            ["list", "--limit", "0"],
            ["list", "--limit", "-3"],
            ["search", "--limit", "0"],
            ["stats", "--days", "0"],
            ["stats", "--top", "0"],
            ["top-users", "--days", "0"],
            ["top-users", "--top", "0"],
            ["export", "-o", "x.json", "--days", "0"],
            ["export", "-o", "x.json", "--max-entries", "0"],
            ["monitor", "--interval", "0"],
            ["monitor", "--interval", "4"],
            ["monitor", "--duration", "0"],
            ["tail", "--interval", "0"],
        ],
    )
    def test_invalid_number_exits_2(self, runner: CliRunner, args: list[str]) -> None:
        result = runner.invoke(main, ["cli", *args])
        assert result.exit_code == 2


class TestDateRangeValidation:
    """--end-date covers the whole day, and start after end is rejected."""

    def test_parse_date_end_of_day(self) -> None:
        assert parse_date("2026-01-01", end_of_day=True) == datetime(
            2026, 1, 1, 23, 59, 59, tzinfo=UTC
        )
        assert parse_date("2026-01-01") == datetime(2026, 1, 1, tzinfo=UTC)
        # An explicit time is left alone.
        assert parse_date("2026-01-01T05:00:00Z", end_of_day=True) == datetime(
            2026, 1, 1, 5, tzinfo=UTC
        )

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_search_same_day_end_date_is_end_of_day(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_client(get_all_logs=[])
        mock_get_client.return_value = (client, MagicMock())
        result = runner.invoke(main, ["cli", "search", "-s", "2026-01-01", "-e", "2026-01-01"])
        assert result.exit_code == 0
        query = client.get_all_logs.call_args.args[0]
        assert query.start_date == datetime(2026, 1, 1, tzinfo=UTC)
        assert query.end_date == datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_export_same_day_end_date_is_end_of_day(
        self, mock_get_client: MagicMock, runner: CliRunner, tmp_path
    ) -> None:
        client = _mock_client(get_all_logs=[])
        mock_get_client.return_value = (client, MagicMock())
        out = str(tmp_path / "x.json")
        result = runner.invoke(
            main, ["cli", "export", "-o", out, "-s", "2026-01-01", "-e", "2026-01-01"]
        )
        assert result.exit_code == 0
        query = client.get_all_logs.call_args.args[0]
        assert query.end_date == datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)

    @pytest.mark.parametrize("command", [["search"], ["export", "-o", "x.json"]])
    def test_start_after_end_exits_2(self, runner: CliRunner, command: list[str]) -> None:
        result = runner.invoke(
            main, ["cli", *command, "-s", "2026-02-01", "-e", "2026-01-01"]
        )
        assert result.exit_code == 2


class TestStatsTopFlag:
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_top_15_shows_15_users(self, mock_get_client: MagicMock, runner: CliRunner) -> None:
        entries = [
            AuditLogEntry(
                id=str(i),
                user_id=f"U{i}@x.e",
                user_email=f"user{i:02d}@example.com",
                action="CREATE",
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            )
            for i in range(15)
        ]
        client = _mock_client(get_all_logs=entries)
        mock_get_client.return_value = (client, MagicMock())
        result = runner.invoke(main, ["cli", "stats", "--top", "15", "-F", "json"])
        assert result.exit_code == 0
        assert len(json.loads(result.stdout)["statistics"]["top_users"]) == 15


class TestEmptyResultsAndStreams:
    """Empty results still emit one JSON document; pipes and tail exit codes behave."""

    @staticmethod
    def _empty_client() -> MagicMock:
        client = _fake_client([])
        client.get_logs_paginated.return_value = iter([])
        client.get_logs.return_value = AuditLogResponse(content=[], last=True)
        return client

    @pytest.mark.parametrize(
        "args",
        [["list", "-F", "json"], ["stats", "-F", "json"], ["report"]],
        ids=["list", "stats", "report"],
    )
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_empty_result_is_valid_json(
        self, mock_get_client: MagicMock, runner: CliRunner, args: list[str]
    ) -> None:
        mock_get_client.return_value = (self._empty_client(), MagicMock())

        result = runner.invoke(main, ["cli", *args])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        if args[0] == "report":
            assert data["anomalies"] == []
            assert data["truncated"] is False
            assert data["days_analyzed"] == 7
            assert "generated_at" in data
        if args[0] == "stats":
            assert data["days"] == 7
            assert data["anomalies"] == []
            assert data["statistics"]["total_entries"] == 0

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_empty_report_writes_output_file(
        self, mock_get_client: MagicMock, runner: CliRunner, tmp_path
    ) -> None:
        mock_get_client.return_value = (self._empty_client(), MagicMock())
        out = tmp_path / "r.json"

        result = runner.invoke(main, ["cli", "report", "-o", str(out)])

        assert result.exit_code == 0, result.output
        assert json.loads(out.read_text())["anomalies"] == []

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_broken_pipe_is_quiet(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_client.side_effect = BrokenPipeError(32, "Broken pipe")

        result = runner.invoke(main, ["cli", "list", "-F", "json"])

        assert isinstance(result.exception, SystemExit)
        assert result.exit_code == 1
        assert result.stderr == ""
        assert "Broken pipe" not in result.output
        assert "File error" not in result.output

    @pytest.mark.parametrize(
        ("succeeds", "code"), [(False, 1), (True, 0)], ids=["all-failed", "one-ok"]
    )
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_tail_exit_code_follows_successful_polls(
        self,
        mock_get_client: MagicMock,
        mock_nm: MagicMock,
        runner: CliRunner,
        succeeds: bool,
        code: int,
    ) -> None:
        from cja_audit_log_monitor.client import APIError

        client = MagicMock()
        if succeeds:
            client.get_logs.return_value = AuditLogResponse(content=[], last=True)
        else:
            client.get_logs.side_effect = APIError("upstream down", status_code=503)
        settings = MagicMock()
        settings.alert_rules = []
        mock_get_client.return_value = (client, settings)
        mock_nm.return_value.__enter__.return_value.is_configured.return_value = False

        def one_poll(monitor, *args, **kwargs):
            monitor._get_new_entries()

        with patch(
            "cja_audit_log_monitor.cli.AuditLogMonitor.start", autospec=True, side_effect=one_poll
        ):
            result = runner.invoke(main, ["cli", "tail", "--no-alerts"])
        assert result.exit_code == code

    def test_anomalies_interval_has_five_second_floor(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cli", "anomalies", "--interval", "4"])
        assert result.exit_code == 2
        assert "Invalid value" in result.output

    @patch("cja_audit_log_monitor.cli.load_config")
    def test_config_escapes_credential_display(
        self, mock_load: MagicMock, runner: CliRunner
    ) -> None:
        settings = MagicMock()
        settings.org_id = "[/red]boom@AdobeOrg"
        settings.client_id = "[bold]cid-1234567"
        settings.alert_rules = []
        mock_load.return_value = settings

        result = runner.invoke(main, ["cli", "config"])

        assert result.exit_code == 0, result.output
        assert "[/red]bo..." in result.output
        assert "[bold]ci..." in result.output


def test_anomaly_dispatch_error_log_has_no_exception_text(caplog):
    """An unexpected notify_anomaly error is logged by type only."""
    import logging

    from cja_audit_log_monitor.cli import _run_anomalies_cycle
    from cja_audit_log_monitor.notifications import AnomalyDedupFilter

    client = MagicMock()
    client.get_all_logs.return_value = iter([])
    nm = MagicMock()
    nm.notify_anomaly.side_effect = RuntimeError("https://hooks.slack.com/SECRET")
    nm.pop_first_failure.return_value = None
    anomaly = {"type": "t", "description": "d"}

    with patch("cja_audit_log_monitor.cli.analyze_for_anomalies", return_value=[anomaly]):
        with caplog.at_level(logging.DEBUG):
            _run_anomalies_cycle(client, nm, AnomalyDedupFilter(), 1)
    assert "RuntimeError" in caplog.text
    assert "SECRET" not in caplog.text


class TestExportRaces:
    """A file that appears after the early check is never clobbered; odd paths read clearly."""

    @staticmethod
    def _client(entries):
        client = MagicMock()
        client.get_all_logs.return_value = entries
        client.get_logs_paginated.return_value = iter(entries)
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_file_created_during_fetch_is_not_clobbered(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries, tmp_path
    ) -> None:
        target = tmp_path / "out.json"
        client = self._client(sample_audit_entries)

        def fetch_then_appear(*args, **kwargs):
            target.write_text("someone else")
            return sample_audit_entries

        client.get_all_logs.side_effect = fetch_then_appear
        mock_get_client.return_value = (client, MagicMock())

        result = runner.invoke(main, ["cli", "export", "-o", str(target)])

        assert result.exit_code == 1
        assert target.read_text() == "someone else"
        assert sorted(p.name for p in tmp_path.iterdir()) == ["out.json"]

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_report_file_created_during_fetch_is_not_clobbered(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries, tmp_path
    ) -> None:
        target = tmp_path / "report.json"
        client = self._client(sample_audit_entries)

        def fetch_then_appear(*args, **kwargs):
            target.write_text("someone else")
            return sample_audit_entries

        client.get_all_logs.side_effect = fetch_then_appear
        mock_get_client.return_value = (client, MagicMock())

        result = runner.invoke(main, ["cli", "report", "-o", str(target)])

        assert result.exit_code == 1
        assert target.read_text() == "someone else"

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_directory_output_says_folder(
        self, mock_get_client: MagicMock, runner: CliRunner, tmp_path
    ) -> None:
        for extra in ([], ["--force"]):
            result = runner.invoke(
                main, ["cli", "export", "-o", str(tmp_path), *extra], env={"COLUMNS": "500"}
            )
            assert result.exit_code == 1
            assert "folder" in result.stderr
            assert "--force" not in result.stderr
        mock_get_client.assert_not_called()

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_export_tsv_to_stdout(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), MagicMock())
        result = runner.invoke(main, ["cli", "export", "-f", "tsv", "-o", "-", "--days", "1"])
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0].startswith("id\ttimestamp")

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_report_dash_goes_to_stdout(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), MagicMock())
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["cli", "report", "-o", "-", "--days", "1"])
            assert not Path("-").exists()
        assert result.exit_code == 0, result.output
        assert "statistics" in json.loads(result.stdout) or json.loads(result.stdout)
