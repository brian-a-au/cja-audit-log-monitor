"""Pydantic models and enums for CJA audit logs."""

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ActionType(str, Enum):
    """Audit log action types."""

    API_REQUEST = "API_REQUEST"
    APPROVE = "APPROVE"
    CREATE = "CREATE"
    DELETE = "DELETE"
    EDIT = "EDIT"
    EMBARGO = "EMBARGO"
    EXPORT = "EXPORT"
    ORG_CHANGE = "ORG_CHANGE"
    REFRESH = "REFRESH"
    SHARE = "SHARE"
    TRANSFER = "TRANSFER"
    UNAPPROVE = "UNAPPROVE"
    UNSHARE = "UNSHARE"


class ComponentType(str, Enum):
    """Audit log component types."""

    ANNOTATION = "ANNOTATION"
    AUDIENCE = "AUDIENCE"
    CALCULATED_METRIC = "CALCULATED_METRIC"
    CONNECTION = "CONNECTION"
    DATA_GROUP = "DATA_GROUP"
    DATA_VIEW = "DATA_VIEW"
    DATASET_STITCHING = "DATASET_STITCHING"
    DATE_RANGE = "DATE_RANGE"
    FEATURE_ACCESS = "FEATURE_ACCESS"
    FILTER = "FILTER"
    IMS_ORG = "IMS_ORG"
    MOBILE = "MOBILE"
    PROJECT = "PROJECT"
    REPORT = "REPORT"
    SCHEDULED_PROJECT = "SCHEDULED_PROJECT"
    USER = "USER"
    USER_GROUP = "USER_GROUP"


class AuditLogEntry(BaseModel):
    """Single audit log entry from the API."""

    id: str | None = None
    timestamp: datetime | None = Field(None, alias="dateCreated")
    user_id: str | None = Field(None, alias="userId")
    user_email: str | None = Field(None, alias="userEmail")
    action: str | None = None
    component_type: str | None = Field(None, alias="componentType")
    component_id: str | None = Field(None, alias="componentId")
    component_name: str | None = Field(None, alias="componentName")
    description: str | None = None
    org_id: str | None = Field(None, alias="orgId")
    ip_address: str | None = Field(None, alias="ipAddress")
    changes: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}


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
    last: bool = True
    number: int = 0
    size: int = 100

    model_config = {"populate_by_name": True}


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
        params: dict[str, Any] = {
            "page": self.page,
            "pageSize": self.page_size,
        }

        if self.start_date:
            params["startDate"] = self.start_date.strftime("%Y-%m-%dT%H:%M:%S%z")

        if self.end_date:
            params["endDate"] = self.end_date.strftime("%Y-%m-%dT%H:%M:%S%z")

        if self.actions:
            params["action"] = [a.value for a in self.actions]

        if self.components:
            params["component"] = [c.value for c in self.components]

        if self.user_id:
            params["userId"] = self.user_id

        if self.user_type:
            params["userType"] = self.user_type

        if self.component_id:
            params["componentId"] = self.component_id

        if self.description:
            params["description"] = self.description

        return params


class TokenInfo(BaseModel):
    """OAuth token information."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int
    expires_at: datetime | None = None


class AlertRule(BaseModel):
    """Configuration for an alert rule."""

    name: str
    description: str | None = None
    enabled: bool = True
    actions: list[ActionType] | None = None
    components: list[ComponentType] | None = None
    threshold_count: int = 1
    threshold_window_minutes: int = 60
    users: list[str] | None = None


class WebhookConfig(BaseModel):
    """Configuration for webhook notifications."""

    url: str
    enabled: bool = True
    method: str = "POST"
    headers: dict[str, str] | None = None
    timeout: int = 30
    include_entry_details: bool = True


class NotificationConfig(BaseModel):
    """Configuration for alert notifications."""

    webhooks: list[WebhookConfig] = Field(default_factory=list)
    slack_webhook_url: str | None = None
    notify_on_anomalies: bool = True
    notify_on_alerts: bool = True
