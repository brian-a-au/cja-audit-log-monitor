"""Configuration handling for CJA Audit Log Monitor."""

import logging
import os
import re
import stat
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import yaml
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator
from pydantic.fields import FieldInfo
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
)

try:
    from pydantic_settings import SettingsError
except ImportError:  # pragma: no cover - pydantic-settings 2.0 has it in the sources module
    from pydantic_settings.sources import SettingsError  # type: ignore[no-redef,attr-defined]

from .models import AlertRule, NotificationConfig, WebhookConfig

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path.home() / ".cja-audit-log-monitor"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.yaml"

# Upper limits, so a typo cannot overflow a date or a timer.
MAX_MONITOR_INTERVAL = 86_400  # one day, in seconds
MAX_DAYS = 3_650  # about ten years

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

    def get_field_value(  # pragma: no cover - base class needs it; pydantic calls __call__
        self, field: FieldInfo, field_name: str
    ) -> tuple[Any, str, bool]:
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
    default_page_size: int = Field(
        default=100, ge=1, le=1000, description="Default page size for queries (1 to 1000)"
    )
    default_days: int = Field(
        default=7, ge=1, le=MAX_DAYS, description="Default number of days for date range"
    )

    # Monitoring settings
    monitor_interval: int = Field(
        default=60,
        ge=5,
        le=MAX_MONITOR_INTERVAL,
        description="Polling interval in seconds (5 to 86,400)",
    )

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

    @field_validator("alert_rules")
    @classmethod
    def unique_rule_names(cls, rules: list[AlertRule]) -> list[AlertRule]:
        """Two rules with one name would share one event count."""
        seen: set[str] = set()
        for rule in rules:
            if rule.name in seen:
                raise ValueError(f"alert rule name {rule.name!r} is used twice")
            seen.add(rule.name)
        return rules

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
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("must not hold a user name or password")
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
    explicit = config_path is not None
    if config_path is None:
        config_path = get_config_path()

    # Load from YAML config file if it exists
    if use_file and config_path.exists():
        config_data.update(_read_config_file(config_path))
    elif use_file and explicit and not config_path.is_symlink():
        logger.warning("config file %s not found; using environment only", config_path)

    token = _config_file_data.set(config_data)
    try:
        return CJASettings()
    except ValidationError as e:
        field = str(e.errors()[0]["loc"][0]) if e.errors()[0]["loc"] else ""
        if use_file and field in config_data and not _set_outside_file(field):
            source, short = str(config_path), config_path.name
        else:
            source = short = "environment or .env"
        raise ConfigError(_validation_summary(source, e), _validation_summary(short, e)) from None
    except SettingsError as e:
        # A JSON-valued env var or .env line (e.g. NOTIFICATIONS) that does not parse.
        # The message never holds the value; keep only the field name.
        field = _settings_error_field(e)
        text = f"environment or .env: {field}: not valid JSON"
        raise ConfigError(text, text) from None
    except UnicodeDecodeError:
        # Only the .env file is read as text here; the YAML file was read above.
        text = ".env is not UTF-8 text"
        raise ConfigError(text, text) from None
    except OSError as e:
        text = f".env cannot be read ({e.strerror or type(e).__name__})"
        raise ConfigError(text, text) from None
    finally:
        _config_file_data.reset(token)


def _set_outside_file(field: str) -> bool:
    """Whether an env var or the .env file sets ``field`` (they win over the config file)."""
    if any(name.lower() == field for name in os.environ):
        return True
    env_file = Path(".env")
    if not env_file.is_file():
        return False
    try:
        from dotenv import dotenv_values

        return any(str(name).lower() == field for name in dotenv_values(env_file))
    except Exception:  # pragma: no cover - CJASettings() already failed on an unreadable .env
        return False


def _settings_error_field(error: Exception) -> str:
    """The field name from pydantic-settings' 'error parsing value for field "x"' text."""
    match = re.search(r'field "([^"]+)"', str(error))
    return match.group(1) if match else "a setting"


def _read_config_file(config_path: Path) -> dict[str, Any]:
    """Parse the YAML config file. Every failure is a ConfigError that never shows content.

    Each error is raised ``from None``: a chained exception would carry the parsed data
    (and the secret) into a traceback.
    """

    def fail(problem: str) -> ConfigError:
        return ConfigError(f"{config_path}: {problem}", f"{config_path.name}: {problem}")

    try:
        _warn_if_not_private(config_path)
        with open(config_path, encoding="utf-8") as f:
            yaml_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        detail = (str(e).strip().splitlines() or ["unknown error"])[0]
        raise fail(f"not valid YAML ({detail})") from None
    except UnicodeDecodeError:
        raise fail("not valid UTF-8 text") from None
    except IsADirectoryError:
        raise fail("is a folder, not a file") from None
    except PermissionError:
        raise fail("cannot be read (permission denied)") from None
    except OSError as e:
        raise fail(f"cannot be read ({e.strerror or type(e).__name__})") from None
    except RecursionError:
        raise fail("nested too deeply") from None
    if yaml_config is None:
        return {}
    if not isinstance(yaml_config, dict):
        raise fail("expected a mapping of settings at the top level")
    bad_keys = [key for key in yaml_config if not isinstance(key, str)]
    if bad_keys:
        raise fail(f"setting names must be text (found {type(bad_keys[0]).__name__})")
    for key in yaml_config:
        if key not in CJASettings.model_fields:
            logger.warning("%s: ignoring unknown setting %r", config_path, key)
    _warn_nested_unknown_keys(yaml_config, config_path)
    return yaml_config


def _warn_unknown_keys(data: Any, model: type[BaseModel], where: str, path: Path) -> None:
    """Warn about keys of ``data`` that ``model`` does not have. Non-dicts are left to pydantic."""
    if not isinstance(data, dict):
        return
    for key in data:
        if key not in model.model_fields:
            logger.warning("%s: %s: ignoring unknown setting %r", path, where, key)


def _warn_nested_unknown_keys(config: dict[str, Any], path: Path) -> None:
    """Warn about typos inside rules, the notifications block and each webhook."""
    rules = config.get("alert_rules")
    if isinstance(rules, list):
        for index, rule in enumerate(rules):
            _warn_unknown_keys(rule, AlertRule, f"alert_rules[{index}]", path)
    notifications = config.get("notifications")
    _warn_unknown_keys(notifications, NotificationConfig, "notifications", path)
    if isinstance(notifications, dict) and isinstance(notifications.get("webhooks"), list):
        for index, webhook in enumerate(notifications["webhooks"]):
            _warn_unknown_keys(webhook, WebhookConfig, f"notifications.webhooks[{index}]", path)


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
    """Create a default configuration file.

    Only a folder that this call creates is made private (0700); an existing folder keeps
    its mode. A symlink at ``config_path`` is refused, never followed.
    """
    if config_path is None:
        config_path = get_config_path()

    created_folder = not config_path.parent.exists()
    config_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    if created_folder:
        config_path.parent.chmod(0o700)  # mkdir's mode is masked by the umask

    if config_path.is_symlink():
        raise ConfigError(f"{config_path} is a symlink; give the path of a real file")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0)
    try:
        fd = os.open(config_path, flags, 0o600)
    except OSError as e:
        raise ConfigError(f"{config_path}: cannot write ({e.strerror})") from None
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(_TEMPLATE_HEAD + _alert_rules_template() + "\n" + _TEMPLATE_NOTIFICATIONS)
    config_path.chmod(0o600)  # os.open's mode is ignored when the file already exists
    return config_path


def _alert_rules_template() -> str:
    """The built-in rules as a commented YAML block, so uncommenting keeps all of them."""
    from .alerts import DEFAULT_ALERT_RULES

    rules = [
        rule.model_dump(mode="json", exclude_none=True, exclude={"enabled"})
        for rule in DEFAULT_ALERT_RULES
    ]
    block = yaml.safe_dump({"alert_rules": rules}, sort_keys=False, indent=2)
    lines = [
        "# Alert rules. These are the built-in rules. If you define any rules here, they",
        "# replace the built-in rules, so keep the ones you want. To use the block, remove",
        "# the '# ' marks from the alert_rules lines.",
        "# Fields: name (required), description, enabled (default true), actions, components,",
        "# users, threshold_count (default 1), threshold_window_minutes (default 60),",
        "# per_user (default false). Action and component names are not case sensitive.",
        "# Off-hours activity (midnight to 5am) is an anomaly check, not a rule.",
    ]
    for line in block.splitlines():
        # safe_dump puts list items at the key's indent; nest them under alert_rules:.
        lines.append("# " + (line if line.startswith("alert_rules") else "  " + line))
    lines += [
        "#",
        "# An example of an extra rule. To use it, add it under alert_rules: above.",
        "#   - name: named_account_deletes",
        "#     actions:",
        "#     - DELETE",
        "#     users:   # user id, email, or display name",
        "#     - someone@example.com",
    ]
    return "\n".join(lines) + "\n"


_TEMPLATE_HEAD = """\
# CJA Audit Log Monitor Configuration
# See .env.example for authentication credentials

# API settings
api_base_url: https://cja.adobe.io
ims_base_url: https://ims-na1.adobelogin.com

# CLI defaults
default_page_size: 100
default_days: 7

# Monitoring settings
monitor_interval: 60

# OAuth scopes
scopes: openid,AdobeID,read_organizations,additional_info.projectedProductContext

"""

_TEMPLATE_NOTIFICATIONS = """\
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


def get_config_path() -> Path:
    """Get the default config file path."""
    # Check environment variable first
    env_path = os.getenv("CJA_CONFIG_PATH")
    if env_path:
        return Path(env_path).expanduser()
    return DEFAULT_CONFIG_FILE
