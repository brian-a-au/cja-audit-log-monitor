"""Configuration handling for CJA Audit CLI."""

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import AlertRule

DEFAULT_CONFIG_DIR = Path.home() / ".cja-audit"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"


class CJASettings(BaseSettings):
    """Application settings with environment variable support."""

    model_config = SettingsConfigDict(
        env_prefix="CJA_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Authentication
    client_id: str = Field(default="", description="Adobe OAuth client ID")
    client_secret: str = Field(default="", description="Adobe OAuth client secret")
    org_id: str = Field(default="", description="Adobe IMS organization ID")
    scopes: str = Field(
        default="openid,AdobeID,read_organizations,additional_info.projectedProductContext",
        description="OAuth scopes (comma-separated)",
    )

    # JWT authentication (legacy)
    tech_account_id: str = Field(default="", description="Technical account ID for JWT")
    private_key_path: str = Field(default="", description="Path to private key for JWT")

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

    @property
    def scopes_list(self) -> list[str]:
        """Get scopes as a list."""
        return [s.strip() for s in self.scopes.split(",") if s.strip()]

    def is_oauth_configured(self) -> bool:
        """Check if OAuth credentials are configured."""
        return bool(self.client_id and self.client_secret and self.org_id)

    def is_jwt_configured(self) -> bool:
        """Check if JWT credentials are configured."""
        return bool(
            self.client_id
            and self.tech_account_id
            and self.private_key_path
            and Path(self.private_key_path).exists()
        )


def load_config(config_path: Path | None = None) -> CJASettings:
    """Load configuration from file and environment variables.

    Priority (highest to lowest):
    1. Environment variables
    2. Config file
    3. Default values
    """
    config_data: dict[str, Any] = {}

    # Determine config file path
    if config_path is None:
        config_path = DEFAULT_CONFIG_FILE

    # Load from YAML config file if it exists
    if config_path.exists():
        with open(config_path) as f:
            yaml_config = yaml.safe_load(f)
            if yaml_config:
                config_data.update(yaml_config)

    # Environment variables will override config file values via pydantic-settings
    return CJASettings(**config_data)


def save_config(settings: CJASettings, config_path: Path | None = None) -> None:
    """Save configuration to YAML file."""
    if config_path is None:
        config_path = DEFAULT_CONFIG_FILE

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
        config_path = DEFAULT_CONFIG_FILE

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
