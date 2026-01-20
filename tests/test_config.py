"""Tests for configuration module."""

from pathlib import Path
from tempfile import TemporaryDirectory

import yaml

from cja_audit.config import (
    CJASettings,
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
        settings = CJASettings()
        assert not settings.is_oauth_configured()

    def test_is_oauth_configured_true(self) -> None:
        """Test OAuth configuration check returns True when configured."""
        settings = CJASettings(
            client_id="id",
            client_secret="secret",
            org_id="org",
        )
        assert settings.is_oauth_configured()

    def test_is_oauth_configured_partial(self) -> None:
        """Test OAuth configuration check returns False when partially configured."""
        settings = CJASettings(
            client_id="id",
            client_secret="",  # Missing
            org_id="org",
        )
        assert not settings.is_oauth_configured()

    def test_is_jwt_configured_false(self) -> None:
        """Test JWT configuration check returns False when not configured."""
        settings = CJASettings()
        assert not settings.is_jwt_configured()


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
                client_secret="super_secret",
            )

            save_config(settings, config_path)

            with open(config_path) as f:
                saved = yaml.safe_load(f)

            assert "client_id" not in saved
            assert "client_secret" not in saved

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
