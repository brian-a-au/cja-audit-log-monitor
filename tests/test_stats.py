"""Tests for statistics module."""

from cja_audit_log_monitor.models import AuditLogEntry
from cja_audit_log_monitor.stats import (
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


class TestLocalDistributions:
    def _entry(self, hour, day=17):
        from datetime import UTC, datetime

        from cja_audit_log_monitor.models import AuditLogEntry

        return AuditLogEntry(id="x", timestamp=datetime(2026, 11, day, hour, tzinfo=UTC))

    def test_hourly_local(self, los_angeles_tz):
        from cja_audit_log_monitor.stats import get_hourly_distribution

        assert get_hourly_distribution([self._entry(23)])[23] == 1
        assert get_hourly_distribution([self._entry(23)], local=True)[15] == 1

    def test_daily_local(self, los_angeles_tz):
        from cja_audit_log_monitor.stats import get_daily_distribution

        entry = self._entry(3, day=18)
        assert get_daily_distribution([entry]) == {"2026-11-18": 1}
        assert get_daily_distribution([entry], local=True) == {"2026-11-17": 1}


class TestGroupByAccount:
    """Users are counted per account, not per display name."""

    @staticmethod
    def _entry(user_id, name=None, email=None):
        from cja_audit_log_monitor.models import AuditLogEntry

        return AuditLogEntry(id=user_id, user_id=user_id, user_name=name, user_email=email)

    def test_same_name_different_accounts_stay_separate(self):
        from cja_audit_log_monitor.stats import calculate_stats, get_user_activity

        entries = [
            self._entry("AAA11111@techacct.adobe.com", name="Integration"),
            self._entry("BBB22222@techacct.adobe.com", name="Integration"),
        ]
        ranking = get_user_activity(entries)
        assert len(ranking) == 2
        assert len({label for label, _ in ranking}) == 2
        assert all(label.startswith("Integration (") for label, _ in ranking)
        assert len(calculate_stats(entries)["top_users"]) == 2

    def test_user_count_is_every_account(self):
        from cja_audit_log_monitor.stats import calculate_stats

        entries = [self._entry(f"U{i}@x.e", email=f"u{i}@example.com") for i in range(25)]
        stats = calculate_stats(entries)
        assert stats["user_count"] == 25
        assert len(stats["top_users"]) == 10


class TestTopN:
    def test_top_n_controls_how_many_users_are_returned(self):
        from cja_audit_log_monitor.models import AuditLogEntry
        from cja_audit_log_monitor.stats import calculate_stats

        entries = [
            AuditLogEntry(id=f"{i}", user_id=f"U{i}@x.e", user_email=f"u{i}@example.com")
            for i in range(15)
        ]
        assert len(calculate_stats(entries, top_n=15)["top_users"]) == 15
        assert len(calculate_stats(entries, top_n=3)["top_users"]) == 3
        assert len(calculate_stats(entries)["top_users"]) == 10


def test_stats_use_utc() -> None:
    from cja_audit_log_monitor.models import AuditLogEntry
    from cja_audit_log_monitor.stats import calculate_stats

    entry = AuditLogEntry.model_validate(
        {"id": "1", "action": "EDIT", "dateCreated": "2026-11-18T23:30:00-07:00"}
    )
    stats = calculate_stats([entry])
    assert stats["date_range"]["start"] == "2026-11-19 06:30:00"


def test_report_trend_counts_the_last_7_days_by_day_and_action() -> None:
    from datetime import UTC, datetime, timedelta

    from cja_audit_log_monitor.stats import generate_report

    now = datetime.now(UTC)

    def entry(i: int, days_ago: float, action: str) -> AuditLogEntry:
        return AuditLogEntry(
            id=f"t-{i}",
            timestamp=now - timedelta(days=days_ago),
            user_id="u",
            action=action,
            component_type="PROJECT",
        )

    entries = [
        entry(1, 0.1, "CREATE"),
        entry(2, 0.1, "CREATE"),
        entry(3, 0.1, "DELETE"),
        entry(4, 2, "EDIT"),
        entry(5, 10, "DELETE"),  # older than 7 days: not in the trend
    ]
    trend = generate_report(entries)["trend_7_day"]
    today = (now - timedelta(days=0.1)).strftime("%Y-%m-%d")
    assert trend[today] == {"CREATE": 2, "DELETE": 1}
    assert sum(sum(day.values()) for day in trend.values()) == 4
