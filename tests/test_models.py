"""Tests for Pydantic models."""

from datetime import UTC, datetime, timedelta

import pytest

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
            "FAVORITE",
            "LABEL",
            "ORG_CHANGE",
            "PIN",
            "REFRESH",
            "SHARE",
            "TRANSFER",
            "UNAPPROVE",
            "UNFAVORITE",
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
            "CONTAINER",
            "DATA_GROUP",
            "DATA_VIEW",
            "DATASET_STITCHING",
            "DATE_RANGE",
            "FEATURE_ACCESS",
            "FILTER",
            "FULL_TABLE_EXPORT",
            "IMAGE",
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
        assert params["pageNumber"] == 0
        assert "page" not in params

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


# Shape of an entry as the live CJA Audit Logs API returns it (values made up).
LIVE_API_ENTRY = {
    "id": "6afce25938051732907b1022",
    "dateCreated": "2026-11-17T23:25:13.000+00:00",
    "action": "EDIT",
    "description": "Updated data view",
    "imsOrgId": "ABC123@AdobeOrg",
    "user": {
        "id": "ABCDEF1234@AdobeID",
        "idType": "IMS",
        "name": "Pat Example",
        "email": "pat@example.com",
    },
    "component": {
        "id": "dv_123",
        "idType": "DATA_VIEW",
        "name": "Production View",
    },
}


class TestLiveApiShape:
    """The live API nests user and component objects; the model must read them."""

    def test_reads_nested_user(self):
        entry = AuditLogEntry.model_validate(LIVE_API_ENTRY)
        assert entry.user_id == "ABCDEF1234@AdobeID"
        assert entry.user_email == "pat@example.com"
        assert entry.user_name == "Pat Example"

    def test_reads_nested_component(self):
        entry = AuditLogEntry.model_validate(LIVE_API_ENTRY)
        assert entry.component_type == "DATA_VIEW"
        assert entry.component_id == "dv_123"
        assert entry.component_name == "Production View"

    def test_reads_ims_org_id(self):
        entry = AuditLogEntry.model_validate(LIVE_API_ENTRY)
        assert entry.org_id == "ABC123@AdobeOrg"

    def test_response_parses_live_entries(self):
        response = AuditLogResponse.model_validate(
            {"content": [LIVE_API_ENTRY], "totalElements": 1, "totalPages": 1}
        )
        assert response.content[0].user_email == "pat@example.com"
        assert response.content[0].component_type == "DATA_VIEW"

    def test_missing_nested_objects_leave_fields_empty(self):
        entry = AuditLogEntry.model_validate({"id": "x", "action": "EDIT"})
        assert entry.user_email is None
        assert entry.component_type is None

    def test_null_nested_objects_are_ignored(self):
        entry = AuditLogEntry.model_validate({"id": "x", "user": None, "component": None})
        assert entry.user_id is None
        assert entry.component_id is None

    def test_flat_fields_still_work(self):
        entry = AuditLogEntry.model_validate(
            {"id": "x", "userEmail": "a@example.com", "componentType": "PROJECT"}
        )
        assert entry.user_email == "a@example.com"
        assert entry.component_type == "PROJECT"


class TestQueryParamsMatchLiveApi:
    """Parameter names the live API honors (checked against a real org)."""

    def test_page_is_sent_as_page_number(self):
        params = AuditLogQuery(page=3, page_size=10).to_query_params()
        assert params["pageNumber"] == 3
        assert "page" not in params

    def test_email_is_sent_as_user_email(self):
        params = AuditLogQuery(user_id="pat@example.com").to_query_params()
        assert params["userEmail"] == "pat@example.com"
        assert "userId" not in params

    def test_ims_ids_are_sent_as_user_id(self):
        for value in (
            "ABC123@82462040631c0cd4495ca6.e",
            "ABC123@techacct.adobe.com",
            "ABC123@AdobeID",
            "ABC123",
        ):
            params = AuditLogQuery(user_id=value).to_query_params()
            assert params["userId"] == value, value
            assert "userEmail" not in params


class TestDateFilterSendsBothDates:
    """The live API rejects a date filter unless startDate and endDate are both sent."""

    def test_start_only_adds_end_date_of_now(self):
        start = datetime(2024, 1, 1, tzinfo=UTC)
        params = AuditLogQuery(start_date=start).to_query_params()
        assert params["startDate"] == "2024-01-01T00:00:00+0000"
        end = datetime.strptime(params["endDate"], "%Y-%m-%dT%H:%M:%S%z")
        assert abs((datetime.now(UTC) - end).total_seconds()) < 5

    def test_end_only_adds_earliest_start_date(self):
        end = datetime(2024, 1, 31, tzinfo=UTC)
        params = AuditLogQuery(end_date=end).to_query_params()
        assert params["startDate"] == "2000-01-01T00:00:00+0000"
        assert params["endDate"] == "2024-01-31T00:00:00+0000"

    def test_no_dates_sends_neither(self):
        params = AuditLogQuery().to_query_params()
        assert "startDate" not in params
        assert "endDate" not in params

    def test_model_fields_stay_none(self):
        query = AuditLogQuery(start_date=datetime(2024, 1, 1, tzinfo=UTC))
        query.to_query_params()
        assert query.end_date is None


class TestValuesSeenInLiveOrgs:
    """Component types and actions seen in a live org's audit logs."""

    @pytest.mark.parametrize("value", ["IMAGE", "CONTAINER", "FULL_TABLE_EXPORT"])
    def test_component_types(self, value):
        assert ComponentType(value).value == value

    @pytest.mark.parametrize("value", ["FAVORITE", "UNFAVORITE", "PIN", "LABEL"])
    def test_actions(self, value):
        assert ActionType(value).value == value


class TestTimestampTimezone:
    """Naive timestamps are read as UTC."""

    def test_naive_timestamp_gets_utc(self) -> None:
        entry = AuditLogEntry.model_validate({"id": "a", "timestamp": "2026-11-18T10:00:00"})
        assert entry.timestamp is not None
        assert entry.timestamp.tzinfo == UTC

    def test_aware_timestamp_is_kept(self) -> None:
        raw = {"id": "a", "dateCreated": "2026-11-18T10:00:00+02:00"}
        entry = AuditLogEntry.model_validate(raw)
        assert entry.timestamp is not None
        assert entry.timestamp.utcoffset() == timedelta(hours=2)


def test_response_last_defaults_to_false() -> None:
    assert AuditLogResponse.model_validate({"content": []}).last is False


class TestAlertRuleValidation:
    def test_zero_threshold_count_rejected(self) -> None:
        from pydantic import ValidationError

        from cja_audit_log_monitor.models import AlertRule

        with pytest.raises(ValidationError):
            AlertRule(name="x", threshold_count=0)

    def test_zero_window_rejected(self) -> None:
        from pydantic import ValidationError

        from cja_audit_log_monitor.models import AlertRule

        with pytest.raises(ValidationError):
            AlertRule(name="x", threshold_window_minutes=0)

    def test_actions_normalized_and_accept_enum_members(self) -> None:
        from cja_audit_log_monitor.models import AlertRule

        rule = AlertRule(name="x", actions=["delete", ActionType.EXPORT], components=["data_view"])
        assert rule.actions == ["DELETE", "EXPORT"]
        assert rule.components == ["DATA_VIEW"]


class TestControlCharacters:
    """Control characters in entry text never reach a terminal (G31)."""

    HOSTILE = "name\x1b]0;PWNED\x07\x1b[2J\x1b[41mRED\x9b\x7f\ttab\rcr"

    def test_printable_replaces_control_characters(self) -> None:
        from cja_audit_log_monitor.models import printable

        text = printable(self.HOSTILE + "\nline")
        assert "\x1b" not in text and "\x07" not in text and "\x9b" not in text
        assert "\x7f" not in text and "\r" not in text
        assert "\ttab" not in text and " tab" in text
        assert "\nline" in text  # a line break stays

    def test_entry_text_fields_are_printable(self) -> None:
        entry = AuditLogEntry.model_validate({
            "id": "1",
            "componentName": self.HOSTILE,
            "description": self.HOSTILE,
            "user": {"id": "U1", "name": self.HOSTILE, "email": "e\x1b@example.com"},
        })
        for value in (entry.component_name, entry.description, entry.user_name,
                      entry.user_email):
            assert "\x1b" not in value
