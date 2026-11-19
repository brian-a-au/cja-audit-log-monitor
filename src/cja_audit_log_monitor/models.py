"""Pydantic models and enums for CJA audit logs."""

import logging
import re
from datetime import UTC, datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator

logger = logging.getLogger(__name__)


class ActionType(str, Enum):
    """Audit log action types."""

    API_REQUEST = "API_REQUEST"
    APPROVE = "APPROVE"
    CREATE = "CREATE"
    DELETE = "DELETE"
    EDIT = "EDIT"
    EMBARGO = "EMBARGO"
    EXPORT = "EXPORT"
    FAVORITE = "FAVORITE"
    LABEL = "LABEL"
    ORG_CHANGE = "ORG_CHANGE"
    PIN = "PIN"
    REFRESH = "REFRESH"
    SHARE = "SHARE"
    TRANSFER = "TRANSFER"
    UNAPPROVE = "UNAPPROVE"
    UNFAVORITE = "UNFAVORITE"
    UNSHARE = "UNSHARE"


class ComponentType(str, Enum):
    """Audit log component types."""

    ANNOTATION = "ANNOTATION"
    AUDIENCE = "AUDIENCE"
    CALCULATED_METRIC = "CALCULATED_METRIC"
    CONNECTION = "CONNECTION"
    CONTAINER = "CONTAINER"
    DATA_GROUP = "DATA_GROUP"
    DATA_VIEW = "DATA_VIEW"
    DATASET_STITCHING = "DATASET_STITCHING"
    DATE_RANGE = "DATE_RANGE"
    FEATURE_ACCESS = "FEATURE_ACCESS"
    FILTER = "FILTER"
    FULL_TABLE_EXPORT = "FULL_TABLE_EXPORT"
    IMAGE = "IMAGE"
    IMS_ORG = "IMS_ORG"
    MOBILE = "MOBILE"
    PROJECT = "PROJECT"
    REPORT = "REPORT"
    SCHEDULED_PROJECT = "SCHEDULED_PROJECT"
    USER = "USER"
    USER_GROUP = "USER_GROUP"


# Suffixes of IMS user ids seen in live audit logs, e.g. "ABC@82462040631c0cd4495ca6.e".
_IMS_ID_SUFFIXES = (".e", "@techacct.adobe.com", "@AdobeID")


def is_ims_user_id(value: str) -> bool:
    """True when ``value`` is an IMS user id rather than an email address."""
    return "@" not in value or value.endswith(_IMS_ID_SUFFIXES)


# C0 controls except tab and line feed, DEL, the C1 controls (which include CSI), and lone
# surrogates, which no output encoding can write.
_CONTROL = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")


def printable(text: str) -> str:
    """Replace control characters and lone surrogates with U+FFFD, tabs with spaces.

    Line breaks are kept.

    Audit data comes from anyone who can name a component. An escape sequence in a name
    could set the terminal title, clear the screen or hide rows, so none reaches output.
    """
    return _CONTROL.sub("\ufffd", text.replace("\t", " "))


class AuditLogEntry(BaseModel):
    """Single audit log entry from the API."""

    id: str | None = None
    timestamp: datetime | None = Field(None, alias="dateCreated")
    user_id: str | None = Field(None, alias="userId")
    user_email: str | None = Field(None, alias="userEmail")
    user_name: str | None = Field(None, alias="userName")
    action: str | None = None
    component_type: str | None = Field(None, alias="componentType")
    component_id: str | None = Field(None, alias="componentId")
    component_name: str | None = Field(None, alias="componentName")
    description: str | None = None
    org_id: str | None = Field(None, alias="orgId")
    ip_address: str | None = Field(None, alias="ipAddress")
    changes: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}

    @field_validator(
        "id", "user_id", "user_email", "user_name", "action", "component_type",
        "component_id", "component_name", "description", "org_id", "ip_address",
    )
    @classmethod
    def _printable(cls, value: str | None) -> str | None:
        return printable(value) if isinstance(value, str) else value

    @field_validator("timestamp")
    @classmethod
    def _assume_utc(cls, value: datetime | None) -> datetime | None:
        """Read a timestamp with no timezone as UTC."""
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value

    @model_validator(mode="before")
    @classmethod
    def _flatten_live_api_shape(cls, data: Any) -> Any:
        """Map the live API's nested objects onto the flat fields.

        The CJA Audit Logs API returns ``user`` and ``component`` as objects
        and the org as ``imsOrgId``. Flat keys, when present, take priority.
        """
        if not isinstance(data, dict):
            return data
        data = dict(data)
        user = data.pop("user", None)
        if isinstance(user, dict):
            data.setdefault("userId", user.get("id"))
            data.setdefault("userEmail", user.get("email"))
            data.setdefault("userName", user.get("name"))
        component = data.pop("component", None)
        if isinstance(component, dict):
            data.setdefault("componentType", component.get("idType"))
            data.setdefault("componentId", component.get("id"))
            data.setdefault("componentName", component.get("name"))
        if "imsOrgId" in data:
            data.setdefault("orgId", data.pop("imsOrgId"))
        return data


class PaginationInfo(BaseModel):
    """Pagination information from API response."""

    page: int = 0
    page_size: int = Field(100, alias="pageSize")
    total_elements: int = Field(0, alias="totalElements")
    total_pages: int = Field(0, alias="totalPages")
    number_of_elements: int = Field(0, alias="numberOfElements")
    first: bool = True
    last: bool = True

    model_config = {"populate_by_name": True}


class AuditLogResponse(BaseModel):
    """API response containing audit logs with pagination."""

    content: list[AuditLogEntry] = Field(default_factory=list)
    page: PaginationInfo | None = None
    total_elements: int = Field(0, alias="totalElements")
    total_pages: int = Field(0, alias="totalPages")
    number_of_elements: int = Field(0, alias="numberOfElements")
    first: bool = True
    last: bool = False  # a missing flag must not end paging early
    number: int = 0
    size: int = 100

    model_config = {"populate_by_name": True}


# The API rejects a date filter unless both dates are sent. This stands in for a missing start.
API_EARLIEST = datetime(2000, 1, 1, tzinfo=UTC)

_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S%z"


class AuditLogQuery(BaseModel):
    """Query parameters for audit log requests."""

    start_date: datetime | None = None
    end_date: datetime | None = None
    actions: list[ActionType] | None = None
    components: list[ComponentType] | None = None
    user_id: str | None = None
    user_type: str | None = None
    component_id: str | None = None
    description: str | None = None
    page: int = 0
    page_size: int = 100

    def to_query_params(self) -> dict[str, Any]:
        """Convert to API query parameters."""
        # The live API pages with "pageNumber"; it silently ignores "page".
        params: dict[str, Any] = {
            "pageNumber": self.page,
            "pageSize": self.page_size,
        }

        # The API needs both dates whenever either is set, so fill in the missing one.
        if self.start_date or self.end_date:
            start = self.start_date or API_EARLIEST
            end = self.end_date or datetime.now(UTC)
            params["startDate"] = start.strftime(_DATE_FORMAT)
            params["endDate"] = end.strftime(_DATE_FORMAT)

        if self.actions:
            params["action"] = [a.value for a in self.actions]

        if self.components:
            params["component"] = [c.value for c in self.components]

        if self.user_id:
            # The API matches userId only against IMS ids; emails need userEmail.
            key = "userId" if is_ims_user_id(self.user_id) else "userEmail"
            params[key] = self.user_id

        if self.user_type:
            params["userType"] = self.user_type

        if self.component_id:
            params["componentId"] = self.component_id

        if self.description:
            params["description"] = self.description

        return params


class TokenInfo(BaseModel):
    """OAuth token information."""

    access_token: SecretStr
    token_type: str = "bearer"
    expires_in: int
    expires_at: datetime | None = None


def _normalize_rule_names(value: Any, enum_cls: type[Enum], label: str) -> Any:
    """Upper-case rule action/component names; warn about names the enum lacks.

    Unknown names are kept: the API can report values this tool does not list.
    """
    if value is None or not isinstance(value, (list, tuple)):
        return value
    known = {m.value for m in enum_cls}
    names: list[Any] = []
    for item in value:
        if isinstance(item, Enum):
            item = item.value
        if isinstance(item, str):
            item = item.strip().upper()
            if item not in known:
                logger.warning("Alert rule %s %r is not a known %s type", label, item, label)
        names.append(item)
    return names


class AlertRule(BaseModel):
    """Configuration for an alert rule."""

    name: str
    description: str | None = None
    enabled: bool = True
    actions: list[str] | None = None
    components: list[str] | None = None
    threshold_count: int = Field(1, ge=1)
    threshold_window_minutes: int = Field(60, ge=1, le=525_600)  # at most one year
    users: list[str] | None = None
    per_user: bool = False

    @field_validator("actions", mode="before")
    @classmethod
    def _normalize_actions(cls, value: Any) -> Any:
        return _normalize_rule_names(value, ActionType, "action")

    @field_validator("components", mode="before")
    @classmethod
    def _normalize_components(cls, value: Any) -> Any:
        return _normalize_rule_names(value, ComponentType, "component")

    @field_validator("users", mode="before")
    @classmethod
    def _strip_users(cls, value: Any) -> Any:
        if isinstance(value, (list, tuple)):
            return [item.strip() if isinstance(item, str) else item for item in value]
        return value

    @field_validator("actions", "components", "users")
    @classmethod
    def _not_empty(cls, value: list[str] | None) -> list[str] | None:
        """An empty list would match everything; leaving the key out says that plainly."""
        if value is not None and not value:
            raise ValueError("must not be empty; leave it out to match everything")
        return value


class WebhookConfig(BaseModel):
    """Configuration for webhook notifications."""

    url: str = Field(repr=False)
    enabled: bool = True
    method: str = "POST"
    headers: dict[str, str] | None = Field(default=None, repr=False)
    timeout: int = Field(30, gt=0, le=300)  # seconds
    include_entry_details: bool = True


class NotificationConfig(BaseModel):
    """Configuration for alert notifications."""

    webhooks: list[WebhookConfig] = Field(default_factory=list)
    slack_webhook_url: str | None = Field(default=None, repr=False)
    notify_on_anomalies: bool = False
    notify_on_alerts: bool = True

    @property
    def enabled_webhook_count(self) -> int:
        """Return the number of enabled webhook channels."""
        return sum(webhook.enabled for webhook in self.webhooks)

    @property
    def has_active_channels(self) -> bool:
        """Return whether Slack or an enabled webhook is configured."""
        return bool(self.slack_webhook_url) or self.enabled_webhook_count > 0
