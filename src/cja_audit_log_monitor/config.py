"""Configuration handling for CJA Audit CLI."""

import logging
import os
import stat
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .models import AlertRule, NotificationConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".cja-audit-log-monitor"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"

# Parsed YAML for the load_config call in progress; read by ConfigFileSource.
_config_file_data: ContextVar[dict[str, Any]] = ContextVar("_config_file_data", default={})


class ConfigError(Exception):
    """The config file could not be read or holds invalid settings.

    ``str(error)`` is the full message; ``summary`` is a one-line version for
    tight spaces such as the TUI header.
    """

    def __init__(self, message: str, summary: str | None = None) -> None:
        super().__init__(message)
        first_line = (message.strip().splitlines() or [""])[0]
        self.summary = summary or first_line


def _validation_summary(source: str, error: ValidationError) -> str:
    """One line naming the first invalid field and why (never the input value)."""
    errors = error.errors()
    first = errors[0]
    location = ".".join(str(part) for part in first["loc"])
    text = f"{source}: {location}: {first['msg']}" if location else f"{source}: {first['msg']}"
    if len(errors) > 1:
        text += f" (+{len(errors) - 1} more)"
    return text


class ConfigFileSource(PydanticBaseSettingsSource):
    """Settings source that serves the YAML data staged by load_config."""

    def get_field_value(self, field: FieldInfo, field_name: str) -> tuple[Any, str, bool]:
        return _config_file_data.get().get(field_name), field_name, False

    def __call__(self) -> dict[str, Any]:
        return dict(_config_file_data.get())


class CJASettings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        hide_input_in_errors=True,
    )

    # Authentication (matches Adobe API skill: org_id, client_id, secret, scopes)
    org_id: str = Field(default="", description="Adobe IMS organization ID (ORG_ID)")
    client_id: str = Field(default="", description="Adobe OAuth client ID (CLIENT_ID)")
    secret: SecretStr = Field(
        default=SecretStr(""), description="Adobe OAuth client secret (SECRET)"
    )
    scopes: str = Field(
        default="openid,AdobeID,read_organizations,additional_info.projectedProductContext",
        description="OAuth scopes (SCOPES, comma-separated)",
    )

    # API settings
    api_base_url: str = Field(
        default="https://cja.adobe.io",
        description="CJA API base URL",
    )
    ims_base_url: str = Field(
        default="https://ims-na1.adobelogin.com",
        description="Adobe IMS base URL",
    )

    # CLI defaults
    default_page_size: int = Field(default=100, description="Default page size for queries")
    default_days: int = Field(default=7, description="Default number of days for date range")
    output_format: str = Field(default="table", description="Default output format")

    # Monitoring settings
    monitor_interval: int = Field(default=60, description="Polling interval in seconds")

    # Alert settings
    alert_rules: list[AlertRule] = Field(default_factory=list)

    # Notification settings
    notifications: NotificationConfig = Field(default_factory=NotificationConfig)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Priority: init kwargs > env vars > .env > config file > defaults."""
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            ConfigFileSource(settings_cls),
            file_secret_settings,
        )

    @field_validator("org_id")
    @classmethod
    def validate_org_id(cls, v: str) -> str:
        """Validate org_id format ends with @AdobeOrg."""
        if v and not v.endswith("@AdobeOrg"):
            raise ValueError("ORG_ID must end with @AdobeOrg")
        return v

    @field_validator("api_base_url", "ims_base_url")
    @classmethod
    def validate_endpoint_url(cls, v: str) -> str:
        """Require https, allowing plain http only for localhost (tests, local mocks)."""
        parsed = urlparse(v)
        if parsed.scheme == "https" and parsed.hostname:
            return v
        if parsed.scheme == "http" and parsed.hostname in ("localhost", "127.0.0.1"):
            return v
        raise ValueError("must be an https:// URL (http:// is allowed only for localhost)")

    @property
    def scopes_list(self) -> list[str]:
        """Get scopes as a list."""
        return [s.strip() for s in self.scopes.split(",") if s.strip()]

    def is_oauth_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.secret.get_secret_value() and self.org_id)


def load_config(config_path: Path | None = None, *, use_file: bool = True) -> CJASettings:
    """Load configuration from the config file, .env and environment variables.

    Priority (highest to lowest):
    1. Environment variables
    2. .env file
    3. Config file
    4. Default values

    With ``use_file=False`` the config file is not read at all.
    """
    config_data: dict[str, Any] = {}

    # Determine config file path
    if config_path is None:
        config_path = get_config_path()

    # Load from YAML config file if it exists
    if use_file and config_path.exists():
        _warn_if_not_private(config_path)
        with open(config_path) as f:
            try:
                yaml_config = yaml.safe_load(f)
            except yaml.YAMLError as e:
                detail = (str(e).strip().splitlines() or ["unknown error"])[0]
                raise ConfigError(
                    f"{config_path}: not valid YAML ({detail})",
                    f"{config_path.name}: not valid YAML ({detail})",
                ) from e
        if yaml_config is not None and not isinstance(yaml_config, dict):
            raise ConfigError(
                f"{config_path}: expected a mapping of settings at the top level",
                f"{config_path.name}: expected a mapping of settings at the top level",
            )
        if yaml_config:
            config_data.update(yaml_config)
            for key in config_data:
                if key not in CJASettings.model_fields:
                    logger.warning("%s: ignoring unknown setting %r", config_path, key)

    token = _config_file_data.set(config_data)
    try:
        return CJASettings()
    except ValidationError as e:
        source = str(config_path) if use_file else "environment"
        short = config_path.name if use_file else "environment"
        raise ConfigError(f"{source}: {e}", _validation_summary(short, e)) from e
    finally:
        _config_file_data.reset(token)


def _warn_if_not_private(config_path: Path) -> None:
    """Warn when the config file is readable by group or others (POSIX only)."""
    if sys.platform == "win32":
        return
    mode = stat.S_IMODE(config_path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        logger.warning(
            "%s is readable by other users (mode %o); run: chmod 600 %s",
            config_path,
            mode,
            config_path,
        )


def create_default_config(config_path: Path | None = None) -> Path:
    """Create a default configuration file."""
    if config_path is None:
        config_path = get_config_path()

    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    config_path.parent.chmod(0o700)

    default_config = """# CJA Audit Log Monitor Configuration
# See .env.example for authentication credentials

# API settings
api_base_url: https://cja.adobe.io
ims_base_url: https://ims-na1.adobelogin.com

# CLI defaults
default_page_size: 100
default_days: 7
output_format: table

# Monitoring settings
monitor_interval: 60

# OAuth scopes
scopes: openid,AdobeID,read_organizations,additional_info.projectedProductContext

# Alert rules (example)
# alert_rules:
#   - name: bulk_delete
#     description: Alert on multiple delete operations
#     enabled: true
#     actions:
#       - DELETE
#     threshold_count: 5
#     threshold_window_minutes: 60
#     per_user: true   # count each user's events separately
#   - name: sensitive_export
#     description: Alert on data exports
#     enabled: true
#     actions:
#       - EXPORT
#     threshold_count: 1
#     threshold_window_minutes: 1440

# Notification channels (uncomment to enable delivery to Slack and/or webhooks)
# notifications:
#   slack_webhook_url: https://hooks.slack.com/services/XXX/YYY/ZZZ
#   notify_on_alerts: true
#   notify_on_anomalies: true   # opt-in; fires from `cja-audit-log-monitor cli anomalies`
#   webhooks:
#     - url: https://example.com/webhook
#       enabled: true
#       method: POST
#       headers:
#         Authorization: Bearer your-token
#       timeout: 30
#       include_entry_details: true
"""

    fd = os.open(config_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(default_config)
    config_path.chmod(0o600)  # os.open's mode is ignored when the file already exists

    return config_path


def get_config_path() -> Path:
    """Get the default config file path."""
    # Check environment variable first
    env_path = os.getenv("CJA_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_FILE
