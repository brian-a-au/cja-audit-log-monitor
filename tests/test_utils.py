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
