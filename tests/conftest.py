"""Pytest fixtures for CJA Audit tests."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from cja_audit_log_monitor.config import CJASettings
from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.tui.state import AppState

from .fakeapi import FakeApi, start

_ENV_NAMES = (
    "ORG_ID CLIENT_ID SECRET SCOPES API_BASE_URL IMS_BASE_URL MONITOR_INTERVAL "
    "DEFAULT_PAGE_SIZE DEFAULT_DAYS OUTPUT_FORMAT CJA_CONFIG_PATH"
).split()


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    """Keep shell env vars, a local .env and the real config file out of every test."""
    for name in _ENV_NAMES:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.lower(), raising=False)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("CJA_CONFIG_PATH", str(tmp_path / "config.yaml"))


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


@pytest.fixture
def mock_app_state(sample_settings, sample_audit_entries) -> AppState:
    """Create an AppState with mocked client and services for TUI testing."""
    state = AppState()
    state._settings = sample_settings

    # Mock client
    mock_client = MagicMock()
    mock_client.get_all_logs.return_value = sample_audit_entries
    mock_client.get_logs_sample.return_value = (sample_audit_entries, len(sample_audit_entries))
    mock_client.get_logs.return_value = AuditLogResponse(
        content=sample_audit_entries,
        total_elements=len(sample_audit_entries),
        total_pages=1,
        number_of_elements=len(sample_audit_entries),
        first=True,
        last=True,
        number=0,
        size=50,
    )
    mock_client.verify_connection.return_value = {
        "connected": True,
        "authenticated": True,
        "org_id": sample_settings.org_id,
        "api_url": sample_settings.api_base_url,
        "total_logs_available": len(sample_audit_entries),
    }
    mock_client.close = MagicMock()
    state._client = mock_client

    # Mock alert engine
    mock_alert_engine = MagicMock()
    mock_alert_engine.rules = []
    mock_alert_engine.check_batch.return_value = []
    state._alert_engine = mock_alert_engine

    return state


@pytest.fixture
def los_angeles_tz(monkeypatch):
    """Run a test with the local time zone set to America/Los_Angeles."""
    import time

    monkeypatch.setenv("TZ", "America/Los_Angeles")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def fake_api():
    """A local fake of IMS and the audit log API, for tests that run a real process."""
    api = start(FakeApi())
    yield api
    api.block.clear()
    assert api.server is not None
    api.server.shutdown()
    api.server.server_close()
