"""Pytest fixtures for CJA Audit tests."""

from datetime import UTC, datetime

import pytest

from cja_audit.config import CJASettings
from cja_audit.models import AuditLogEntry


@pytest.fixture
def sample_settings() -> CJASettings:
    """Create sample settings for testing."""
    return CJASettings(
        client_id="test_client_id",
        secret="test_secret",
        org_id="test_org_id@AdobeOrg",
        scopes="openid,AdobeID",
    )


@pytest.fixture
def sample_audit_entry() -> AuditLogEntry:
    """Create a sample audit log entry."""
    return AuditLogEntry(
        id="entry-123",
        timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
        user_id="user-456",
        user_email="user@example.com",
        action="CREATE",
        component_type="PROJECT",
        component_id="project-789",
        component_name="Test Dashboard",
        description="Created new dashboard",
        org_id="org-001",
        ip_address="192.168.1.1",
    )


@pytest.fixture
def sample_audit_entries() -> list[AuditLogEntry]:
    """Create multiple sample audit log entries."""
    return [
        AuditLogEntry(
            id=f"entry-{i}",
            timestamp=datetime(2024, 1, 15, 10, i, 0, tzinfo=UTC),
            user_id=f"user-{i % 3}",
            user_email=f"user{i % 3}@example.com",
            action=["CREATE", "EDIT", "DELETE"][i % 3],
            component_type=["PROJECT", "FILTER", "CALCULATED_METRIC"][i % 3],
            component_id=f"component-{i}",
            component_name=f"Component {i}",
        )
        for i in range(10)
    ]


@pytest.fixture
def sample_api_response() -> dict:
    """Create a sample API response dictionary."""
    return {
        "content": [
            {
                "id": "entry-1",
                "dateCreated": "2024-01-15T10:30:00Z",
                "userId": "user-1",
                "userEmail": "user@example.com",
                "action": "CREATE",
                "componentType": "PROJECT",
                "componentId": "project-1",
                "componentName": "Dashboard",
            }
        ],
        "totalElements": 1,
        "totalPages": 1,
        "numberOfElements": 1,
        "first": True,
        "last": True,
        "number": 0,
        "size": 100,
    }


@pytest.fixture
def mock_token_response() -> dict:
    """Create a mock OAuth token response."""
    return {
        "access_token": "mock_access_token_12345",
        "token_type": "bearer",
        "expires_in": 86400,
    }
