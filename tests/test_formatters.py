"""Tests for formatters module."""

from datetime import datetime, timezone

import pytest
from rich.console import Console
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
    """Tests for action color mapping."""

    def test_create_is_green(self) -> None:
        """Test CREATE action is green."""
        assert get_action_color("CREATE") == "green"

    def test_delete_is_red(self) -> None:
        """Test DELETE action is red."""
        assert get_action_color("DELETE") == "red"

    def test_edit_is_yellow(self) -> None:
        """Test EDIT action is yellow."""
        assert get_action_color("EDIT") == "yellow"

    def test_unknown_is_white(self) -> None:
        """Test unknown action defaults to white."""
        assert get_action_color("UNKNOWN") == "white"


class TestFormatTimestamp:
    """Tests for timestamp formatting."""

    def test_format_none(self) -> None:
        """Test formatting None timestamp."""
        assert format_timestamp(None) == "-"

    def test_format_datetime(self) -> None:
        """Test formatting datetime."""
        dt = datetime(2024, 1, 15, 10, 30, 45, tzinfo=timezone.utc)
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
