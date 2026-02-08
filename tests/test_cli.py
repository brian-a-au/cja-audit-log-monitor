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


class TestTuiCommand:
    """Tests for TUI command."""

    def test_tui_help(self, runner: CliRunner) -> None:
        """Test tui command help."""
        result = runner.invoke(main, ["tui", "--help"])
        assert result.exit_code == 0
        assert "Launch the TUI interface" in result.output
