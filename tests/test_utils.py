"""Tests for utils module."""

from pathlib import Path

from cja_audit_log_monitor.utils import display_path


class TestDisplayPath:
    """display_path hides the home directory behind '~'."""

    def test_display_path_collapses_home(self):
        assert display_path(Path.home() / ".x" / "c.yaml") == "~/.x/c.yaml"

    def test_display_path_home_itself(self):
        assert display_path(Path.home()) == "~"

    def test_display_path_other_unchanged(self):
        assert display_path(Path("/etc/x")) == "/etc/x"


def test_user_identifier_falls_back_to_name_before_id():
    from cja_audit_log_monitor.models import AuditLogEntry
    from cja_audit_log_monitor.utils import get_user_identifier

    entry = AuditLogEntry(user_id="ABCDEF@AdobeID", user_name="Pat Example")
    assert get_user_identifier(entry) == "Pat Example"


class TestLocalTime:
    def test_to_local_converts_utc(self, los_angeles_tz):
        from datetime import UTC, datetime

        from cja_audit_log_monitor.utils import to_local

        local = to_local(datetime(2026, 11, 17, 23, 25, tzinfo=UTC))
        assert (local.day, local.hour) == (17, 15)

    def test_to_local_treats_naive_as_utc(self, los_angeles_tz):
        from datetime import datetime

        from cja_audit_log_monitor.utils import to_local

        assert to_local(datetime(2026, 11, 17, 23, 25)).hour == 15

    def test_local_tz_name(self, los_angeles_tz):
        from cja_audit_log_monitor.utils import local_tz_name

        assert local_tz_name() in ("PST", "PDT")
