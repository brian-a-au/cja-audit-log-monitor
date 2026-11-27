"""Tests for configuration module."""

import logging
import stat
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml
from pydantic import ValidationError

from cja_audit_log_monitor.config import (
    CJASettings,
    ConfigError,
    create_default_config,
    load_config,
)
from cja_audit_log_monitor.utils import display_path


class TestCJASettings:
    """Tests for CJASettings class."""

    def test_default_values(self) -> None:
        """Test default settings values."""
        settings = CJASettings()
        assert settings.default_page_size == 100
        assert settings.default_days == 7
        assert settings.api_base_url == "https://cja.adobe.io"

    def test_scopes_list(self) -> None:
        """Test scopes_list property."""
        settings = CJASettings(scopes="openid, AdobeID, extra")
        assert settings.scopes_list == ["openid", "AdobeID", "extra"]

    def test_scopes_list_empty(self) -> None:
        """Test scopes_list with empty string."""
        settings = CJASettings(scopes="")
        assert settings.scopes_list == []

    def test_is_oauth_configured_false(self) -> None:
        """Test OAuth configuration check returns False when not configured."""
        # Explicitly create with empty credentials, bypassing .env
        settings = CJASettings(
            client_id="",
            secret="",
            org_id="",
            _env_file=None,
        )
        assert not settings.is_oauth_configured()

    def test_is_oauth_configured_true(self) -> None:
        """Test OAuth configuration check returns True when configured."""
        settings = CJASettings(
            client_id="id",
            secret="mysecret",
            org_id="org@AdobeOrg",
            scopes="openid",
        )
        assert settings.is_oauth_configured()

    def test_is_oauth_configured_needs_scopes(self) -> None:
        """The tool has no built-in scopes, so a credential without scopes is not complete."""
        settings = CJASettings(client_id="id", secret="mysecret", org_id="org@AdobeOrg")
        assert settings.scopes == ""
        assert not settings.is_oauth_configured()

    def test_is_oauth_configured_partial(self) -> None:
        """Test OAuth configuration check returns False when partially configured."""
        settings = CJASettings(
            client_id="id",
            secret="",  # Missing
            org_id="org@AdobeOrg",
        )
        assert not settings.is_oauth_configured()

    def test_org_id_validation(self) -> None:
        """Test org_id must end with @AdobeOrg."""
        import pytest

        with pytest.raises(ValueError, match="must end with @AdobeOrg"):
            CJASettings(org_id="invalid_org_id")


class TestLoadConfig:
    """Tests for load_config function."""

    def test_load_from_yaml(self) -> None:
        """Test loading config from YAML file."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_data = {
                "default_page_size": 50,
                "default_days": 14,
            }
            with open(config_path, "w") as f:
                yaml.safe_dump(config_data, f)

            settings = load_config(config_path)
            assert settings.default_page_size == 50
            assert settings.default_days == 14

    def test_load_nonexistent_file(self) -> None:
        """A config file that was named and does not exist is an error, not the defaults."""
        with pytest.raises(ConfigError, match=r"^/nonexistent/config\.yaml: does not exist"):
            load_config(Path("/nonexistent/config.yaml"))

    def test_load_empty_file(self) -> None:
        """Test loading empty config file uses defaults."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            config_path.touch()

            settings = load_config(config_path)
            assert settings.default_page_size == 100  # Default value


class TestBadConfigFile:
    """A bad config file raises ConfigError naming the file."""

    @pytest.mark.parametrize(
        "text", ["- a\n- b\n", "hello\n", "monitor_interval: [1, \n", "monitor_interval: abc\n"]
    )
    def test_invalid_file_raises_config_error(self, tmp_path: Path, text: str) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(text)
        with pytest.raises(ConfigError, match=str(path)):
            load_config(path)

    def test_output_format_is_not_a_setting(self) -> None:
        assert "output_format" not in CJASettings.model_fields

    def test_old_config_with_output_format_still_loads(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("default_days: 3\noutput_format: table\n")
        with caplog.at_level("WARNING"):
            settings = load_config(path)
        assert settings.default_days == 3
        assert "output_format" in caplog.text

    @pytest.mark.parametrize(
        "line",
        [
            "default_page_size: 0",
            "default_page_size: 1001",
            "default_days: 0",
            "monitor_interval: 4",
        ],
    )
    def test_out_of_range_values_are_rejected(self, tmp_path: Path, line: str) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(line + "\n")
        with pytest.raises(ConfigError, match=line.split(":")[0]):
            load_config(path)

    def test_large_interval_and_days_are_accepted(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: 7200\ndefault_days: 400\n")
        settings = load_config(path)
        assert (settings.monitor_interval, settings.default_days) == (7200, 400)

    def test_range_edges_are_accepted(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("default_page_size: 1000\ndefault_days: 1\nmonitor_interval: 5\n")
        settings = load_config(path)
        assert (settings.default_page_size, settings.default_days) == (1000, 1)
        assert settings.monitor_interval == 5

    def test_unknown_key_warns(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_intervall: 5\n")
        with caplog.at_level("WARNING"):
            load_config(path)
        assert "monitor_intervall" in caplog.text


class TestConfigPriority:
    """Env vars and .env beat the config file; init kwargs beat everything."""

    def test_env_beats_config_file(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("default_days: 3\nmonitor_interval: 10\n")
        monkeypatch.setenv("DEFAULT_DAYS", "5")
        settings = load_config(path)
        assert settings.default_days == 5
        assert settings.monitor_interval == 10

    def test_dotenv_beats_config_file(self, tmp_path) -> None:
        (tmp_path / ".env").write_text("MONITOR_INTERVAL=77\n")
        path = tmp_path / "c.yaml"
        path.write_text("monitor_interval: 10\n")
        assert load_config(path).monitor_interval == 77

    def test_init_kwargs_beat_env(self, monkeypatch) -> None:
        monkeypatch.setenv("CLIENT_ID", "from_env")
        assert CJASettings(client_id="explicit").client_id == "explicit"

    def test_config_file_does_not_leak_between_calls(self, tmp_path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("monitor_interval: 10\n")
        assert load_config(path).monitor_interval == 10
        assert CJASettings().monitor_interval == 60


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
class TestPrivateConfigFiles:
    def test_default_config_is_private(self, tmp_path: Path) -> None:
        folder = tmp_path / "d"
        path = create_default_config(folder / "config.yaml")
        assert stat.S_IMODE(folder.stat().st_mode) == 0o700
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_overwrite_keeps_file_private(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("x: 1\n")
        path.chmod(0o644)
        create_default_config(path)
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    def test_load_warns_when_file_is_readable_by_others(self, tmp_path: Path, caplog) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: 10\n")
        path.chmod(0o644)
        with caplog.at_level(logging.WARNING):
            load_config(path)
        assert "chmod 600" in caplog.text

    def test_load_is_quiet_for_private_file(self, tmp_path: Path, caplog) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: 10\n")
        path.chmod(0o600)
        with caplog.at_level(logging.WARNING):
            load_config(path)
        assert "chmod 600" not in caplog.text


class TestEndpointUrls:
    @pytest.mark.parametrize("field", ["ims_base_url", "api_base_url"])
    def test_plain_http_to_remote_host_rejected(self, field: str) -> None:
        with pytest.raises(ValidationError):
            CJASettings(**{field: "http://evil.example"})

    @pytest.mark.parametrize("field", ["ims_base_url", "api_base_url"])
    @pytest.mark.parametrize(
        "url", ["http://localhost:8080", "http://127.0.0.1:9", "https://example.com"]
    )
    def test_allowed_urls(self, field: str, url: str) -> None:
        assert getattr(CJASettings(**{field: url}), field) == url

    def test_other_schemes_rejected(self) -> None:
        with pytest.raises(ValidationError):
            CJASettings(api_base_url="ftp://example.com")


class TestCreateDefaultConfig:
    """Tests for create_default_config function."""

    def test_creates_valid_yaml(self) -> None:
        """Test that created config is valid YAML."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            create_default_config(config_path)

            with open(config_path) as f:
                config = yaml.safe_load(f)

            assert config["api_base_url"] == "https://cja.adobe.io"
            assert config["ims_base_url"] == "https://ims-na1.adobelogin.com"

    def test_creates_directory(self) -> None:
        """Test create_default_config creates parent directory."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "nested" / "config.yaml"
            create_default_config(config_path)

            assert config_path.exists()

    def test_returns_path(self) -> None:
        """Test create_default_config returns the path."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            result = create_default_config(config_path)

            assert result == config_path

    def test_default_config_template_includes_notifications_block(self, tmp_path: Path) -> None:
        """create_default_config writes a commented notifications: example."""
        config_file = tmp_path / "config.yaml"
        create_default_config(config_file)
        text = config_file.read_text()

        assert "# notifications:" in text
        assert "slack_webhook_url" in text
        assert "webhooks:" in text


class TestCreateDefaultConfigAnomalies:
    """Tests that the init template documents the anomalies command."""

    def test_template_mentions_anomalies_command(self, tmp_path):
        from cja_audit_log_monitor.config import create_default_config

        out = create_default_config(tmp_path / "config.yaml")
        content = out.read_text()
        assert "cja-audit-log-monitor cli anomalies" in content


def test_settings_no_top_level_slack_field() -> None:
    """The dead top-level slack_webhook_url field has been removed."""
    s = CJASettings()
    assert not hasattr(s, "slack_webhook_url"), (
        "Top-level slack_webhook_url is dead — use settings.notifications.slack_webhook_url"
    )


def test_secret_hidden_everywhere() -> None:
    s = CJASettings(org_id="X@AdobeOrg", client_id="c", secret="SENTINEL")
    for text in (repr(s), str(s), s.model_dump_json()):
        assert "SENTINEL" not in text
    assert s.secret.get_secret_value() == "SENTINEL"


def test_webhook_urls_hidden_from_repr() -> None:
    from cja_audit_log_monitor.models import NotificationConfig, WebhookConfig

    hook = WebhookConfig(url="https://h/x?token=T", headers={"Authorization": "HDRSECRET"})
    assert "token=T" not in repr(hook)
    assert "HDRSECRET" not in repr(hook)
    notif = NotificationConfig(slack_webhook_url="https://hooks.slack.com/SLACKSECRET")
    assert "SLACKSECRET" not in repr(notif)


class TestConfigErrorHidesInput:
    """Config errors must not echo input values (webhook headers, URLs, secrets)."""

    def test_webhook_typo_does_not_leak_header_or_url(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text(
            "notifications:\n"
            "  webhooks:\n"
            "    - urll: https://hooks.example.com/SECRETPATH\n"
            "      headers:\n"
            "        Authorization: Bearer HDRTOK\n"
        )
        with pytest.raises(ConfigError) as excinfo:
            load_config(path)
        text = str(excinfo.value)
        assert "HDRTOK" not in text
        assert "SECRETPATH" not in text
        assert "input_value" not in text
        assert "urll" not in text or "input_value" not in text

    def test_summary_is_one_line_with_location_and_message(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: abc\n")
        with pytest.raises(ConfigError) as excinfo:
            load_config(path)
        summary = excinfo.value.summary
        assert "\n" not in summary
        assert summary.startswith("config.yaml: monitor_interval: ")
        assert "valid integer" in summary

    def test_summary_for_yaml_error_is_one_line(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: [1, \n")
        with pytest.raises(ConfigError) as excinfo:
            load_config(path)
        assert "\n" not in excinfo.value.summary
        assert excinfo.value.summary.startswith("config.yaml: ")


class TestAlertRuleConfig:
    def test_unknown_action_loads_with_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("alert_rules:\n  - name: r\n    actions: [DELETE, ARCHIVE]\n")
        with caplog.at_level("WARNING"):
            settings = load_config(path)
        assert settings.alert_rules[0].actions == ["DELETE", "ARCHIVE"]
        assert "ARCHIVE" in caplog.text
        assert "DELETE" not in caplog.text

    def test_bad_threshold_is_config_error_without_input(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("alert_rules:\n  - name: r\n    threshold_count: 0\n")
        with pytest.raises(ConfigError) as excinfo:
            load_config(path)
        assert "input_value" not in str(excinfo.value)


def test_no_config_mistake_crashes_or_leaks(bad_config) -> None:
    """Review Focus 2: every config mistake is a ConfigError that shows no secret."""
    from .conftest import SECRET_MARK

    with pytest.raises(ConfigError) as info:
        load_config(bad_config)
    assert SECRET_MARK not in str(info.value)
    assert SECRET_MARK not in info.value.summary
    assert "\n" not in info.value.summary


@pytest.mark.parametrize(
    ("yaml_text", "where", "key"),
    [
        ("alert_rules:\n  - name: r\n    treshold_count: 5\n", "alert_rules[0]", "treshold_count"),
        ("alert_rules:\n  - name: r\n    per-user: true\n", "alert_rules[0]", "per-user"),
        (
            "notifications:\n  slack_webhook: https://x.example.com\n",
            "notifications",
            "slack_webhook",
        ),
        (
            "notifications:\n  webhooks:\n    - url: https://x.example.com\n      time_out: 5\n",
            "notifications.webhooks[0]",
            "time_out",
        ),
    ],
    ids=["rule-typo", "rule-dash", "slack-typo", "webhook-typo"],
)
def test_nested_typo_warns(tmp_path, caplog, yaml_text, where, key) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text)
    path.chmod(0o600)
    with caplog.at_level(logging.WARNING):
        load_config(path)
    expected = f"{display_path(path)}: {where}: ignoring unknown setting {key!r}"
    assert expected in caplog.text


def _uncomment_rules(text: str) -> str:
    """Remove the '# ' marks from the commented alert_rules block, as the docs say to."""
    out, inside = [], False
    for line in text.splitlines():
        if line.startswith("# alert_rules:"):
            inside = True
        elif inside and not line.startswith("#   "):
            inside = False
        out.append(line[2:] if inside else line)
    return "\n".join(out) + "\n"


def test_uncommented_template_keeps_the_builtin_rules(tmp_path) -> None:
    from cja_audit_log_monitor.alerts import DEFAULT_ALERT_RULES

    path = create_default_config(tmp_path / "config.yaml")
    path.write_text(_uncomment_rules(path.read_text()))
    names = [rule.name for rule in load_config(path).alert_rules]
    assert names == [rule.name for rule in DEFAULT_ALERT_RULES]
    loaded = {rule.name: rule for rule in load_config(path).alert_rules}
    for rule in DEFAULT_ALERT_RULES:
        assert loaded[rule.name] == rule


def test_init_leaves_an_existing_folder_mode(tmp_path) -> None:
    folder = tmp_path / "shared"
    folder.mkdir()
    folder.chmod(0o755)
    create_default_config(folder / "config.yaml")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o755


def test_init_makes_a_new_folder_private(tmp_path) -> None:
    folder = tmp_path / "new"
    create_default_config(folder / "config.yaml")
    assert stat.S_IMODE(folder.stat().st_mode) == 0o700


def test_init_refuses_a_symlink(tmp_path) -> None:
    target = tmp_path / "important.txt"
    target.write_text("keep me")
    link = tmp_path / "config.yaml"
    link.symlink_to(target)
    with pytest.raises(ConfigError):
        create_default_config(link)
    assert target.read_text() == "keep me"


@pytest.mark.parametrize(
    ("text", "field"),
    [("monitor_interval: 86401\n", "monitor_interval"), ("default_days: 3651\n", "default_days")],
)
def test_upper_limits(tmp_path, text, field) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(text)
    path.chmod(0o600)
    with pytest.raises(ConfigError, match=field):
        load_config(path)


def test_values_at_the_upper_limits_load(tmp_path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("monitor_interval: 86400\ndefault_days: 3650\n")
    path.chmod(0o600)
    settings = load_config(path)
    assert (settings.monitor_interval, settings.default_days) == (86400, 3650)


def test_endpoint_with_userinfo_is_rejected() -> None:
    with pytest.raises(ValidationError):
        CJASettings(api_base_url="https://user:pass@cja.adobe.io")


def test_tilde_config_path_is_expanded(monkeypatch) -> None:
    from cja_audit_log_monitor.config import get_config_path

    monkeypatch.setenv("CJA_CONFIG_PATH", "~/x.yaml")
    assert get_config_path() == Path.home() / "x.yaml"


class TestNamedConfigFileMustExist:
    """A path given with -c or CJA_CONFIG_PATH is never skipped for a lower source."""

    ENV = {
        "ORG_ID": "A1B2C3D4E5F6A7B8C9D0E1F2@AdobeOrg",
        "CLIENT_ID": "aaaa1111bbbb2222cccc3333dddd4444",
        "SECRET": "fake-secret-A-not-a-credential-0001",
        "SCOPES": "openid,AdobeID",
    }

    @pytest.fixture(autouse=True)
    def _a_full_credential_in_the_environment(self, monkeypatch) -> None:
        for name, value in self.ENV.items():
            monkeypatch.setenv(name, value)

    def test_a_missing_file_is_an_error_that_names_the_path(self, tmp_path) -> None:
        missing = tmp_path / "missing.yaml"
        with pytest.raises(ConfigError) as info:
            load_config(missing)
        assert str(info.value) == f"{missing}: does not exist (given with -c)"
        assert info.value.summary == "missing.yaml: does not exist (given with -c)"

    def test_a_dangling_symlink_is_an_error(self, tmp_path) -> None:
        link = tmp_path / "link.yaml"
        link.symlink_to(tmp_path / "gone.yaml")
        with pytest.raises(ConfigError, match="does not exist"):
            load_config(link)

    def test_a_folder_is_an_error(self, tmp_path) -> None:
        with pytest.raises(ConfigError, match="is a folder, not a file"):
            load_config(tmp_path)

    def test_a_missing_file_in_the_variable_is_an_error(self, tmp_path, monkeypatch) -> None:
        missing = tmp_path / "missing.yaml"
        monkeypatch.setenv("CJA_CONFIG_PATH", str(missing))
        with pytest.raises(ConfigError) as info:
            load_config()
        assert str(info.value) == f"{missing}: does not exist (given with CJA_CONFIG_PATH)"

    def test_a_file_in_the_variable_is_read(self, tmp_path, monkeypatch) -> None:
        path = tmp_path / "other.yaml"
        path.write_text("monitor_interval: 30\n")
        path.chmod(0o600)
        monkeypatch.setenv("CJA_CONFIG_PATH", str(path))
        assert load_config().monitor_interval == 30

    @pytest.mark.parametrize("command", [["cli", "list"], ["cli", "config"], ["tui"], []])
    def test_the_cli_and_the_tui_stop_with_one_line(self, tmp_path, command) -> None:
        from unittest.mock import patch

        from click.testing import CliRunner

        from cja_audit_log_monitor.cli import main

        missing = tmp_path / "missing.yaml"
        with patch("cja_audit_log_monitor.tui.CJAAuditApp") as make_app:
            result = CliRunner().invoke(main, ["-c", str(missing), *command])
        assert result.exit_code == 1
        make_app.assert_not_called()
        assert result.stdout == ""
        line = result.stderr.replace("\n", "")
        assert line == f"Configuration error: {missing}: does not exist (given with -c)"

    def test_init_still_creates_a_file_that_does_not_exist(self, tmp_path) -> None:
        from click.testing import CliRunner

        from cja_audit_log_monitor.cli import main

        path = tmp_path / "new.yaml"
        result = CliRunner().invoke(main, ["-c", str(path), "cli", "init"])
        assert result.exit_code == 0 and path.exists()


def test_missing_default_config_is_quiet(caplog) -> None:
    with caplog.at_level(logging.WARNING):
        load_config()
    assert "not found" not in caplog.text


def test_first_message_names_all_four_credentials(sample_settings) -> None:
    from cja_audit_log_monitor.auth import AuthenticationError, TokenManager

    with pytest.raises(AuthenticationError) as info:
        TokenManager(CJASettings(_env_file=None)).get_token()
    text = str(info.value)
    assert "ORG_ID" in text and "CLIENT_ID" in text and "SECRET" in text
    assert "SCOPES" in text
    assert ".env.example" not in text


class TestConfigEdges:
    def test_a_bad_dotenv_value_is_blamed_on_the_dotenv(self, tmp_path) -> None:
        """The file's good value loses to the .env's bad one, so the error names the .env."""
        (tmp_path / ".env").write_text("MONITOR_INTERVAL=0\n")
        path = tmp_path / "c.yaml"
        path.write_text("monitor_interval: 10\n")
        with pytest.raises(ConfigError) as info:
            load_config(path)
        assert str(info.value).startswith("environment or .env: monitor_interval:")

    def test_more_errors_are_counted(self, tmp_path) -> None:
        path = tmp_path / "c.yaml"
        path.write_text("monitor_interval: 0\ndefault_days: 0\n")
        with pytest.raises(ConfigError, match=r"\(\+1 more\)$"):
            load_config(path)

    def test_default_path_without_the_env_var(self, monkeypatch) -> None:
        from cja_audit_log_monitor.config import DEFAULT_CONFIG_FILE, get_config_path

        monkeypatch.delenv("CJA_CONFIG_PATH", raising=False)
        assert get_config_path() == DEFAULT_CONFIG_FILE

    def test_init_without_a_path_uses_the_env_var(self, tmp_path, monkeypatch) -> None:
        target = tmp_path / "from-env" / "config.yaml"
        monkeypatch.setenv("CJA_CONFIG_PATH", str(target))
        assert create_default_config() == target
        assert target.is_file()

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes")
    def test_init_in_a_read_only_folder_is_a_config_error(self, tmp_path) -> None:
        import os

        if os.geteuid() == 0:
            pytest.skip("root can write anywhere")
        folder = tmp_path / "locked"
        folder.mkdir()
        folder.chmod(0o500)
        try:
            with pytest.raises(ConfigError, match="cannot write"):
                create_default_config(folder / "config.yaml")
        finally:
            folder.chmod(0o700)


class TestUnusableDotEnv:
    """A .env that cannot be read as text is a configuration error, not an unexpected one."""

    def test_a_dotenv_that_is_not_utf8_is_a_config_error(self, tmp_path) -> None:
        from cja_audit_log_monitor.config import ConfigError, load_config

        (tmp_path / ".env").write_bytes(b"ORG_ID=x\xff\xfe@AdobeOrg\n")
        with pytest.raises(ConfigError, match=r"\.env is not UTF-8 text"):
            load_config()

    def test_an_unreadable_dotenv_is_a_config_error(self, tmp_path) -> None:
        import os

        from cja_audit_log_monitor.config import ConfigError, load_config

        env = tmp_path / ".env"
        env.write_text("ORG_ID=x@AdobeOrg\n")
        env.chmod(0)
        if os.access(env, os.R_OK):
            pytest.skip("running as a user who can read any file")
        try:
            with pytest.raises(ConfigError, match=r"\.env cannot be read"):
                load_config()
        finally:
            env.chmod(0o600)

    def test_the_cli_says_configuration_error(self, tmp_path) -> None:
        from click.testing import CliRunner

        from cja_audit_log_monitor.cli import main

        (tmp_path / ".env").write_bytes(b"ORG_ID=\xff\n")
        result = CliRunner().invoke(main, ["cli", "config"])
        assert result.exit_code == 1
        assert "Configuration error: .env is not UTF-8 text" in result.output
        assert "Unexpected error" not in result.output
