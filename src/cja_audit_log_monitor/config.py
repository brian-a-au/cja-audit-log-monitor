"""Configuration handling for CJA Audit CLI."""

import os
from contextvars import ContextVar
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

from .models import AlertRule, NotificationConfig

DEFAULT_CONFIG_DIR = Path.home() / ".cja-audit-log-monitor"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"

# Parsed YAML for the load_config call in progress; read by ConfigFileSource.
_config_file_data: ContextVar[dict[str, Any]] = ContextVar("_config_file_data", default={})


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
    )

    # Authentication (matches Adobe API skill: org_id, client_id, secret, scopes)
    org_id: str = Field(default="", description="Adobe IMS organization ID (ORG_ID)")
    client_id: str = Field(default="", description="Adobe OAuth client ID (CLIENT_ID)")
    secret: str = Field(default="", description="Adobe OAuth client secret (SECRET)")
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

    @property
    def scopes_list(self) -> list[str]:
        """Get scopes as a list."""
        return [s.strip() for s in self.scopes.split(",") if s.strip()]

    def is_oauth_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.secret and self.org_id)


def load_config(config_path: Path | None = None) -> CJASettings:
    """Load configuration from the config file, .env and environment variables.

    Priority (highest to lowest):
    1. Environment variables
    2. .env file
    3. Config file
    4. Default values
    """
    config_data: dict[str, Any] = {}

    # Determine config file path
    if config_path is None:
        config_path = get_config_path()

    # Load from YAML config file if it exists
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config:
                config_data.update(yaml_config)

    token = _config_file_data.set(config_data)
    try:
        return CJASettings()
    finally:
        _config_file_data.reset(token)


def save_config(settings: CJASettings, config_path: Path | None = None) -> None:
    """Save configuration to YAML file."""
    if config_path is None:
        config_path = get_config_path()

    # Ensure directory exists
    config_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert to dict, excluding sensitive data from file (use env vars for those)
    config_dict = {
        "api_base_url": settings.api_base_url,
        "ims_base_url": settings.ims_base_url,
        "default_page_size": settings.default_page_size,
        "default_days": settings.default_days,
        "output_format": settings.output_format,
        "monitor_interval": settings.monitor_interval,
        "scopes": settings.scopes,
    }

    # Include alert rules if configured
    if settings.alert_rules:
        config_dict["alert_rules"] = [rule.model_dump() for rule in settings.alert_rules]

    with open(config_path, "w") as f:
        yaml.safe_dump(config_dict, f, default_flow_style=False)


def create_default_config(config_path: Path | None = None) -> Path:
    """Create a default configuration file."""
    if config_path is None:
        config_path = get_config_path()

    config_path.parent.mkdir(parents=True, exist_ok=True)

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

    with open(config_path, "w") as f:
        f.write(default_config)

    return config_path


def get_config_path() -> Path:
    """Get the default config file path."""
    # Check environment variable first
    env_path = os.getenv("CJA_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return DEFAULT_CONFIG_FILE
