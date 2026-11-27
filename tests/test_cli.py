"""Tests for CLI commands."""

import json
import re
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest
from click.testing import CliRunner

from cja_audit_log_monitor.cli import main, parse_date
from cja_audit_log_monitor.credentials import CredentialReport, Source
from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse

from .conftest import verify_result

ENV_SOURCE = Source(kind="environment", name="environment variables")


def _settings() -> MagicMock:
    """Stand-in settings with the real defaults for the values commands read."""
    return MagicMock(default_days=7, default_page_size=100, monitor_interval=60)


@pytest.fixture(autouse=True)
def _restore_signal_handlers():
    """`anomalies --watch` installs process signal handlers; put the old ones back."""
    import signal

    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
    yield
    for sig, handler in saved.items():
        signal.signal(sig, handler)


@pytest.fixture
def runner() -> CliRunner:
    """Create CLI test runner."""
    return CliRunner()


class TestMainGroup:
    """Tests for main CLI group."""

    def test_version(self, runner: CliRunner) -> None:
        """__version__ matches the installed metadata and --version prints it."""
        from importlib.metadata import version

        import cja_audit_log_monitor

        installed = version("cja-audit-log-monitor")
        assert cja_audit_log_monitor.__version__ == installed
        result = runner.invoke(main, ["--version"])
        assert result.exit_code == 0
        assert installed in result.output

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

    @patch("cja_audit_log_monitor.cli.load_settings")
    def test_show_config(
        self,
        mock_load: MagicMock,
        runner: CliRunner,
        sample_settings,
    ) -> None:
        """Test showing current configuration."""
        mock_load.return_value = (sample_settings, CredentialReport())

        result = runner.invoke(main, ["cli", "config"])
        assert result.exit_code == 0
        assert "Current Configuration" in result.output

    @patch("cja_audit_log_monitor.cli.load_settings")
    def test_show_config_uses_explicit_config_path(
        self,
        mock_load: MagicMock,
        runner: CliRunner,
        sample_settings,
    ) -> None:
        """Test config output reflects an explicit --config path."""
        mock_load.return_value = (sample_settings, CredentialReport())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_client.credential_source = ENV_SOURCE
        mock_client.verify_connection.return_value = verify_result(total_logs_available=1000)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_client.credential_source = ENV_SOURCE
        mock_client.verify_connection.return_value = verify_result()
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (mock_client, _settings())

        result = runner.invoke(main, ["cli", "verify", "--output-format", "json"])
        assert result.exit_code == 0
        assert '"adobe-credentials/v1/live-test"' in result.output


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
        mock_get_client.return_value = (self._client(sample_audit_entries), _settings())

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
        mock_get_client.return_value = (self._client(sample_audit_entries), _settings())

        result = runner.invoke(main, ["cli", "export", "-F", "csv", "-o", "-", "--days", "1"])

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
        mock_get_client.return_value = (self._client(sample_audit_entries), _settings())
        target = tmp_path / "out.json"
        target.write_text("old")

        result = runner.invoke(main, ["cli", "export", "-o", str(target), "--force"])

        assert result.exit_code == 0, result.output
        assert json.loads(target.read_text())["count"] == len(sample_audit_entries)

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_missing_directory_is_one_line_error(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries, tmp_path
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), _settings())
        target = tmp_path / "missing" / "x.csv"

        result = runner.invoke(
            main, ["cli", "export", "-F", "csv", "-o", str(target)], env={"COLUMNS": "500"}
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
        mock_get_client.return_value = (self._client(entries), _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

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
        mock_get_client.return_value = (mock_client, _settings())

        def run_single_poll(monitor, *args, **kwargs):
            monitor._get_new_entries()

        mock_monitor_start.side_effect = run_single_poll

        result = runner.invoke(
            main,
            ["cli", "tail", "--action", "DELETE", "--interval", "5", "--no-alerts"],
        )
        assert result.exit_code == 0

    def test_tail_command_constructs_notification_manager(self, monkeypatch) -> None:
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

        with (
            patch("cja_audit_log_monitor.cli.get_client") as gc,
            patch("cja_audit_log_monitor.cli.NotificationManager", return_value=fake_nm),
            patch("cja_audit_log_monitor.cli.AuditLogMonitor") as mon_cls,
        ):
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

    def test_monitor_command_constructs_notification_manager(self, monkeypatch) -> None:
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

        with (
            patch("cja_audit_log_monitor.cli.get_client") as gc,
            patch("cja_audit_log_monitor.cli.NotificationManager", return_value=fake_nm),
            patch("cja_audit_log_monitor.cli.AuditLogMonitor") as mon_cls,
        ):
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
        assert mock_cycle.call_args.args[3] == 1

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
        nm_instance.notify_anomaly = MagicMock(return_value=set())
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
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
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
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
        nm_instance.notify_anomaly = MagicMock(return_value={"slack"})
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {
                "type": "high_activity_user",
                "user": "a@x.com",
                "action_count": 50,
                "average": 10.0,
                "description": "...",
            },
            {"type": "off_hours_activity", "hour": 3, "action_count": 25, "description": "..."},
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
        """notify_on_anomalies: false → the CLI sends nothing."""
        from cja_audit_log_monitor.config import CJASettings
        from cja_audit_log_monitor.models import NotificationConfig

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
                slack_webhook_url="https://hooks.slack.com/x",
                notify_on_anomalies=False,
            ),
        )
        mock_get_client.return_value = (client, settings)

        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=True)
        nm_instance.notify_anomaly = MagicMock(return_value=set())
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {
                "type": "high_activity_user",
                "user": "a@x.com",
                "action_count": 50,
                "average": 10.0,
                "description": "...",
            },
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert nm_instance.notify_anomaly.call_count == 0

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
        nm_instance.notify_anomaly = MagicMock(return_value=set())
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {
                "type": "high_activity_user",
                "user": "a@x.com",
                "action_count": 50,
                "average": 10.0,
                "description": "...",
            },
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        # No channel is configured, so nothing is sent; failures are still drained.
        assert nm_instance.notify_anomaly.call_count == 0
        assert nm_instance.pop_failures.call_count >= 1

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
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
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
        nm_instance.notify_anomaly = MagicMock(return_value={"slack"})
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
        mock_nm_cls.return_value = nm_instance

        # Same anomaly returned on both cycles
        anomaly = {
            "type": "high_activity_user",
            "user": "a@x.com",
            "action_count": 50,
            "average": 10.0,
            "description": "...",
        }
        mock_analyze.return_value = [anomaly]

        # Allow exactly two cycles, then simulate Ctrl-C during the second wait.
        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=[None, KeyboardInterrupt]):
            result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])

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
        nm_instance.notify_anomaly = MagicMock(return_value=set())
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
        mock_nm_cls.return_value = nm_instance
        mock_analyze.return_value = []

        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=KeyboardInterrupt):
            result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])

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
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
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
        nm_instance.notify_anomaly = MagicMock(side_effect=[RuntimeError("boom"), {"slack"}])
        nm_instance.pop_failures = MagicMock(return_value=[])
        nm_instance.config = settings.notifications
        nm_instance.channels = MagicMock(
            return_value=["slack"] if settings.notifications.slack_webhook_url else []
        )
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {
                "type": "high_activity_user",
                "user": "a@x.com",
                "action_count": 50,
                "average": 10.0,
                "description": "...",
            },
            {
                "type": "bulk_delete_single_user",
                "user": "b@x.com",
                "delete_count": 12,
                "description": "...",
            },
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert nm_instance.notify_anomaly.call_count == 2

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.analyze_for_anomalies")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_delivery_failures_drained_to_console(
        self,
        mock_get_client: MagicMock,
        mock_analyze: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        """Whatever pop_failures returns is printed to console as a warning.

        This test mocks pop_failures directly — it verifies the
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
            org_id="x@AdobeOrg",
            client_id="cid",
            client_secret="cs",
            scopes="openid",
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
        nm_instance.notify_anomaly = MagicMock(return_value=set())
        warning_text = (
            "Notification delivery failed (slack); subsequent failures "
            "suppressed for this session — check logs."
        )
        nm_instance.pop_failures = MagicMock(return_value=[warning_text])
        mock_nm_cls.return_value = nm_instance

        mock_analyze.return_value = [
            {
                "type": "high_activity_user",
                "user": "a@x.com",
                "action_count": 50,
                "average": 10.0,
                "description": "...",
            },
        ]

        result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 0
        assert "Notification delivery failed (slack)" in result.output
        assert "Notification delivery failed (slack)" in result.stderr
        assert "Notification delivery failed (slack)" not in result.stdout

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli._run_anomalies_cycle")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_survives_transient_token_failure(
        self,
        mock_get_client: MagicMock,
        mock_cycle: MagicMock,
        mock_nm_cls: MagicMock,
        runner: CliRunner,
    ) -> None:
        from cja_audit_log_monitor.auth import AuthenticationError

        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        mock_get_client.return_value = (client, _settings())
        nm_instance = MagicMock()
        nm_instance.__enter__ = MagicMock(return_value=nm_instance)
        nm_instance.__exit__ = MagicMock(return_value=False)
        nm_instance.is_configured = MagicMock(return_value=False)
        mock_nm_cls.return_value = nm_instance
        mock_cycle.side_effect = [AuthenticationError("IMS 503", transient=True), None]

        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=[None, KeyboardInterrupt]):
            result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])

        assert result.exit_code == 0
        assert mock_cycle.call_count == 2

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

        # Cycle 1 raises APIError; cycle 2 succeeds. Loop must survive.
        mock_cycle.side_effect = [
            APIError("upstream blip", status_code=status_code),
            None,
        ]

        with patch("cja_audit_log_monitor.cli.time.sleep", side_effect=[None, KeyboardInterrupt]):
            result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])

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
            result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])

        assert result.exit_code == 0
        sleep.assert_called_once_with(60)

    @pytest.mark.parametrize("status_code", [400, 401, 403, 404])
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

        result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])

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
                AuditLogEntry(
                    id="1",
                    action="CREATE",
                    user_email="alice@example.com",
                    component_name="mine-comp",
                ),
                AuditLogEntry(
                    id="2",
                    action="CREATE",
                    user_email="bob@example.com",
                    component_name="other-comp",
                ),
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
    USER = "[bold]u[/bold]@example.com"

    @pytest.mark.parametrize(
        ("args", "has_name"),
        [
            (["list", "-F", "json"], True),
            (["search", "-F", "json"], True),
            (["user", "-u", "someone", "-F", "json"], True),
            (["component", "-i", "comp-1", "-F", "json"], True),
            (["query", "--today", "-F", "json"], True),
            (["verify", "-F", "json"], False),
            (["stats", "-F", "json"], "user"),
            (["alerts", "list", "-F", "json"], False),
            (["report"], False),
        ],
        ids=[
            "list",
            "search",
            "user",
            "component",
            "query",
            "verify",
            "stats",
            "alerts-list",
            "report",
        ],
    )
    def test_stdout_is_valid_json(self, runner: CliRunner, args: list[str], has_name: bool) -> None:
        entry = AuditLogEntry(
            id="entry-1",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            user_id="user-1",
            user_email=self.USER,
            action="CREATE",
            component_type="PROJECT",
            component_id="comp-1",
            component_name=self.NAME,
            description="d" * 200,
        )
        mock_client = MagicMock()
        mock_client.get_all_logs.return_value = [entry]
        mock_client.get_component_logs.return_value = [entry]
        mock_client.credential_source = ENV_SOURCE
        mock_client.verify_connection.return_value = verify_result(total_logs_available=1)
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with (
            patch("cja_audit_log_monitor.cli.get_client", return_value=(mock_client, _settings())),
            patch("cja_audit_log_monitor.cli.load_settings") as mock_load,
        ):
            mock_load.return_value = (MagicMock(alert_rules=[]), CredentialReport())
            result = runner.invoke(main, ["-v", "cli", *args])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        if has_name == "user":
            assert self.USER in json.dumps(data)
        elif has_name:
            assert data["entries"][0]["component_name"] == self.NAME


def _fake_client(entries):
    client = MagicMock()
    client.get_all_logs.return_value = entries
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def test_cli_consoles_have_no_fixed_size_in_tests() -> None:
    """The conftest fixture gives each test fresh consoles, made without COLUMNS or LINES.

    A console made while both are set keeps that size for good, so an xdist worker that
    started with COLUMNS=80 would otherwise render every CLI test 80 columns wide.
    """
    from cja_audit_log_monitor import cli as cli_module

    for console in (cli_module.console, cli_module.err_console):
        assert console._width is None
        assert console._height is None


class TestDataIsNotMarkup:
    """Names from the API render literally; they are never Rich markup."""

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_list_shows_bracketed_component_name(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entry
    ) -> None:
        entry = sample_audit_entry.model_copy(update={"component_name": "Q3 [/final] report"})
        mock_get_client.return_value = (_fake_client([entry]), _settings())

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
        mock_get_client.return_value = (_fake_client([entry]), _settings())

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
        mock_get_client.return_value = (client, _settings())

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
        mock_get_client.return_value = (client, _settings())
        target = tmp_path / "out.json"
        client.get_all_logs.return_value = [MagicMock()]

        with patch("cja_audit_log_monitor.cli.export_entries", side_effect=OSError("disk [/full]")):
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
        mock_get_client.return_value = (client, _settings())

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
        mock_get_client.return_value = (client, _settings())
        result = runner.invoke(main, ["cli", "verify", "-F", fmt])
        assert result.exit_code == 1

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_show_missing_entry_exits_1_with_message_on_stderr(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        client = _mock_client()
        client.get_logs_paginated.return_value = iter([])
        mock_get_client.return_value = (client, _settings())
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
        mock_get_client.return_value = (client, _settings())
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
        mock_get_client.return_value = (client, _settings())
        out = str(tmp_path / "x.json")
        result = runner.invoke(
            main, ["cli", "export", "-o", out, "-s", "2026-01-01", "-e", "2026-01-01"]
        )
        assert result.exit_code == 0
        query = client.get_all_logs.call_args.args[0]
        assert query.end_date == datetime(2026, 1, 1, 23, 59, 59, tzinfo=UTC)

    @pytest.mark.parametrize("command", [["search"], ["export", "-o", "x.json"]])
    def test_start_after_end_exits_2(self, runner: CliRunner, command: list[str]) -> None:
        result = runner.invoke(main, ["cli", *command, "-s", "2026-02-01", "-e", "2026-01-01"])
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
        mock_get_client.return_value = (client, _settings())
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
        mock_get_client.return_value = (self._empty_client(), _settings())

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
        mock_get_client.return_value = (self._empty_client(), _settings())
        out = tmp_path / "r.json"

        result = runner.invoke(main, ["cli", "report", "-o", str(out)])

        assert result.exit_code == 0, result.output
        assert json.loads(out.read_text())["anomalies"] == []

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_broken_pipe_is_quiet(self, mock_get_client: MagicMock, runner: CliRunner) -> None:
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

    @patch("cja_audit_log_monitor.cli.load_settings")
    def test_config_escapes_credential_display(
        self, mock_load: MagicMock, runner: CliRunner
    ) -> None:
        settings = MagicMock()
        settings.org_id = "[/red]boom@AdobeOrg"
        settings.client_id = "[bold]cid-1234567"
        settings.scopes = "[dim]openid"
        settings.alert_rules = []
        mock_load.return_value = (settings, CredentialReport())

        result = runner.invoke(main, ["cli", "config"])

        assert result.exit_code == 0, result.output
        assert "[/red]boom@AdobeOrg" in result.output
        assert "[bol****4567" in result.output
        assert "[dim]openid" in result.output


def test_anomaly_dispatch_error_log_has_no_exception_text(caplog):
    """An unexpected notify_anomaly error is logged by type only."""
    import logging

    from cja_audit_log_monitor.cli import _run_anomalies_cycle
    from cja_audit_log_monitor.notifications import AnomalyDedupFilter

    client = MagicMock()
    client.get_all_logs.return_value = iter([])
    nm = MagicMock()
    nm.channels.return_value = ["slack"]
    nm.notify_anomaly.side_effect = RuntimeError("https://hooks.slack.com/SECRET")
    nm.pop_failures.return_value = []
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
        mock_get_client.return_value = (client, _settings())

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
        mock_get_client.return_value = (client, _settings())

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
        mock_get_client.return_value = (self._client(sample_audit_entries), _settings())
        result = runner.invoke(main, ["cli", "export", "-F", "tsv", "-o", "-", "--days", "1"])
        assert result.exit_code == 0, result.output
        assert result.stdout.splitlines()[0].startswith("id\ttimestamp")

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_report_dash_goes_to_stdout(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (self._client(sample_audit_entries), _settings())
        with runner.isolated_filesystem():
            result = runner.invoke(main, ["cli", "report", "-o", "-", "--days", "1"])
            assert not Path("-").exists()
        assert result.exit_code == 0, result.output
        report = json.loads(result.stdout)
        assert sum(report["action_distribution"].values()) == len(sample_audit_entries)


class TestConfiguredDefaults:
    """Commands fall back to default_days and monitor_interval."""

    @staticmethod
    def _client() -> MagicMock:
        client = MagicMock()
        client.get_all_logs.return_value = []
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_stats_uses_default_days(self, mock_get_client: MagicMock, runner: CliRunner) -> None:
        client = self._client()
        settings = _settings()
        settings.default_days = 3
        mock_get_client.return_value = (client, settings)
        result = runner.invoke(main, ["cli", "stats", "--output-format", "json"])
        assert result.exit_code == 0
        query = client.get_all_logs.call_args.args[0]
        assert (query.end_date - query.start_date).days == 3
        assert json.loads(result.output)["days"] == 3

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_explicit_days_beats_the_setting(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        client = self._client()
        settings = _settings()
        settings.default_days = 3
        mock_get_client.return_value = (client, settings)
        result = runner.invoke(main, ["cli", "stats", "--days", "10"])
        assert result.exit_code == 0
        query = client.get_all_logs.call_args.args[0]
        assert (query.end_date - query.start_date).days == 10

    @patch("cja_audit_log_monitor.cli.AuditLogMonitor")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_monitor_uses_configured_interval(
        self, mock_get_client: MagicMock, mock_monitor: MagicMock, runner: CliRunner
    ) -> None:
        settings = _settings()
        settings.monitor_interval = 30
        settings.alert_rules = []
        mock_get_client.return_value = (self._client(), settings)
        mock_monitor.return_value.successful_polls = 1
        result = runner.invoke(main, ["cli", "monitor", "--duration", "1", "--no-alerts"])
        assert result.exit_code == 0
        assert mock_monitor.call_args.kwargs["interval"] == 30

    def test_help_says_the_default_comes_from_config(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cli", "stats", "--help"])
        assert "default_days from the config" in " ".join(result.output.split())

    def test_init_template_has_no_output_format(self, runner: CliRunner) -> None:
        with runner.isolated_filesystem():
            runner.invoke(main, ["--config", "c.yaml", "cli", "init"])
            assert "output_format" not in Path("c.yaml").read_text()


class TestConsistentFlags:
    """Short flags mean one thing each; -F picks the format everywhere (F33)."""

    @pytest.mark.parametrize(
        "args",
        [
            ["tail", "-c", "x"],
            ["monitor", "-D", "5"],
            ["stats", "-t", "3"],
            ["top-users", "-t", "3"],
        ],
    )
    def test_clashing_short_flags_are_gone(self, runner: CliRunner, args: list[str]) -> None:
        result = runner.invoke(main, ["cli", *args])
        assert result.exit_code == 2
        assert "No such option" in result.output

    @patch("cja_audit_log_monitor.cli.AuditLogMonitor")
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_tail_component_id_long_flag_works(
        self,
        mock_get_client: MagicMock,
        mock_nm: MagicMock,
        mock_monitor: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        mock_monitor.return_value.successful_polls = 1
        result = runner.invoke(main, ["cli", "tail", "--component-id", "x"])
        assert result.exit_code == 0

    @patch("cja_audit_log_monitor.cli.AuditLogMonitor")
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_monitor_duration_long_flag_works(
        self,
        mock_get_client: MagicMock,
        mock_nm: MagicMock,
        mock_monitor: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        mock_monitor.return_value.successful_polls = 1
        result = runner.invoke(main, ["cli", "monitor", "--duration", "5"])
        assert result.exit_code == 0
        mock_monitor.return_value.start.assert_called_once_with(duration=5)

    @pytest.mark.parametrize("command", ["stats", "top-users"])
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_top_uses_n(self, mock_get_client: MagicMock, runner: CliRunner, command: str) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        result = runner.invoke(main, ["cli", command, "-n", "3"])
        assert result.exit_code == 0

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_export_format_short_flag_is_capital_f(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (_fake_client(sample_audit_entries), _settings())
        result = runner.invoke(main, ["cli", "export", "-F", "csv", "-o", "-"])
        assert result.exit_code == 0
        assert result.stdout.startswith("id,")
        old = runner.invoke(main, ["cli", "export", "-f", "csv", "-o", "-"])
        assert old.exit_code == 2

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_choices_ignore_case(self, mock_get_client: MagicMock, runner: CliRunner) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        result = runner.invoke(main, ["cli", "find-action", "-a", "export"])
        assert result.exit_code == 0
        result = runner.invoke(main, ["cli", "list", "-F", "JSON"])
        assert result.exit_code == 0

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_query_presets_are_exclusive(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        result = runner.invoke(main, ["cli", "query", "--today", "--yesterday"])
        assert result.exit_code == 2
        assert "mutually exclusive" in result.output

    @pytest.mark.parametrize(
        "args", [["component", "-i", ""], ["dashboard", "-i", "  "], ["user", "-u", ""]]
    )
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_blank_ids_are_usage_errors(
        self, mock_get_client: MagicMock, runner: CliRunner, args: list[str]
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        result = runner.invoke(main, ["cli", *args])
        assert result.exit_code == 2
        mock_get_client.assert_not_called()

    def test_help_shows_real_defaults_and_hides_none(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cli", "list", "--help"], env={"COLUMNS": "200"})
        assert "default: 50" in " ".join(result.output.split())
        stats_help = runner.invoke(main, ["cli", "stats", "--help"], env={"COLUMNS": "200"})
        assert "[default: None]" not in stats_help.output
        assert "default_days from the config" in " ".join(stats_help.output.split())
        monitor_help = runner.invoke(main, ["cli", "monitor", "--help"], env={"COLUMNS": "200"})
        assert "[default: None]" not in monitor_help.output
        assert "monitor_interval from the config" in " ".join(monitor_help.output.split())


class TestJsonFormatEverywhere:
    """Every read command can print one JSON document on stdout; progress is on stderr."""

    @pytest.mark.parametrize(
        ("args", "keys"),
        [
            (["dashboard", "-i", "d1"], {"dashboard_id", "entries", "count"}),
            (["find-action", "-a", "CREATE"], {"action", "days", "entries", "count"}),
            (["top-users"], {"days", "users"}),
            (["timeline"], {"days", "daily", "hourly"}),
            (["anomalies"], {"anomalies", "count"}),
        ],
    )
    @pytest.mark.parametrize("empty", [False, True])
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_format_json_is_parseable(
        self,
        mock_get_client: MagicMock,
        mock_nm: MagicMock,
        runner: CliRunner,
        sample_audit_entries,
        args: list[str],
        keys: set[str],
        empty: bool,
    ) -> None:
        entries = [] if empty else sample_audit_entries
        client = _fake_client(entries)
        client.get_component_logs.return_value = entries
        mock_get_client.return_value = (client, _settings())
        nm = mock_nm.return_value.__enter__.return_value
        nm.is_configured.return_value = False
        nm.pop_failures.return_value = []

        result = runner.invoke(main, ["cli", *args, "-F", "json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert keys <= set(data)
        if "count" in data and "entries" in data:
            assert data["count"] == len(entries)


class TestSmallCliBehaviours:
    """Empty results say so, `show` searches deeply, tables fit 80 columns."""

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_anomalies_none_found_says_so_on_stdout(
        self, mock_get_client: MagicMock, mock_nm: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        nm = mock_nm.return_value.__enter__.return_value
        nm.is_configured.return_value = False
        nm.pop_failures.return_value = []

        result = runner.invoke(main, ["cli", "anomalies"])

        assert result.exit_code == 0, result.output
        assert "No anomalies found in the last 24 hours." in result.stdout

    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_anomalies_none_found_keeps_json_clean(
        self, mock_get_client: MagicMock, mock_nm: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        nm = mock_nm.return_value.__enter__.return_value
        nm.is_configured.return_value = False
        nm.pop_failures.return_value = []

        result = runner.invoke(main, ["cli", "anomalies", "-F", "json", "--lookback", "6"])

        assert json.loads(result.stdout) == {"anomalies": [], "count": 0}
        assert "No anomalies" not in result.stdout

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_show_finds_entry_on_third_page(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        from cja_audit_log_monitor.client import AuditLogsClient

        def make(i: int) -> AuditLogEntry:
            return AuditLogEntry(
                id=f"e{i}",
                timestamp=datetime(2026, 1, 1, tzinfo=UTC),
                user_id="u1",
                action="CREATE",
                component_type="PROJECT",
                component_name="Thing",
            )

        pages_requested: list[int] = []

        def get_logs(query):
            pages_requested.append(query.page)
            size = query.page_size
            start = query.page * size
            return AuditLogResponse(
                content=[make(i) for i in range(start, start + size)],
                last=False,
                number=query.page,
                total_pages=50,
            )

        class PagedClient(AuditLogsClient):
            def __init__(self) -> None:  # no network, no settings
                pass

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def get_logs(self, query=None):
                return get_logs(query)

        mock_get_client.return_value = (PagedClient(), _settings())

        result = runner.invoke(main, ["cli", "show", "e2500"])

        assert result.exit_code == 0, result.output
        assert "CREATE" in result.stdout
        assert pages_requested == [0, 1, 2]

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_stats_lists_top_users_once(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        mock_get_client.return_value = (_fake_client(sample_audit_entries), _settings())

        result = runner.invoke(main, ["cli", "stats"], env={"COLUMNS": "120"})

        assert result.exit_code == 0, result.output
        assert result.stdout.count("user0@example.com") == 1

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_list_details_fits_80_columns(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entry
    ) -> None:
        entry = sample_audit_entry.model_copy(
            update={"description": "A long description " * 5, "ip_address": "203.0.113.200"}
        )
        mock_get_client.return_value = (_fake_client([entry]), _settings())

        result = runner.invoke(main, ["cli", "list", "-D"], env={"COLUMNS": "80"})

        assert result.exit_code == 0, result.output
        assert max(len(line) for line in result.stdout.splitlines()) <= 80
        assert "203.0.113." in result.stdout  # the IP folds rather than widening the table
        assert "2024-01-15 10:30:00" in result.stdout

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_list_details_keeps_user_component_and_ip_readable_at_80(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entry
    ) -> None:
        entry = sample_audit_entry.model_copy(
            update={
                "user_email": "jordan.lee@example.com",
                "component_name": "Revenue per Visit (7d)",
                "description": "Deleted calculated metric Revenue per Visit",
                "ip_address": "203.0.113.200",
            }
        )
        mock_get_client.return_value = (_fake_client([entry]), _settings())

        result = runner.invoke(main, ["cli", "list", "-D"], env={"COLUMNS": "80"})

        assert result.exit_code == 0, result.output
        lines = result.stdout.splitlines()
        assert max(len(line) for line in lines) <= 80
        assert "jordan.l" in result.stdout
        assert any("IP 203.0.113.200" in line for line in lines)
        assert "Revenue" in result.stdout

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_search_accepts_short_details_flag(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entry
    ) -> None:
        mock_get_client.return_value = (_fake_client([sample_audit_entry]), _settings())

        result = runner.invoke(main, ["cli", "search", "-D"], env={"COLUMNS": "120"})

        assert result.exit_code == 0, result.output
        assert "Details" in result.stdout

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_timeline_json_has_same_hour_keys_when_empty(
        self, mock_get_client: MagicMock, runner: CliRunner
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())

        result = runner.invoke(main, ["cli", "timeline", "-F", "json"])

        assert result.exit_code == 0, result.output
        data = json.loads(result.stdout)
        assert data["daily"] == {}
        assert data["hourly"] == {f"{h:02d}": 0 for h in range(24)}

    @patch("cja_audit_log_monitor.cli.get_client")
    def test_show_not_found_reports_entries_actually_searched(
        self, mock_get_client: MagicMock, runner: CliRunner, sample_audit_entries
    ) -> None:
        client = _fake_client([])
        client.get_logs_paginated.return_value = iter(sample_audit_entries[:3])
        mock_get_client.return_value = (client, _settings())

        result = runner.invoke(main, ["cli", "show", "missing-id"])

        assert result.exit_code == 1
        assert "Searched 3 entries" in result.stderr
        assert "10,000" not in result.stderr

    def test_alerts_list_fits_80_columns_with_whole_names(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cli", "alerts", "list"], env={"COLUMNS": "80"})

        assert result.exit_code == 0, result.output
        assert max(len(line) for line in result.stdout.splitlines()) <= 80
        for name in ("bulk_delete", "bulk_export", "sensitive_component_delete", "bulk_share"):
            assert name in result.stdout


class TestWatchJsonAndHelpDefaults:
    @patch("cja_audit_log_monitor.cli._install_anomalies_signal_handlers")
    @patch("cja_audit_log_monitor.cli.time.sleep")
    @patch("cja_audit_log_monitor.cli.NotificationManager")
    @patch("cja_audit_log_monitor.cli.get_client")
    def test_watch_json_is_one_compact_object_per_line(
        self,
        mock_get_client: MagicMock,
        mock_nm: MagicMock,
        mock_sleep: MagicMock,
        mock_signals: MagicMock,
        runner: CliRunner,
    ) -> None:
        mock_get_client.return_value = (_fake_client([]), _settings())
        nm = mock_nm.return_value.__enter__.return_value
        nm.is_configured.return_value = False
        nm.pop_failures.return_value = []
        mock_sleep.side_effect = [None, KeyboardInterrupt]

        result = runner.invoke(main, ["cli", "anomalies", "--watch", "-F", "json"])

        lines = result.stdout.splitlines()
        assert len(lines) == 2
        assert [json.loads(line) for line in lines] == [{"anomalies": [], "count": 0}] * 2

    def test_help_defaults_match_settings(self, runner: CliRunner) -> None:
        from cja_audit_log_monitor.config import CJASettings

        fields = CJASettings.model_fields
        stats_help = " ".join(
            runner.invoke(main, ["cli", "stats", "--help"], env={"COLUMNS": "200"}).output.split()
        )
        monitor_help = " ".join(
            runner.invoke(main, ["cli", "monitor", "--help"], env={"COLUMNS": "200"}).output.split()
        )
        assert f"{fields['default_days'].default} if unset" in stats_help
        assert f"{fields['monitor_interval'].default} if unset" in monitor_help

    def test_anomalies_help_mentions_one_object_per_line(self, runner: CliRunner) -> None:
        out = " ".join(
            runner.invoke(
                main, ["cli", "anomalies", "--help"], env={"COLUMNS": "200"}
            ).output.split()
        )
        assert "with --watch, one JSON object per line" in out


# ---------------------------------------------------------------------------
# Guards that check what is sent and printed, not only the exit code (G38)
# ---------------------------------------------------------------------------


def test_verbose_logs_go_to_stderr_in_a_real_process(fake_api, tmp_path):
    """In a real process (where logging is really configured) -v never touches stdout."""
    import subprocess

    from .fakeapi import command, raw_entry

    fake_api.entries = [raw_entry(i) for i in range(3)]
    result = subprocess.run(
        [*command(), "-v", "cli", "list", "-F", "json"],
        env=fake_api.env(tmp_path / "missing.yaml"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert len(json.loads(result.stdout)["entries"]) == 3
    assert result.stderr.strip()  # the debug lines went somewhere: stderr


class TestFlagsReachTheRequest:
    """Each filter flag ends up in the query the client is asked for."""

    @staticmethod
    def _client():
        client = MagicMock()
        client.get_all_logs.return_value = []
        client.get_logs_paginated.return_value = iter([])
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        return client

    def _run(self, runner, args):
        client = self._client()
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", *args])
        assert result.exit_code == 0, result.output
        return client, client.get_all_logs.call_args.args[0]

    def test_search_sends_every_filter(self, runner: CliRunner) -> None:
        _, query = self._run(
            runner,
            [
                "search",
                "-u",
                "a@example.com",
                "-a",
                "DELETE",
                "-C",
                "PROJECT",
                "--component-id",
                "c-1",
                "--desc",
                "words",
            ],
        )
        params = query.to_query_params()
        assert params["userEmail"] == "a@example.com"
        assert params["action"] == ["DELETE"]
        assert params["component"] == ["PROJECT"]
        assert params["componentId"] == "c-1"
        assert params["description"] == "words"

    def test_user_sends_the_user(self, runner: CliRunner) -> None:
        _, query = self._run(runner, ["user", "-u", "a@example.com"])
        assert query.to_query_params()["userEmail"] == "a@example.com"

    def test_query_yesterday_is_the_day_before_today(self, runner: CliRunner) -> None:
        _, query = self._run(runner, ["query", "--yesterday"])
        today = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        assert query.start_date == today - timedelta(days=1)
        assert query.end_date <= today

    def test_top_users_honors_top(self, runner: CliRunner, sample_audit_entries) -> None:
        client = self._client()
        client.get_all_logs.return_value = sample_audit_entries
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "top-users", "-n", "1", "-F", "json"])
        assert result.exit_code == 0, result.output
        assert len(json.loads(result.stdout)["users"]) == 1


@pytest.mark.parametrize(
    ("flags", "shown", "hidden"),
    [
        (["--component-id", "c-mine"], "mine-comp", "other-comp"),
        (["-a", "DELETE"], "mine-comp", "other-comp"),
    ],
    ids=["component-id", "action"],
)
def test_tail_filters_by_component_and_action(runner: CliRunner, flags, shown, hidden) -> None:
    client = MagicMock()
    client.get_logs.return_value = AuditLogResponse(
        content=[
            AuditLogEntry(
                id="1", action="DELETE", component_id="c-mine", component_name="mine-comp"
            ),
            AuditLogEntry(
                id="2", action="CREATE", component_id="c-other", component_name="other-comp"
            ),
        ],
        last=True,
    )

    def fake_start(self, *args, **kwargs):
        for entry in self._get_new_entries():
            self._display_entry(entry)

    with (
        patch("cja_audit_log_monitor.cli.get_client") as gc,
        patch("cja_audit_log_monitor.cli.AuditLogMonitor.start", fake_start),
    ):
        gc.return_value = (client, MagicMock(alert_rules=[]))
        result = runner.invoke(main, ["cli", "tail", *flags, "--no-alerts"])
    assert result.exit_code == 0, result.output
    assert shown in result.output
    assert hidden not in result.output


@pytest.mark.parametrize("fmt", ["csv", "tsv"])
def test_delimited_export_does_not_clobber_a_file_created_during_fetch(
    runner: CliRunner, sample_audit_entries, tmp_path, fmt
) -> None:
    target = tmp_path / f"out.{fmt}"

    def entries_then_appear(*args, **kwargs):
        target.write_text("someone else")
        yield from sample_audit_entries

    client = MagicMock()
    client.get_logs_paginated.side_effect = entries_then_appear
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
        result = runner.invoke(main, ["cli", "export", "-F", fmt, "-o", str(target)])
    assert result.exit_code == 1
    assert target.read_text() == "someone else"


def test_cli_bad_config_is_one_line(bad_config) -> None:
    from .conftest import SECRET_MARK

    result = CliRunner().invoke(main, ["-c", str(bad_config), "cli", "list"])
    assert result.exit_code == 1
    assert result.exception is None or isinstance(result.exception, SystemExit)
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1, result.stderr
    assert lines[0].startswith("Configuration error:")
    assert SECRET_MARK not in result.output


def test_config_error_is_one_line(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("monitor_interval: 4\n")
    path.chmod(0o600)
    result = CliRunner().invoke(main, ["-c", str(path), "cli", "list"])
    assert result.exit_code == 1
    lines = [line for line in result.stderr.splitlines() if line.strip()]
    assert len(lines) == 1, result.stderr
    assert str(path) in lines[0]
    assert "monitor_interval" in lines[0]
    assert "pydantic.dev" not in result.stderr


def test_env_error_names_the_environment(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("API_BASE_URL", "http://example.com")
    result = CliRunner().invoke(main, ["-c", str(tmp_path / "missing.yaml"), "cli", "list"])
    assert result.exit_code == 1
    line = result.stderr.strip()
    assert line.startswith("Configuration error: environment or .env: api_base_url")
    assert "missing.yaml" not in line


def test_env_value_overriding_a_file_value_is_blamed_on_the_environment(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text("monitor_interval: 30\n")
    path.chmod(0o600)
    monkeypatch.setenv("monitor_interval", "4")
    with pytest.raises(Exception) as info:
        from cja_audit_log_monitor.config import load_config

        load_config(path)
    assert str(info.value).startswith("environment or .env: monitor_interval")


def test_cli_config_marks_a_missing_file(tmp_path) -> None:
    # "Config file: " plus a 60 character path ends near column 80, so a plain print would
    # break the line before "(not found)", as it did on the Linux CI runner.
    missing = "m" * 55 + ".yaml"  # relative to the test's working folder, tmp_path
    result = CliRunner().invoke(main, ["-c", missing, "cli", "config"])
    assert result.exit_code == 0
    assert f"{missing} (not found)" in result.stdout


def test_init_message_asks_for_scopes(tmp_path) -> None:
    result = CliRunner().invoke(main, ["-c", str(tmp_path / "c.yaml"), "cli", "init"])
    assert result.exit_code == 0
    assert "SCOPES=your_scopes_from_developer_console" in result.stdout
    assert ".env.example" not in result.stdout


def test_tail_prints_the_polling_line_once(runner: CliRunner) -> None:
    with (
        patch("cja_audit_log_monitor.cli.get_client") as gc,
        patch("cja_audit_log_monitor.cli.AuditLogMonitor.start", lambda self, *a, **k: None),
    ):
        client = MagicMock()
        gc.return_value = (client, MagicMock(alert_rules=[]))
        result = runner.invoke(main, ["cli", "tail", "--no-alerts"])
    assert result.output.lower().count("polling every") <= 1
    assert "Polling every" not in result.stderr


def test_monitor_hides_channel_summary_when_alert_delivery_is_off(runner: CliRunner) -> None:
    from cja_audit_log_monitor.config import CJASettings
    from cja_audit_log_monitor.models import NotificationConfig

    settings = CJASettings(
        _env_file=None,
        notifications=NotificationConfig(
            slack_webhook_url="https://hooks.slack.com/x", notify_on_alerts=False
        ),
    )
    with (
        patch("cja_audit_log_monitor.cli.get_client", return_value=(MagicMock(), settings)),
        patch("cja_audit_log_monitor.cli.AuditLogMonitor.start", lambda self, *a, **k: None),
        patch("cja_audit_log_monitor.cli.AuditLogMonitor.successful_polls", 1, create=True),
    ):
        result = runner.invoke(main, ["cli", "monitor"])
    assert "Notification channels" not in result.output


def test_exit_does_not_wait_for_an_abandoned_worker(monkeypatch) -> None:
    import threading

    from cja_audit_log_monitor import cli as cli_module

    exits: list[int] = []
    monkeypatch.setattr(cli_module.os, "_exit", exits.append)
    release = threading.Event()
    worker = threading.Thread(target=release.wait, args=(10,))
    worker.start()
    try:
        cli_module.exit_without_waiting_for_workers(0)
    finally:
        release.set()
        worker.join()
    assert exits == [0]


def test_exit_returns_normally_when_no_worker_is_left(monkeypatch) -> None:
    import threading

    from cja_audit_log_monitor import cli as cli_module

    exits: list[int] = []
    monkeypatch.setattr(cli_module.os, "_exit", exits.append)
    monkeypatch.setattr(cli_module.threading, "enumerate", lambda: [threading.main_thread()])
    cli_module.exit_without_waiting_for_workers(0)
    assert exits == []


class TestAnomalyDeliveryPerChannel:
    """Each anomaly reaches each channel once (G14, G15)."""

    SLACK = "https://hooks.slack.com/services/T/B/x"
    HOOK = "https://example.com/hook"

    @staticmethod
    def _client(entries_by_cycle):
        client = MagicMock()
        client.get_all_logs.side_effect = entries_by_cycle
        return client

    @staticmethod
    def _deletes(user="mallory@example.com", count=12):
        now = datetime(2026, 3, 1, 12, 30, tzinfo=UTC)  # midday: no off-hours anomaly
        return [
            AuditLogEntry(
                id=f"{user}-{i}",
                action="DELETE",
                user_email=user,
                timestamp=now - timedelta(minutes=i),
            )
            for i in range(count)
        ]

    def _manager(self, webhook=False):
        from cja_audit_log_monitor.models import NotificationConfig, WebhookConfig
        from cja_audit_log_monitor.notifications import NotificationManager

        hooks = [WebhookConfig(url=self.HOOK)] if webhook else []
        return NotificationManager(
            NotificationConfig(
                slack_webhook_url=self.SLACK,
                webhooks=hooks,
                notify_on_anomalies=True,
            )
        )

    def _cycles(self, nm, entries_by_cycle, monkeypatch=None, days=None):
        from cja_audit_log_monitor.cli import _run_anomalies_cycle
        from cja_audit_log_monitor.notifications import AnomalyDedupFilter

        client = self._client(entries_by_cycle)
        dedup = AnomalyDedupFilter()
        for index in range(len(entries_by_cycle)):
            if monkeypatch is not None and days is not None:
                monkeypatch.setattr(
                    "cja_audit_log_monitor.notifications._today_iso",
                    lambda d=days[index]: d,
                    raising=False,
                )
            _run_anomalies_cycle(client, nm, dedup, 24, watch=True)

    def _posts(self, httpx_mock, url):
        return [r for r in httpx_mock.get_requests() if str(r.url) == url]

    def test_failed_anomaly_delivery_is_retried_next_cycle(self, httpx_mock) -> None:
        httpx_mock.add_response(url=self.SLACK, status_code=503)
        httpx_mock.add_response(url=self.SLACK, status_code=200)
        self._cycles(self._manager(), [self._deletes(), self._deletes()])
        assert len(self._posts(httpx_mock, self.SLACK)) == 2

    def test_same_anomaly_not_resent_at_midnight(self, httpx_mock, monkeypatch) -> None:
        httpx_mock.add_response(url=self.SLACK, status_code=200)
        self._cycles(
            self._manager(),
            [self._deletes(), self._deletes()],
            monkeypatch,
            ["2026-03-01", "2026-03-02"],
        )
        assert len(self._posts(httpx_mock, self.SLACK)) == 1

    def test_cleared_then_returning_anomaly_is_sent_again(self, httpx_mock) -> None:
        httpx_mock.add_response(url=self.SLACK, status_code=200, is_reusable=True)
        self._cycles(self._manager(), [self._deletes(), [], self._deletes()])
        assert len(self._posts(httpx_mock, self.SLACK)) == 2

    def test_flapping_channel_delivers_once(self, httpx_mock) -> None:
        """Review Focus 5: Slack fails once, the webhook works; each gets one good post."""
        httpx_mock.add_response(url=self.SLACK, status_code=503)
        httpx_mock.add_response(url=self.SLACK, status_code=200)
        httpx_mock.add_response(url=self.HOOK, status_code=200)
        self._cycles(self._manager(webhook=True), [self._deletes()] * 3)
        assert len(self._posts(httpx_mock, self.HOOK)) == 1
        assert len(self._posts(httpx_mock, self.SLACK)) == 2  # one failure, one success


def test_verbose_does_not_log_httpcore_internals(fake_api, tmp_path) -> None:
    """-v shows the tool's own debug lines, not httpcore's (which dump raw headers)."""
    import subprocess

    from .fakeapi import command, raw_entry

    fake_api.entries = [raw_entry(1)]
    result = subprocess.run(
        [*command(), "-v", "cli", "list", "-F", "json"],
        env=fake_api.env(tmp_path / "missing.yaml"),
        cwd=tmp_path,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "receive_response_headers" not in result.stderr
    assert "send_request_headers" not in result.stderr


class TestExportPathChecks:
    """The CLI export path check runs before any request (G25, G44)."""

    @staticmethod
    def _run(args):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = CliRunner().invoke(main, ["cli", "export", *args])
        return result, client

    def test_dangling_symlink_needs_force(self, tmp_path) -> None:
        link = tmp_path / "out.json"
        link.symlink_to(tmp_path / "gone.json")
        result, client = self._run(["-o", str(link)])
        assert result.exit_code == 1
        assert "--force" in result.stderr
        client.get_all_logs.assert_not_called()

    def test_unwritable_folder_fails_before_fetch(self, tmp_path) -> None:
        import os

        if hasattr(os, "geteuid") and os.geteuid() == 0:
            pytest.skip("root can write anywhere")
        folder = tmp_path / "locked"
        folder.mkdir()
        folder.chmod(0o500)
        try:
            result, client = self._run(["-o", str(folder / "out.json")])
        finally:
            folder.chmod(0o700)
        assert result.exit_code == 1
        assert "cannot write" in result.stderr
        client.get_all_logs.assert_not_called()

    def test_cli_expands_tilde(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("HOME", str(tmp_path))
        (tmp_path / "out.json").write_text("old")
        result, client = self._run(["-o", "~/out.json"])
        assert result.exit_code == 1
        assert "already exists" in result.stderr
        client.get_all_logs.assert_not_called()


class TestEmptyAndCutExports:
    """An empty export writes an empty document; a cut export says so (G23, G44)."""

    @staticmethod
    def _run(args, entries):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs.side_effect = lambda q, max_entries=None: entries[:max_entries]
        client.get_logs_paginated.side_effect = lambda q: iter(entries)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            return CliRunner().invoke(main, ["cli", "export", *args])

    @pytest.mark.parametrize("fmt", ["json", "csv", "tsv"])
    @pytest.mark.parametrize("where", ["new", "force", "stdout"])
    def test_empty_export_writes_an_empty_document(self, tmp_path, fmt, where) -> None:
        target = tmp_path / f"out.{fmt}"
        args = ["-F", fmt]
        if where == "stdout":
            args += ["-o", "-"]
        else:
            if where == "force":
                target.write_text("yesterday")
                args.append("--force")
            args += ["-o", str(target)]
        result = self._run(args, [])
        assert result.exit_code == 0, result.output
        assert "No audit logs matched" in result.stderr
        text = result.stdout if where == "stdout" else target.read_text()
        if fmt == "json":
            data = json.loads(text)
            assert data["count"] == 0 and data["entries"] == []
        else:
            sep = "," if fmt == "csv" else "\t"
            lines = text.strip().splitlines()
            assert len(lines) == 1 and lines[0].startswith(f"id{sep}timestamp")

    @pytest.mark.parametrize("fmt", ["json", "csv"])
    def test_max_entries_cut_is_reported(self, tmp_path, sample_audit_entries, fmt) -> None:
        result = self._run(
            ["-F", fmt, "--max-entries", "3", "-o", str(tmp_path / f"o.{fmt}")],
            sample_audit_entries,
        )
        assert result.exit_code == 0, result.output
        assert "Exported 3 entries" in result.stderr
        assert "--max-entries" in result.stderr


def test_show_prints_changes(runner: CliRunner) -> None:
    entry = AuditLogEntry(id="c1", action="EDIT", changes={"name": {"old": "a", "new": "b"}})
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_logs_paginated.side_effect = lambda *a, **k: iter([entry])
    client.get_all_logs.return_value = [entry]
    with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
        result = runner.invoke(main, ["cli", "show", "c1"])
    assert result.exit_code == 0, result.output
    assert "Changes" in result.stdout
    assert '"old": "a"' in result.stdout


class TestExportFormatAndMessages:
    @staticmethod
    def _run(args, entries, during=None):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)

        def fetch(*a, **k):
            if during:
                during()
            return entries

        client.get_all_logs.side_effect = fetch
        client.get_logs_paginated.side_effect = lambda q: iter(fetch())
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            return CliRunner().invoke(main, ["cli", "export", *args])

    @pytest.mark.parametrize(("suffix", "first"), [("csv", "id,"), ("tsv", "id\t")])
    def test_format_from_suffix(self, tmp_path, sample_audit_entries, suffix, first) -> None:
        target = tmp_path / f"audit.{suffix}"
        result = self._run(["-o", str(target)], sample_audit_entries)
        assert result.exit_code == 0, result.output
        assert target.read_text().startswith(first)

    def test_explicit_format_wins_over_suffix(self, tmp_path, sample_audit_entries) -> None:
        target = tmp_path / "audit.csv"
        result = self._run(["-F", "json", "-o", str(target)], sample_audit_entries)
        assert result.exit_code == 0
        assert json.loads(target.read_text())["count"] == len(sample_audit_entries)

    def test_late_file_message_names_the_target_and_force(
        self, tmp_path, sample_audit_entries
    ) -> None:
        target = tmp_path / "out.json"
        result = self._run(
            ["-o", str(target)], sample_audit_entries, during=lambda: target.write_text("x")
        )
        assert result.exit_code == 1
        assert str(target) in result.stderr.replace("\n", "")
        assert "--force" in result.stderr
        assert ".tmp" not in result.stderr


HOSTILE_NAME = "\x1b]0;PWNED\x07\x1b[2J[/b] 日本 \ud83d"


def _hostile_entry() -> AuditLogEntry:
    return AuditLogEntry.model_validate(
        {
            "id": "h1",
            "dateCreated": "2026-01-15T10:00:00Z",
            "action": "DELETE",
            "componentName": HOSTILE_NAME,
            "componentType": "PROJECT",
            "user": {"id": "U1", "name": HOSTILE_NAME, "email": "h@example.com"},
            "description": HOSTILE_NAME,
        }
    )


@pytest.mark.parametrize(
    "args",
    [
        ["list"],
        ["list", "-D"],
        ["search"],
        ["show", "h1"],
        ["stats"],
        ["timeline"],
        ["top-users"],
        ["user", "-u", "h@example.com"],
        ["list", "-F", "json"],
    ],
    ids=lambda a: " ".join(a),
)
def test_hostile_names_on_every_output(args) -> None:
    """Review Focus 4: odd names reach no terminal as control codes, and nothing crashes."""
    entry = _hostile_entry()
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_all_logs.return_value = [entry]
    client.get_logs_paginated.side_effect = lambda *a, **k: iter([entry])
    client.get_logs_sample.return_value = ([entry], 1)
    with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
        result = CliRunner().invoke(main, ["cli", *args])
    assert result.exit_code == 0, result.output
    assert "\x1b]0;" not in result.output
    assert "\x1b[2J" not in result.output
    if "json" in args:
        json.loads(result.stdout)


@pytest.mark.parametrize("fmt", ["json", "csv", "tsv"])
def test_hostile_names_in_exports(fmt) -> None:
    from io import StringIO

    from cja_audit_log_monitor.export import export_entries

    out = StringIO()
    export_entries([_hostile_entry()], out, output_format=fmt)
    assert "\x1b" not in out.getvalue()


def test_hostile_names_in_slack() -> None:
    from cja_audit_log_monitor.notifications import NotificationManager

    payload = NotificationManager()._build_slack_payload("r", "m", _hostile_entry())
    assert "\x1b" not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
@pytest.mark.parametrize(
    "args",
    [
        ["list"],
        ["search"],
        ["query", "--today"],
        ["stats"],
        ["verify"],
        ["alerts", "list"],
        ["timeline"],
        ["show", "id-1"],
    ],
    ids=lambda a: " ".join(a),
)
def test_commands_run_on_a_narrow_stdout(fake_api, tmp_path, encoding, args) -> None:
    import subprocess

    from .fakeapi import command, raw_entry

    fake_api.entries = [raw_entry(1, componentName="日本 report")]
    env = fake_api.env(tmp_path / "missing.yaml")
    env["PYTHONIOENCODING"] = encoding
    result = subprocess.run(
        [*command(), "cli", *args],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert b"UnicodeEncodeError" not in result.stderr


def test_csv_to_stdout_is_utf8_on_cp1252(fake_api, tmp_path) -> None:
    import subprocess

    from .fakeapi import command, raw_entry

    fake_api.entries = [raw_entry(1, componentName="日本 report")]
    env = fake_api.env(tmp_path / "missing.yaml")
    env["PYTHONIOENCODING"] = "cp1252"
    result = subprocess.run(
        [*command(), "cli", "export", "-F", "csv", "-o", "-"],
        env=env,
        cwd=tmp_path,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    assert "日本 report" in result.stdout.decode("utf-8")


class TestOneLineErrors:
    @pytest.mark.parametrize(
        "args",
        [
            ["list", "-d", "100000000"],
            ["anomalies", "--lookback", "100000000"],
            ["stats", "-d", "4000"],
        ],
        ids=["list", "anomalies", "stats"],
    )
    def test_huge_days_is_a_usage_error(self, runner, args) -> None:
        result = runner.invoke(main, ["cli", *args])
        assert result.exit_code == 2

    def test_unexpected_error_is_one_line(self, runner) -> None:
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs.side_effect = ZeroDivisionError("odd")
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "list"])
        assert result.exit_code == 1
        lines = [line for line in result.stderr.splitlines() if line.strip()]
        assert lines == ["Unexpected error: ZeroDivisionError: odd"]


class TestFiltersAndDates:
    """Filters, limits and date ranges do what the flags say (G28, G29, G45)."""

    @staticmethod
    def _client():
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs.return_value = []
        client.get_component_logs.return_value = []
        return client

    def _run(self, args):
        client = self._client()
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = CliRunner().invoke(main, ["cli", *args])
        return result, client

    @pytest.mark.parametrize("command", [["component", "-i", "x"], ["dashboard", "-i", "x"]])
    def test_component_and_dashboard_fetch_only_the_limit(self, command) -> None:
        result, client = self._run([*command, "-l", "5"])
        assert result.exit_code == 0, result.output
        assert client.get_component_logs.call_args.kwargs.get("max_entries") == 5

    @pytest.mark.parametrize(
        "args",
        [
            ["search", "-u", ""],
            ["search", "--component-id", " "],
            ["search", "--desc", ""],
            ["query", "-u", ""],
            ["timeline", "-u", " "],
            ["tail", "-u", ""],
            ["tail", "--component-id", ""],
        ],
        ids=lambda a: " ".join(a),
    )
    def test_blank_filter_is_a_usage_error(self, args) -> None:
        result, client = self._run(args)
        assert result.exit_code == 2
        client.get_all_logs.assert_not_called()

    def test_filter_values_are_stripped(self) -> None:
        result, client = self._run(["user", "-u", " a@example.com "])
        assert result.exit_code == 0
        query = client.get_all_logs.call_args.args[0]
        assert query.to_query_params()["userEmail"] == "a@example.com"

    @pytest.mark.parametrize("value", ["2026-01-15", "20260115"])
    def test_end_date_forms_get_end_of_day(self, value) -> None:
        from cja_audit_log_monitor.cli import parse_date

        parsed = parse_date(value, end_of_day=True)
        assert (parsed.hour, parsed.minute, parsed.second) == (23, 59, 59)

    def test_ambiguous_date_is_a_usage_error(self) -> None:
        result, _ = self._run(["search", "-e", "2026-1-5"])
        assert result.exit_code == 2

    @pytest.mark.parametrize("value", ["0001-01-01T00:00+05:00", "9999-12-31T23:59-05:00"])
    def test_a_date_past_the_calendar_edge_is_a_usage_error(self, value) -> None:
        result, client = self._run(["search", "-s", value])
        assert result.exit_code == 2
        assert "out of range" in result.output
        assert "Traceback" not in result.output
        client.get_all_logs.assert_not_called()

    @pytest.mark.parametrize("args", [["-s", "2999-01-01"], ["-e", "1999-01-01"]])
    def test_one_sided_range_is_checked(self, args) -> None:
        result, client = self._run(["search", *args])
        assert result.exit_code == 2
        client.get_all_logs.assert_not_called()

    def test_offset_dates_are_sent_in_utc(self) -> None:
        from cja_audit_log_monitor.models import AuditLogQuery

        query = AuditLogQuery(
            start_date=datetime(2026, 1, 15, 5, 0, tzinfo=timezone(timedelta(hours=5))),
            end_date=datetime(2026, 1, 15, 6, 0, tzinfo=timezone(timedelta(hours=5))),
        )
        params = query.to_query_params()
        assert params["startDate"] == "2026-01-15T00:00:00+0000"
        assert params["endDate"] == "2026-01-15T01:00:00+0000"


class TestMessagesAndHelp:
    """Messages, help text and small CLI items (G45, G47, G48)."""

    @staticmethod
    def _client():
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs.return_value = []
        return client

    def test_empty_stats_json_has_user_count(self, runner) -> None:
        with patch(
            "cja_audit_log_monitor.cli.get_client", return_value=(self._client(), _settings())
        ):
            result = runner.invoke(main, ["cli", "stats", "-F", "json"])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["statistics"]["user_count"] == 0

    def test_ctrl_c_on_a_single_anomaly_scan_exits_1(self, runner) -> None:
        client = self._client()
        client.get_all_logs.side_effect = KeyboardInterrupt
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "anomalies"])
        assert result.exit_code == 1

    def test_show_prints_ids_and_dashes(self, runner) -> None:
        entry = AuditLogEntry(
            id="e1", user_id="U1@AdobeID", user_name="Una", component_id="c-9", action="EDIT"
        )
        client = self._client()
        client.get_logs_paginated.side_effect = lambda *a, **k: iter([entry])
        client.get_all_logs.return_value = [entry]
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "show", "e1"])
        assert result.exit_code == 0, result.output
        for text in ("e1", "U1@AdobeID", "Una", "c-9"):
            assert text in result.stdout
        assert "None" not in result.stdout

    @pytest.mark.parametrize("text", ["a\\[b]", "end\\\\", "end\\\\\\", ":smile: x"])
    def test_names_print_exactly(self, runner, text) -> None:
        entry = AuditLogEntry(id="e1", action="EDIT", component_name=text)
        client = self._client()
        client.get_all_logs.return_value = [entry]
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "list", "-D"])
        assert text in result.stdout.replace("\n", "")

    def test_403_names_the_product_profile(self, runner) -> None:
        from cja_audit_log_monitor.client import APIError

        client = self._client()
        client.get_all_logs.side_effect = APIError(
            "API request failed: 403 - {'error_code': '403003'}", status_code=403
        )
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "list"])
        assert "product profile" in result.stderr

    def test_rate_limit_message_shows_the_wait(self) -> None:
        from cja_audit_log_monitor.client import RateLimitError

        assert "45" in str(RateLimitError(retry_after=45))

    @pytest.mark.parametrize(
        ("command", "option"),
        [
            ("search", "--component"),
            ("export", "--action"),
            ("export", "--component"),
            ("query", "--action"),
            ("query", "--component"),
            ("timeline", "--action"),
            ("timeline", "--component"),
        ],
    )
    def test_repeatable_options_say_so(self, runner, command, option) -> None:
        result = runner.invoke(main, ["cli", command, "--help"], terminal_width=200)
        line = next(line for line in result.output.splitlines() if option in line)
        assert "more than once" in line

    def test_date_help_names_utc_and_end_of_day(self, runner) -> None:
        result = runner.invoke(main, ["cli", "search", "--help"], terminal_width=300)
        text = " ".join(result.output.split())
        assert "UTC" in text and "end of that day" in text

    def test_days_help_does_not_claim_a_fixed_default(self, runner) -> None:
        result = runner.invoke(main, ["cli", "stats", "--help"], terminal_width=300)
        assert "from config (7)" not in result.output
        assert "default_days" in result.output

    @pytest.mark.parametrize("command", ["user", "component", "dashboard"])
    def test_limit_help_is_honest(self, runner, command) -> None:
        result = runner.invoke(main, ["cli", command, "--help"], terminal_width=200)
        assert "Show all audit events" not in result.output


def test_verify_says_authentication_failed_for_an_ims_failure(runner) -> None:
    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.credential_source = ENV_SOURCE
    client.verify_connection.return_value = verify_result("bad_secret", error="invalid_client")
    with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
        result = runner.invoke(main, ["cli", "verify"])
    assert result.exit_code == 1
    assert "Authentication failed: invalid_client" in result.stdout
    assert "Sign-in: failed (bad_secret). Copy the client secret again" in result.stdout
    assert "Log fetch: not run" in result.stdout


def test_dns_failure_is_a_network_error_naming_the_host(sample_settings, httpx_mock) -> None:
    import httpx

    from cja_audit_log_monitor.auth import TokenManager

    httpx_mock.add_exception(httpx.ConnectError("[Errno 8] nodename nor servname"))
    with pytest.raises(Exception) as info:
        TokenManager(sample_settings).get_token()
    assert "could not reach ims-na1.adobelogin.com" in str(info.value)
    assert getattr(info.value, "network", False) is True


def test_cli_config_shows_the_org_id_in_full(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ORG_ID", "ABCDEF0123456789@AdobeOrg")
    monkeypatch.setenv("CLIENT_ID", "aaaa1111bbbb2222cccc3333dddd4444")
    monkeypatch.setenv("SECRET", "fake-secret-A-not-a-credential-0001")
    monkeypatch.setenv("SCOPES", "openid,AdobeID")
    result = CliRunner().invoke(main, ["-c", str(tmp_path / "x.yaml"), "cli", "config"])
    assert "ABCDEF0123456789@AdobeOrg" in result.stdout


@pytest.mark.parametrize("command", ["monitor", "tail"])
def test_interval_has_the_config_upper_limit(runner, command) -> None:
    """G56: the CLI --interval takes at most 86,400 seconds, like monitor_interval."""
    result = runner.invoke(main, ["cli", command, "-i", "86401"])
    assert result.exit_code == 2


def test_api_network_failure_is_a_network_error(runner) -> None:
    """G57: an API call that cannot reach the host reads like the login step does."""
    from cja_audit_log_monitor.client import APIError

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    client.get_all_logs.side_effect = APIError(
        "could not reach cja.adobe.io (ConnectError)", network=True
    )
    with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
        result = runner.invoke(main, ["cli", "list"])
    assert result.stderr.startswith("Network error: could not reach cja.adobe.io")


@pytest.mark.parametrize("given", ["ALICE@example.com", "Alice Smith", "u-alice"])
def test_tail_user_matches_like_rule_users(runner: CliRunner, given) -> None:
    """tail -u matches id, email or name in any case, the same way rule `users` do."""
    client = MagicMock()
    client.get_logs.return_value = AuditLogResponse(
        content=[
            AuditLogEntry(
                id="1",
                action="CREATE",
                user_id="U-ALICE",
                user_email="alice@example.com",
                user_name="alice smith",
                component_name="mine-comp",
            ),
            AuditLogEntry(
                id="2", action="CREATE", user_email="bob@example.com", component_name="other-comp"
            ),
        ],
        last=True,
    )

    def fake_start(self, *args, **kwargs):
        for entry in self._get_new_entries():
            self._display_entry(entry)

    with (
        patch("cja_audit_log_monitor.cli.get_client") as gc,
        patch("cja_audit_log_monitor.cli.AuditLogMonitor.start", fake_start),
    ):
        gc.return_value = (client, MagicMock(alert_rules=[]))
        result = runner.invoke(main, ["cli", "tail", "-u", given, "--no-alerts"])
    assert result.exit_code == 0, result.output
    assert "mine-comp" in result.output
    assert "other-comp" not in result.output


@pytest.mark.parametrize(("status", "retried"), [(418, True), (400, False)])
def test_anomalies_watch_uses_the_shared_retry_policy(runner, status, retried) -> None:
    from cja_audit_log_monitor.client import APIError

    client = MagicMock()
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    with (
        patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())),
        patch(
            "cja_audit_log_monitor.cli._run_anomalies_cycle",
            side_effect=[APIError("x", status_code=status), None],
        ) as cycle,
        patch("cja_audit_log_monitor.cli.time.sleep", side_effect=[None, KeyboardInterrupt]),
    ):
        result = runner.invoke(main, ["cli", "anomalies", "--watch", "--interval", "5"])
    assert (cycle.call_count == 2) is retried
    assert (result.exit_code == 0) is retried


class TestCountWording:
    """Counts read "1 entry", and empty results use one wording (G47)."""

    @staticmethod
    def _run(args, entries):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs.return_value = entries
        client.get_component_logs.return_value = entries
        client.get_logs_paginated.side_effect = lambda *a, **k: iter(entries)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            return CliRunner().invoke(main, ["cli", *args])

    @pytest.mark.parametrize(
        "args",
        [
            ["list"],
            ["search"],
            ["user", "-u", "a@example.com"],
            ["component", "-i", "c"],
            ["dashboard", "-i", "d"],
            ["query", "--today"],
        ],
        ids=lambda a: a[0],
    )
    def test_one_entry_is_singular(self, sample_audit_entry, args) -> None:
        result = self._run(args, [sample_audit_entry])
        assert result.exit_code == 0, result.output
        assert "1 entries" not in result.output
        assert re.search(r"\b1 (matching )?entry\b", result.output)

    @pytest.mark.parametrize(
        "args",
        [
            ["list"],
            ["search"],
            ["user", "-u", "a@example.com"],
            ["component", "-i", "c"],
            ["dashboard", "-i", "d"],
            ["query", "--today"],
            ["stats"],
            ["timeline"],
            ["top-users"],
        ],
        ids=lambda a: a[0],
    )
    def test_empty_results_use_one_wording(self, args) -> None:
        result = self._run(args, [])
        assert result.exit_code == 0, result.output
        assert "No audit logs found" in result.output

    def test_export_of_one_entry(self, tmp_path, sample_audit_entry) -> None:
        result = self._run(["export", "-o", str(tmp_path / "o.json")], [sample_audit_entry])
        assert "Exported 1 entry " in result.stderr


@pytest.mark.parametrize("signal_name", ["SIGTERM", "SIGHUP"])
def test_signal_during_export_leaves_no_temp_file(fake_api, tmp_path, signal_name) -> None:
    """G44: a stopped export removes its hidden temp file."""
    import signal
    import subprocess

    from .fakeapi import command, raw_entry

    fake_api.entries = [raw_entry(i) for i in range(1500)]  # two pages of 1,000
    fake_api.block_after = 1  # hold the second page, while the temp file is open
    out = tmp_path / "out"
    out.mkdir()
    proc = subprocess.Popen(
        [*command(), "cli", "export", "-F", "csv", "-o", str(out / "audit.csv")],
        env=fake_api.env(tmp_path / "missing.yaml"),
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    try:
        assert fake_api.blocked.wait(30)
        proc.send_signal(getattr(signal, signal_name))
        # Generous: with pytest-xdist the machine is busy, and a hang still fails here.
        proc.communicate(timeout=30)
    finally:
        fake_api.block.clear()
        if proc.poll() is None:
            proc.kill()
    assert list(out.iterdir()) == []
    assert proc.returncode != 0


class TestOneJsonShape:
    """Users are objects and hours are "00" to "23" in every JSON output (G45)."""

    @staticmethod
    def _run(args, entries):
        client = MagicMock()
        client.__enter__ = MagicMock(return_value=client)
        client.__exit__ = MagicMock(return_value=False)
        client.get_all_logs.return_value = entries
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            return CliRunner().invoke(main, ["cli", *args])

    def test_stats_top_users_are_objects(self, sample_audit_entries) -> None:
        data = json.loads(self._run(["stats", "-F", "json"], sample_audit_entries).stdout)
        users = data["statistics"]["top_users"]
        assert users and all(set(u) == {"user", "count"} for u in users)

    def test_report_hours_and_users(self, sample_audit_entries) -> None:
        data = json.loads(self._run(["report"], sample_audit_entries).stdout)
        assert list(data["hourly_distribution"])[:2] == ["00", "01"]
        assert all(set(u) == {"user", "count"} for u in data["summary"]["top_users"])
        assert all(set(u) == {"user", "count"} for u in data["user_activity"])


def _client_with(entries: list) -> MagicMock:
    """A mock client used as a context manager that returns ``entries``."""
    client = MagicMock()
    client.get_all_logs.return_value = entries
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    return client


def _night_deletes(count: int, user: str = "night@example.com") -> list[AuditLogEntry]:
    """``count`` deletes by one user at about 2am UTC, a minute apart."""
    return [
        AuditLogEntry(
            id=f"del-{i}",
            timestamp=datetime(2024, 1, 15, 2, i, 0, tzinfo=UTC),
            user_id=user,
            user_email=user,
            action="DELETE",
            component_type="PROJECT",
            component_id=f"p-{i}",
            component_name=f"Project {i}",
        )
        for i in range(count)
    ]


class TestAlertsTestCommand:
    """`cli alerts test` runs the real rules and anomaly checks on fetched logs."""

    @staticmethod
    def _run(runner: CliRunner, entries: list):
        settings = MagicMock(alert_rules=None, default_days=7)
        with patch(
            "cja_audit_log_monitor.cli.get_client",
            return_value=(_client_with(entries), settings),
        ):
            return runner.invoke(main, ["cli", "alerts", "test", "--days", "2"])

    def test_no_logs(self, runner: CliRunner) -> None:
        result = self._run(runner, [])
        assert result.exit_code == 0
        assert "No audit logs found." in result.output

    def test_bulk_deletes_fire_an_alert(self, runner: CliRunner) -> None:
        result = self._run(runner, _night_deletes(6))
        assert result.exit_code == 0, result.output
        assert "Found 1 alerts" in result.output
        assert "bulk_delete" in result.output

    def test_quiet_logs_trigger_nothing(self, runner: CliRunner, sample_audit_entries) -> None:
        creates = [e for e in sample_audit_entries if e.action == "CREATE"]
        result = self._run(runner, creates)
        assert result.exit_code == 0, result.output
        assert "No alerts triggered." in result.output


class TestCommandEdges:
    """Output branches that the main command tests do not reach."""

    @pytest.mark.parametrize(
        ("args", "expected"),
        [
            (["list", "--output-format", "json"], {"entries": [], "count": 0}),
            (["query", "--output-format", "json"], {"entries": [], "count": 0}),
            (
                ["user", "--user-id", "a@example.com", "--output-format", "json"],
                {"user": "a@example.com", "entries": [], "count": 0},
            ),
        ],
    )
    def test_empty_results_as_json(self, runner: CliRunner, args, expected) -> None:
        with patch(
            "cja_audit_log_monitor.cli.get_client", return_value=(_client_with([]), _settings())
        ):
            result = runner.invoke(main, ["cli", *args])
        assert result.exit_code == 0, result.output
        assert json.loads(result.output) == expected

    def test_query_last_month_lists_entries(self, runner: CliRunner, sample_audit_entries) -> None:
        client = _client_with(sample_audit_entries)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "query", "--last-month"])
        assert result.exit_code == 0, result.output
        assert "Found 10 entries (last 30 days)" in " ".join(result.output.split())
        query = client.get_all_logs.call_args.args[0]
        assert query.end_date - query.start_date == timedelta(days=30)

    def test_query_json_lists_entries(self, runner: CliRunner, sample_audit_entries) -> None:
        client = _client_with(sample_audit_entries)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "query", "--output-format", "json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["count"] == 10
        assert data["entries"][0]["id"] == "entry-0"

    def test_unknown_component_is_a_usage_error(self, runner: CliRunner) -> None:
        result = runner.invoke(main, ["cli", "search", "--component", "nope"])
        assert result.exit_code == 2
        assert "Invalid component: nope" in result.output

    def test_find_action_with_no_matches(self, runner: CliRunner) -> None:
        with patch(
            "cja_audit_log_monitor.cli.get_client", return_value=(_client_with([]), _settings())
        ):
            result = runner.invoke(main, ["cli", "find-action", "--action", "DELETE"])
        assert result.exit_code == 0
        assert "No DELETE actions found." in result.output

    def test_find_action_lists_matches(self, runner: CliRunner) -> None:
        with patch(
            "cja_audit_log_monitor.cli.get_client",
            return_value=(_client_with(_night_deletes(2)), _settings()),
        ):
            result = runner.invoke(main, ["cli", "find-action", "--action", "DELETE"])
        assert result.exit_code == 0, result.output
        assert "Found 2 DELETE actions" in result.output

    def test_stats_shows_users_actions_and_anomalies(self, runner: CliRunner) -> None:
        with patch(
            "cja_audit_log_monitor.cli.get_client",
            return_value=(_client_with(_night_deletes(6)), _settings()),
        ):
            result = runner.invoke(main, ["cli", "stats", "--days", "2"])
        assert result.exit_code == 0, result.output
        assert "Most Active Users" in result.output
        assert "Potential Anomalies Detected" in result.output

    def test_verify_reports_a_failed_connection(self, runner: CliRunner) -> None:
        client = _client_with([])
        client.credential_source = ENV_SOURCE
        client.verify_connection.return_value = verify_result(
            product="unreachable", error="boom [x]"
        )
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "verify"])
        assert result.exit_code == 1
        assert "Connection failed" in result.output
        assert "Error: boom [x]" in result.output
        assert "Sign-in: ok" in result.output
        assert "Log fetch: failed (unreachable). Check the network" in result.output

    def test_api_network_error_is_labelled(self, runner: CliRunner) -> None:
        from cja_audit_log_monitor.client import APIError

        client = _client_with([])
        client.get_all_logs.side_effect = APIError("could not reach cja.adobe.io", network=True)
        with patch("cja_audit_log_monitor.cli.get_client", return_value=(client, _settings())):
            result = runner.invoke(main, ["cli", "list"])
        assert result.exit_code == 1
        assert "Network error: could not reach cja.adobe.io" in result.output

    def test_init_keeps_an_existing_file_when_declined(self, runner: CliRunner, tmp_path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("org_id: keep\n")
        result = runner.invoke(main, ["-c", str(path), "cli", "init"], input="n\n")
        assert result.exit_code == 0
        assert path.read_text() == "org_id: keep\n"

    def test_tui_command_runs_the_tui_with_the_config_path(self, runner: CliRunner, tmp_path):
        path = tmp_path / "config.yaml"
        with patch("cja_audit_log_monitor.cli.run_tui") as run_tui:
            result = runner.invoke(main, ["-c", str(path), "tui"])
        assert result.exit_code == 0
        run_tui.assert_called_once_with(path, None)

    def test_run_tui_uses_its_own_loop_and_exits_with_the_app_code(self) -> None:
        from cja_audit_log_monitor import cli

        app = MagicMock(return_code=3)
        with (
            patch("cja_audit_log_monitor.tui.CJAAuditApp", return_value=app) as make_app,
            patch.object(cli, "exit_without_waiting_for_workers") as exit_now,
        ):
            cli.run_tui(None)
        make_app.assert_called_once_with(None, profile=None, settings=ANY)
        loop = app.run.call_args.kwargs["loop"]
        assert loop.is_closed()
        exit_now.assert_called_once_with(3)


class TestParseDateEdges:
    def test_a_date_shaped_but_impossible_value_is_rejected(self) -> None:
        import click

        with pytest.raises(click.BadParameter, match="is not a date"):
            parse_date("2024-02-30")
