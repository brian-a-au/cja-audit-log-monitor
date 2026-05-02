"""Tests for formatters module."""

from datetime import UTC, datetime

from rich.table import Table

from cja_audit.formatters import (
    format_logs_table,
    format_single_entry,
    format_stats_panel,
    format_timestamp,
    get_action_color,
)
from cja_audit.models import AuditLogEntry


class TestActionColors:
    """Tests for action severity color mapping (3-tier + neutral)."""

    def test_destructive_actions_use_danger(self) -> None:
        assert get_action_color("DELETE") == "$danger"
        assert get_action_color("EMBARGO") == "$danger"

    def test_sensitive_actions_use_warning(self) -> None:
        assert get_action_color("EXPORT") == "$warning"
        assert get_action_color("SHARE") == "$warning"
        assert get_action_color("UNSHARE") == "$warning"
        assert get_action_color("TRANSFER") == "$warning"

    def test_safe_actions_use_success(self) -> None:
        assert get_action_color("CREATE") == "$success"
        assert get_action_color("APPROVE") == "$success"

    def test_neutral_actions_use_text_muted(self) -> None:
        assert get_action_color("EDIT") == "$text-muted"
        assert get_action_color("REFRESH") == "$text-muted"
        assert get_action_color("API_REQUEST") == "$text-muted"
        assert get_action_color("ORG_CHANGE") == "$text-muted"
        assert get_action_color("UNAPPROVE") == "$text-muted"

    def test_unknown_defaults_to_text_muted(self) -> None:
        assert get_action_color("UNKNOWN") == "$text-muted"

    def test_action_colors_has_four_distinct_values(self) -> None:
        from cja_audit.formatters import ACTION_COLORS
        assert len(set(ACTION_COLORS.values())) == 4


class TestActionIcons:
    """Tests for action severity icons."""

    def test_destructive_actions_use_cross(self) -> None:
        from cja_audit.formatters import get_action_icon
        assert get_action_icon("DELETE") == "✕"
        assert get_action_icon("EMBARGO") == "✕"

    def test_sensitive_actions_use_warning_glyph(self) -> None:
        from cja_audit.formatters import get_action_icon
        assert get_action_icon("EXPORT") == "⚠"
        assert get_action_icon("SHARE") == "⚠"
        assert get_action_icon("UNSHARE") == "⚠"
        assert get_action_icon("TRANSFER") == "⚠"

    def test_safe_actions_use_check(self) -> None:
        from cja_audit.formatters import get_action_icon
        assert get_action_icon("CREATE") == "✓"
        assert get_action_icon("APPROVE") == "✓"

    def test_neutral_actions_use_dot(self) -> None:
        from cja_audit.formatters import get_action_icon
        assert get_action_icon("EDIT") == "·"
        assert get_action_icon("REFRESH") == "·"
        assert get_action_icon("API_REQUEST") == "·"

    def test_unknown_defaults_to_dot(self) -> None:
        from cja_audit.formatters import get_action_icon
        assert get_action_icon("UNKNOWN") == "·"


class TestFormatTimestamp:
    """Tests for timestamp formatting."""

    def test_format_none(self) -> None:
        """Test formatting None timestamp."""
        assert format_timestamp(None) == "-"

    def test_format_datetime(self) -> None:
        """Test formatting datetime."""
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=UTC)
        result = format_timestamp(dt)
        assert "2024-01-15" in result
        assert "10:30:45" in result


class TestFormatLogsTable:
    """Tests for logs table formatting."""

    def test_empty_entries(self) -> None:
        """Test formatting empty list."""
        table = format_logs_table([])
        assert isinstance(table, Table)

    def test_with_entries(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test formatting entries."""
        table = format_logs_table(sample_audit_entries)
        assert isinstance(table, Table)
        assert table.row_count == 10

    def test_with_details(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test formatting with details enabled."""
        table = format_logs_table([sample_audit_entry], show_details=True)
        assert isinstance(table, Table)
        # Should have more columns with details
        assert len(table.columns) > 5


class TestFormatSingleEntry:
    """Tests for single entry formatting."""

    def test_format_entry(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test formatting single entry."""
        panel = format_single_entry(sample_audit_entry)
        assert panel is not None


class TestFormatStatsPanel:
    """Tests for stats panel formatting."""

    def test_format_stats(self) -> None:
        """Test formatting statistics."""
        stats = {
            "total_entries": 100,
            "top_users": [("user1@example.com", 50), ("user2@example.com", 30)],
            "action_counts": {"CREATE": 40, "EDIT": 35, "DELETE": 25},
            "date_range": {"start": "2024-01-01", "end": "2024-01-31"},
        }

        panel = format_stats_panel(stats)
        assert panel is not None

    def test_format_empty_stats(self) -> None:
        """Test formatting empty statistics."""
        panel = format_stats_panel({})
        assert panel is not None

    def test_format_stats_with_none_date_range(self) -> None:
        """Test formatting handles a None date_range value."""
        stats = {
            "total_entries": 5,
            "top_users": [("user@example.com", 5)],
            "action_counts": {"CREATE": 5},
            "component_counts": {"PROJECT": 5},
            "date_range": None,
        }
        panel = format_stats_panel(stats)
        assert panel is not None
