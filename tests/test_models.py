"""Tests for Pydantic models."""

from datetime import UTC, datetime

from cja_audit_log_monitor.models import (
    ActionType,
    AuditLogEntry,
    AuditLogQuery,
    AuditLogResponse,
    ComponentType,
)


class TestActionType:
    """Tests for ActionType enum."""

    def test_all_actions_defined(self) -> None:
        """Verify all expected actions are defined."""
        expected = [
            "API_REQUEST",
            "APPROVE",
            "CREATE",
            "DELETE",
            "EDIT",
            "EMBARGO",
            "EXPORT",
            "ORG_CHANGE",
            "REFRESH",
            "SHARE",
            "TRANSFER",
            "UNAPPROVE",
            "UNSHARE",
        ]
        actual = [a.value for a in ActionType]
        assert set(expected) == set(actual)

    def test_action_from_string(self) -> None:
        """Test creating ActionType from string."""
        assert ActionType("CREATE") == ActionType.CREATE
        assert ActionType("DELETE") == ActionType.DELETE


class TestComponentType:
    """Tests for ComponentType enum."""

    def test_all_components_defined(self) -> None:
        """Verify all expected components are defined."""
        expected = [
            "ANNOTATION",
            "AUDIENCE",
            "CALCULATED_METRIC",
            "CONNECTION",
            "DATA_GROUP",
            "DATA_VIEW",
            "DATASET_STITCHING",
            "DATE_RANGE",
            "FEATURE_ACCESS",
            "FILTER",
            "IMS_ORG",
            "MOBILE",
            "PROJECT",
            "REPORT",
            "SCHEDULED_PROJECT",
            "USER",
            "USER_GROUP",
        ]
        actual = [c.value for c in ComponentType]
        assert set(expected) == set(actual)


class TestAuditLogEntry:
    """Tests for AuditLogEntry model."""

    def test_create_entry(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test creating an audit log entry."""
        assert sample_audit_entry.id == "entry-123"
        assert sample_audit_entry.user_email == "user@example.com"
        assert sample_audit_entry.action == "CREATE"

    def test_create_from_api_response(self) -> None:
        """Test creating entry from API response with aliases."""
        data = {
            "id": "test-id",
            "dateCreated": "2024-01-15T10:30:00Z",
            "userId": "user-1",
            "userEmail": "test@example.com",
            "action": "EDIT",
            "componentType": "FILTER",
            "componentId": "filter-1",
            "componentName": "My Filter",
        }
        entry = AuditLogEntry.model_validate(data)

        assert entry.id == "test-id"
        assert entry.user_id == "user-1"
        assert entry.user_email == "test@example.com"
        assert entry.component_type == "FILTER"

    def test_optional_fields(self) -> None:
        """Test that all fields are optional."""
        entry = AuditLogEntry()
        assert entry.id is None
        assert entry.timestamp is None
        assert entry.action is None


class TestAuditLogQuery:
    """Tests for AuditLogQuery model."""

    def test_default_query(self) -> None:
        """Test default query parameters."""
        query = AuditLogQuery()
        assert query.page == 0
        assert query.page_size == 100
        assert query.actions is None

    def test_to_query_params(self) -> None:
        """Test converting query to API parameters."""
        query = AuditLogQuery(
            actions=[ActionType.CREATE, ActionType.DELETE],
            page_size=50,
        )
        params = query.to_query_params()

        assert params["pageSize"] == 50
        assert params["action"] == ["CREATE", "DELETE"]
        assert params["page"] == 0

    def test_to_query_params_with_dates(self) -> None:
        """Test query params with date range."""
        start = datetime(2024, 1, 1, tzinfo=UTC)
        end = datetime(2024, 1, 31, tzinfo=UTC)

        query = AuditLogQuery(start_date=start, end_date=end)
        params = query.to_query_params()

        assert "startDate" in params
        assert "endDate" in params


class TestAuditLogResponse:
    """Tests for AuditLogResponse model."""

    def test_parse_response(self, sample_api_response: dict) -> None:
        """Test parsing API response."""
        response = AuditLogResponse.model_validate(sample_api_response)

        assert response.total_elements == 1
        assert len(response.content) == 1
        assert response.first is True
        assert response.last is True

    def test_empty_response(self) -> None:
        """Test empty response."""
        response = AuditLogResponse()
        assert response.content == []
        assert response.total_elements == 0
