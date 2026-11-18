"""Tests for configuration module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
import yaml

from cja_audit_log_monitor.config import (
    CJASettings,
    ConfigError,
    create_default_config,
    load_config,
    save_config,
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


class TestSaveConfig:
    """Tests for save_config function."""

    def test_save_config(self) -> None:
        """Test saving config to YAML file."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            settings = CJASettings(default_page_size=75)

            save_config(settings, config_path)

            with open(config_path) as f:
                saved = yaml.safe_load(f)

            assert saved["default_page_size"] == 75

    def test_save_excludes_secrets(self) -> None:
        """Test that secrets are not saved to file."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "config.yaml"
            settings = CJASettings(
                client_id="secret_id",
                secret="super_secret",
            )

            save_config(settings, config_path)

            with open(config_path) as f:
                saved = yaml.safe_load(f)

            assert "client_id" not in saved
            assert "secret" not in saved

    def test_save_creates_directory(self) -> None:
        """Test save creates parent directory if needed."""
        with TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / "subdir" / "config.yaml"
            settings = CJASettings(default_page_size=25)

            save_config(settings, config_path)

            assert config_path.exists()


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
