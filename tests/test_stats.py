"""Tests for statistics module."""

from datetime import datetime, timezone

import pytest

from cja_audit.models import AuditLogEntry
from cja_audit.stats import (
    calculate_stats,
    get_action_distribution,
    get_daily_distribution,
    get_hourly_distribution,
    get_user_activity,
)


class TestCalculateStats:
    """Tests for calculate_stats function."""

    def test_empty_entries(self) -> None:
        """Test stats for empty list."""
        stats = calculate_stats([])

        assert stats["total_entries"] == 0
        assert stats["top_users"] == []
        assert stats["action_counts"] == {}

    def test_basic_stats(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test basic statistics calculation."""
        stats = calculate_stats(sample_audit_entries)

        assert stats["total_entries"] == 10
        assert len(stats["top_users"]) > 0
        assert "action_counts" in stats
        assert "component_counts" in stats

    def test_user_counts(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test user activity counting."""
        stats = calculate_stats(sample_audit_entries)

        # With 10 entries and 3 users (i % 3), each should have ~3-4 entries
        user_dict = dict(stats["top_users"])
        assert sum(user_dict.values()) == 10

    def test_action_counts(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test action counting."""
        stats = calculate_stats(sample_audit_entries)

        # With 10 entries and 3 action types (i % 3)
        action_counts = stats["action_counts"]
        assert "CREATE" in action_counts or "EDIT" in action_counts or "DELETE" in action_counts


class TestDistributions:
    """Tests for distribution functions."""

    def test_hourly_distribution(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test hourly distribution."""
        dist = get_hourly_distribution(sample_audit_entries)

        # Should have all 24 hours
        assert len(dist) == 24
        # All entries are at hour 10
        assert dist[10] == 10
        assert dist[0] == 0

    def test_daily_distribution(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test daily distribution."""
        dist = get_daily_distribution(sample_audit_entries)

        # All on same day
        assert len(dist) == 1
        assert "2024-01-15" in dist

    def test_action_distribution(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test action distribution."""
        dist = get_action_distribution(sample_audit_entries)

        assert isinstance(dist, dict)
        assert sum(dist.values()) == 10

    def test_user_activity(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test user activity ranking."""
        activity = get_user_activity(sample_audit_entries)

        assert len(activity) > 0
        # Should be sorted by count descending
        counts = [count for _, count in activity]
        assert counts == sorted(counts, reverse=True)
