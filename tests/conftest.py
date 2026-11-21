"""Pytest fixtures for CJA Audit tests."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
from hypothesis import settings

from cja_audit_log_monitor.config import CJASettings
from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.tui.state import AppState

from .fakeapi import FakeApi, start

# No per-example deadline: a slow CI runner must not turn a pass into a flaky failure.
# Run `pytest --hypothesis-profile=deep` locally for a longer search.
settings.register_profile("default", deadline=None)
settings.register_profile("deep", deadline=None, max_examples=5000)
settings.load_profile("default")

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


@pytest.fixture(autouse=True)
def _fresh_cli_consoles(monkeypatch):
    """Give each test CLI consoles sized by its own environment, not the process's.

    Rich fixes a console's size when COLUMNS and LINES are set at the time it is made.
    The CLI makes its consoles on import, and on GitHub's Linux runners a pytest-xdist
    worker can have COLUMNS=80 and LINES=24 set by then. Every CLI test in that worker
    then rendered 80 columns wide, whatever COLUMNS the test passed to CliRunner.
    """
    from rich.console import Console

    from cja_audit_log_monitor import cli

    monkeypatch.delenv("COLUMNS", raising=False)
    monkeypatch.delenv("LINES", raising=False)
    monkeypatch.setattr(cli, "console", Console(emoji=False))
    monkeypatch.setattr(cli, "err_console", Console(stderr=True, emoji=False))


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


SECRET_MARK = "FILESECRET-aaaa1111"


def _bad_nonstr_bool_key(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(f"secret: {SECRET_MARK}\nyes: 1\n")
    return path


def _bad_nonstr_int_key(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(f"secret: {SECRET_MARK}\n1: x\n")
    return path


def _bad_not_utf8(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_bytes(f"secret: {SECRET_MARK}\nx: ".encode() + b"\xe9t\xe9\n")
    return path


def _bad_folder(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"SECRET={SECRET_MARK}\n")
    path = tmp_path / "config.yaml"
    path.mkdir()
    return path


def _bad_unreadable(tmp_path, monkeypatch):
    import os

    if hasattr(os, "geteuid") and os.geteuid() == 0:
        pytest.skip("root can read anything")
    path = tmp_path / "config.yaml"
    path.write_text(f"secret: {SECRET_MARK}\n")
    path.chmod(0)
    return path


def _bad_env_json(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(f"secret: {SECRET_MARK}\n")
    path.chmod(0o600)
    monkeypatch.setenv("NOTIFICATIONS", "{")
    return path


def _bad_dotenv_json(tmp_path, monkeypatch):
    (tmp_path / ".env").write_text(f"SECRET={SECRET_MARK}\nALERT_RULES=[\n")
    return tmp_path / "config.yaml"


def _bad_deep_nesting(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(f"secret: {SECRET_MARK}\nx: " + "[" * 5000 + "\n")
    return path


BAD_CONFIGS = {
    "bool-key": _bad_nonstr_bool_key,
    "int-key": _bad_nonstr_int_key,
    "not-utf8": _bad_not_utf8,
    "folder": _bad_folder,
    "unreadable": _bad_unreadable,
    "env-json": _bad_env_json,
    "dotenv-json": _bad_dotenv_json,
    "deep-nesting": _bad_deep_nesting,
}


@pytest.fixture(params=list(BAD_CONFIGS), ids=list(BAD_CONFIGS))
def bad_config(request, tmp_path, monkeypatch):
    """A config path (plus env) with one kind of mistake; each holds SECRET_MARK."""
    return BAD_CONFIGS[request.param](tmp_path, monkeypatch)
