"""Tests for monitoring module."""

from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from cja_audit_log_monitor.models import AuditLogEntry, AuditLogResponse
from cja_audit_log_monitor.monitor import AuditLogMonitor


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock audit logs client."""
    client = MagicMock()
    return client


@pytest.fixture
def monitor(mock_client: MagicMock) -> AuditLogMonitor:
    """Create a monitor instance with mock client."""
    return AuditLogMonitor(mock_client, interval=1)


class TestAuditLogMonitor:
    """Tests for AuditLogMonitor class."""

    def test_init(self, mock_client: MagicMock) -> None:
        """Test monitor initialization."""
        monitor = AuditLogMonitor(mock_client, interval=30)
        assert monitor.interval == 30
        assert monitor._running is False

    def test_init_default_interval(self, mock_client: MagicMock) -> None:
        """Test monitor initialization with default interval."""
        monitor = AuditLogMonitor(mock_client)
        assert monitor.interval == 60

    def test_get_new_entries_first_call(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test fetching entries on first call."""
        entries = [
            AuditLogEntry(
                id="entry-1",
                timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_client.get_logs.return_value = AuditLogResponse(content=entries, last=True)

        new_entries = monitor._get_new_entries()

        assert len(new_entries) == 1
        assert new_entries[0].id == "entry-1"

    def test_get_new_entries_filters_seen(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test that previously seen entries are filtered."""
        entries = [
            AuditLogEntry(
                id="entry-2",
                timestamp=datetime(2024, 1, 15, 10, 1, 0, tzinfo=UTC),
            ),
            AuditLogEntry(
                id="entry-1",
                timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
            ),
        ]
        mock_client.get_logs.return_value = AuditLogResponse(content=entries)

        # First call - see both entries
        monitor._get_new_entries()

        # Second call - same entries, should return empty
        new_entries = monitor._get_new_entries()
        assert len(new_entries) == 0

    def test_get_new_entries_empty_response(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test handling of empty response."""
        mock_client.get_logs.return_value = AuditLogResponse(content=[])

        new_entries = monitor._get_new_entries()
        assert new_entries == []

    def test_set_callback(self, monitor: AuditLogMonitor) -> None:
        """Test setting entry callback."""
        callback = MagicMock()
        monitor.set_callback(callback)
        assert monitor._on_new_entry == callback

    def test_stop(self, monitor: AuditLogMonitor) -> None:
        """Test stopping the monitor."""
        monitor._running = True
        monitor.stop()
        assert monitor._running is False

    def test_handle_entry_calls_callback(
        self,
        monitor: AuditLogMonitor,
    ) -> None:
        """Test that _handle_entry calls the callback."""
        callback = MagicMock()
        monitor.set_callback(callback)

        entry = AuditLogEntry(id="test-entry", action="CREATE")
        monitor._handle_entry(entry)

        callback.assert_called_once_with(entry)

    def test_handle_entry_without_callback(
        self,
        monitor: AuditLogMonitor,
    ) -> None:
        """Test _handle_entry works without callback."""
        entry = AuditLogEntry(id="test-entry", action="CREATE")
        # Should not raise
        monitor._handle_entry(entry)

    def test_get_new_entries_handles_exception(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test that exceptions are handled gracefully."""
        mock_client.get_logs.side_effect = Exception("Network error")

        # Should return empty list, not raise
        new_entries = monitor._get_new_entries()
        assert new_entries == []

    def test_get_new_entries_fetches_multiple_pages(
        self,
        monitor: AuditLogMonitor,
        mock_client: MagicMock,
    ) -> None:
        """Test monitor polling paginates to avoid missing burst events."""
        pages_requested: list[int] = []
        responses = [
            AuditLogResponse(
                content=[
                    AuditLogEntry(
                        id="entry-3",
                        timestamp=datetime(2024, 1, 15, 10, 2, 0, tzinfo=UTC),
                    ),
                    AuditLogEntry(
                        id="entry-2",
                        timestamp=datetime(2024, 1, 15, 10, 1, 0, tzinfo=UTC),
                    ),
                ],
                last=False,
            ),
            AuditLogResponse(
                content=[
                    AuditLogEntry(
                        id="entry-1",
                        timestamp=datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC),
                    )
                ],
                last=True,
            ),
        ]

        def get_logs_side_effect(query):
            pages_requested.append(query.page)
            return responses.pop(0)

        mock_client.get_logs.side_effect = get_logs_side_effect

        new_entries = monitor._get_new_entries()

        assert pages_requested == [0, 1]
        assert [entry.id for entry in new_entries] == ["entry-1", "entry-2", "entry-3"]

    def test_handle_entry_dispatches_to_notification_manager(
        self, sample_audit_entry
    ) -> None:
        """AuditLogMonitor._handle_entry calls notify_alert for each FiredAlert."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.pop_first_failure.return_value = None

        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )

        monitor._handle_entry(sample_audit_entry)
        fake_nm.notify_alert.assert_called_once_with("r", "m", sample_audit_entry)

    def test_handle_entry_works_without_notification_manager(
        self, sample_audit_entry
    ) -> None:
        """AuditLogMonitor._handle_entry behavior unchanged when notification_manager is None."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        client = MagicMock()
        monitor = AuditLogMonitor(client=client, alert_engine=fake_engine)
        monitor._handle_entry(sample_audit_entry)  # must not raise

    def test_handle_entry_suppresses_dispatch_exceptions(
        self, sample_audit_entry
    ) -> None:
        """An exception inside notify_alert does NOT prevent _handle_entry from completing."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.notify_alert.side_effect = RuntimeError("boom")
        fake_nm.pop_first_failure.return_value = None
        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )
        # Must not raise
        monitor._handle_entry(sample_audit_entry)

    def test_handle_entry_prints_pop_first_failure_warning(self, sample_audit_entry) -> None:
        """When pop_first_failure returns a string, console.print emits a yellow-tagged warning."""
        from cja_audit_log_monitor.alerts import FiredAlert

        fa = FiredAlert(rule_name="r", message="m", entry=sample_audit_entry, panel=MagicMock())
        fake_engine = MagicMock()
        fake_engine.check_entry.return_value = [fa]
        fake_nm = MagicMock()
        fake_nm.is_configured.return_value = True
        fake_nm.pop_first_failure.return_value = (
            "Notification delivery failed (slack);"
            " subsequent failures suppressed for this session — check logs."
        )

        fake_console = MagicMock()
        client = MagicMock()
        monitor = AuditLogMonitor(
            client=client,
            console=fake_console,
            alert_engine=fake_engine,
            notification_manager=fake_nm,
        )

        monitor._handle_entry(sample_audit_entry)

        # Expect console.print called with a [yellow]...[/yellow] formatted warning
        warning_calls = [c for c in fake_console.print.call_args_list if "yellow" in str(c)]
        assert warning_calls, "Expected console.print to emit a yellow-tagged warning"
