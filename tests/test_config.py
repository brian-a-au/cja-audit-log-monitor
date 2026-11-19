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
        )
        assert settings.is_oauth_configured()

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
        """Test loading with non-existent config file uses defaults."""
        settings = load_config(Path("/nonexistent/config.yaml"))
        assert settings.default_page_size == 100  # Default value

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

    def test_use_file_false_ignores_the_file(self, tmp_path: Path) -> None:
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: [1, \n")
        assert load_config(path, use_file=False).monitor_interval == 60

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
        path.write_text("client_id: from_yaml\nmonitor_interval: 10\n")
        monkeypatch.setenv("CLIENT_ID", "from_env")
        settings = load_config(path)
        assert settings.client_id == "from_env"
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
        path.write_text(
            "alert_rules:\n  - name: r\n    actions: [DELETE, ARCHIVE]\n"
        )
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
        ("notifications:\n  slack_webhook: https://x.example.com\n", "notifications",
         "slack_webhook"),
        ("notifications:\n  webhooks:\n    - url: https://x.example.com\n      time_out: 5\n",
         "notifications.webhooks[0]", "time_out"),
    ],
    ids=["rule-typo", "rule-dash", "slack-typo", "webhook-typo"],
)
def test_nested_typo_warns(tmp_path, caplog, yaml_text, where, key) -> None:
    path = tmp_path / "config.yaml"
    path.write_text(yaml_text)
    path.chmod(0o600)
    with caplog.at_level(logging.WARNING):
        load_config(path)
    expected = f"{path}: {where}: ignoring unknown setting {key!r}"
    assert expected in caplog.text
