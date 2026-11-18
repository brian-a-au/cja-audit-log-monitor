"""Tests for alerts module."""

from datetime import UTC, datetime

import pytest
from rich.panel import Panel

from cja_audit_log_monitor.alerts import (
    DEFAULT_ALERT_RULES,
    AlertEngine,
    FiredAlert,
    analyze_for_anomalies,
)
from cja_audit_log_monitor.models import ActionType, AlertRule, AuditLogEntry, ComponentType


@pytest.fixture
def alert_engine() -> AlertEngine:
    """Create an alert engine with default rules."""
    return AlertEngine()


class TestAlertEngine:
    """Tests for AlertEngine class."""

    def test_init_default_rules(self) -> None:
        """Test initialization with default rules."""
        engine = AlertEngine()
        assert len(engine.rules) == len(DEFAULT_ALERT_RULES)

    def test_init_custom_rules(self) -> None:
        """Test initialization with custom rules."""
        custom_rules = [
            AlertRule(name="test_rule", threshold_count=1),
        ]
        engine = AlertEngine(rules=custom_rules)
        assert len(engine.rules) == 1

    def test_init_empty_rules(self) -> None:
        """Test initialization with empty rules list."""
        engine = AlertEngine(rules=[])
        assert len(engine.rules) == 0

    def test_add_rule(self, alert_engine: AlertEngine) -> None:
        """Test adding a rule."""
        initial_count = len(alert_engine.rules)
        new_rule = AlertRule(name="new_rule", threshold_count=3)
        alert_engine.add_rule(new_rule)
        assert len(alert_engine.rules) == initial_count + 1

    def test_remove_rule(self, alert_engine: AlertEngine) -> None:
        """Test removing a rule."""
        initial_count = len(alert_engine.rules)
        result = alert_engine.remove_rule("bulk_delete")
        assert result is True
        assert len(alert_engine.rules) == initial_count - 1

    def test_remove_nonexistent_rule(self, alert_engine: AlertEngine) -> None:
        """Test removing non-existent rule returns False."""
        result = alert_engine.remove_rule("nonexistent")
        assert result is False

    def test_enable_disable_rule(self, alert_engine: AlertEngine) -> None:
        """Test enabling and disabling rules."""
        alert_engine.disable_rule("bulk_delete")
        rule = next(r for r in alert_engine.rules if r.name == "bulk_delete")
        assert rule.enabled is False

        alert_engine.enable_rule("bulk_delete")
        assert rule.enabled is True

    def test_enable_nonexistent_rule(self, alert_engine: AlertEngine) -> None:
        """Test enabling non-existent rule returns False."""
        result = alert_engine.enable_rule("nonexistent")
        assert result is False

    def test_disable_nonexistent_rule(self, alert_engine: AlertEngine) -> None:
        """Test disabling non-existent rule returns False."""
        result = alert_engine.disable_rule("nonexistent")
        assert result is False

    def test_matches_rule_action(self) -> None:
        """Test rule matching by action."""
        engine = AlertEngine(rules=[])
        rule = AlertRule(
            name="delete_rule",
            actions=[ActionType.DELETE],
            threshold_count=1,
        )

        delete_entry = AuditLogEntry(action="DELETE")
        create_entry = AuditLogEntry(action="CREATE")

        assert engine._matches_rule(delete_entry, rule) is True
        assert engine._matches_rule(create_entry, rule) is False

    def test_matches_rule_component(self) -> None:
        """Test rule matching by component."""
        engine = AlertEngine(rules=[])
        rule = AlertRule(
            name="project_rule",
            components=[ComponentType.PROJECT],
            threshold_count=1,
        )

        project_entry = AuditLogEntry(component_type="PROJECT")
        filter_entry = AuditLogEntry(component_type="FILTER")

        assert engine._matches_rule(project_entry, rule) is True
        assert engine._matches_rule(filter_entry, rule) is False

    def test_matches_rule_user(self) -> None:
        """Test rule matching by user."""
        engine = AlertEngine(rules=[])
        rule = AlertRule(
            name="user_rule",
            users=["user@example.com"],
            threshold_count=1,
        )

        matching_entry = AuditLogEntry(user_email="user@example.com")
        non_matching_entry = AuditLogEntry(user_email="other@example.com")

        assert engine._matches_rule(matching_entry, rule) is True
        assert engine._matches_rule(non_matching_entry, rule) is False

    def test_matches_rule_no_action(self) -> None:
        """Test rule with action requirement but entry has no action."""
        engine = AlertEngine(rules=[])
        rule = AlertRule(
            name="delete_rule",
            actions=[ActionType.DELETE],
            threshold_count=1,
        )

        entry = AuditLogEntry(action=None)
        assert engine._matches_rule(entry, rule) is False

    def test_threshold_triggering(self) -> None:
        """Test that alerts trigger at threshold."""
        rule = AlertRule(
            name="test_threshold",
            actions=[ActionType.DELETE],
            threshold_count=3,
            threshold_window_minutes=60,
        )
        engine = AlertEngine(rules=[rule])

        entry = AuditLogEntry(
            action="DELETE",
            timestamp=datetime.now(UTC),
        )

        # First two should not trigger
        alerts = engine.check_entry(entry)
        assert len(alerts) == 0
        alerts = engine.check_entry(entry)
        assert len(alerts) == 0

        # Third should trigger
        alerts = engine.check_entry(entry)
        assert len(alerts) == 1

    def test_check_batch(self) -> None:
        """Test checking a batch of entries."""
        rule = AlertRule(
            name="test_batch",
            actions=[ActionType.DELETE],
            threshold_count=2,
            threshold_window_minutes=60,
        )
        engine = AlertEngine(rules=[rule])

        entries = [
            AuditLogEntry(action="DELETE", timestamp=datetime.now(UTC)),
            AuditLogEntry(action="DELETE", timestamp=datetime.now(UTC)),
        ]

        alerts = engine.check_batch(entries)
        assert len(alerts) == 1

    def test_get_rule_status(self, alert_engine: AlertEngine) -> None:
        """Test getting rule status."""
        status = alert_engine.get_rule_status()
        assert len(status) == len(alert_engine.rules)
        assert all("name" in s for s in status)
        assert all("enabled" in s for s in status)

    def test_disabled_rule_not_triggered(self) -> None:
        """Test that disabled rules are not triggered."""
        rule = AlertRule(
            name="disabled_rule",
            actions=[ActionType.DELETE],
            threshold_count=1,
            enabled=False,
        )
        engine = AlertEngine(rules=[rule])

        entry = AuditLogEntry(action="DELETE", timestamp=datetime.now(UTC))
        alerts = engine.check_entry(entry)
        assert len(alerts) == 0

    def test_check_entry_returns_fired_alert_with_metadata(self) -> None:
        """check_entry returns FiredAlert with rule_name, message, entry, and panel."""
        rule = AlertRule(
            name="test_rule",
            description="Test rule",
            actions=[ActionType.DELETE],
            threshold_count=1,
            threshold_window_minutes=60,
        )
        engine = AlertEngine([rule])

        entry = AuditLogEntry(
            id="e1",
            action=ActionType.DELETE.value,
            component_type=ComponentType.PROJECT.value,
            component_id="c1",
            user_email="u@example.com",
            timestamp=datetime.now(UTC),
        )

        fired = engine.check_entry(entry)
        assert len(fired) == 1
        fa = fired[0]
        assert isinstance(fa, FiredAlert)
        assert fa.rule_name == "test_rule"
        assert "Test rule" in fa.message
        assert fa.entry is entry
        assert isinstance(fa.panel, Panel)


class TestAnalyzeForAnomalies:
    """Tests for analyze_for_anomalies function."""

    def test_empty_entries(self) -> None:
        """Test with empty entry list."""
        anomalies = analyze_for_anomalies([])
        assert anomalies == []

    def test_high_activity_user(self) -> None:
        """Test detection of unusually active user."""
        entries = []
        # Create entries where one user has > 3x average activity
        # 4 users with 5 entries each (20 total) + 1 user with 60 entries = 80 total
        # Average = 80/5 = 16, so 60 > 16*3 = 48 triggers the anomaly
        for i in range(4):
            for _ in range(5):
                entries.append(AuditLogEntry(user_email=f"normal{i}@example.com"))
        for _ in range(60):
            entries.append(AuditLogEntry(user_email="active@example.com"))

        anomalies = analyze_for_anomalies(entries)
        high_activity = [a for a in anomalies if a["type"] == "high_activity_user"]
        assert len(high_activity) == 1
        assert high_activity[0]["user"] == "active@example.com"

    def test_bulk_delete_single_user(self) -> None:
        """Test detection of bulk deletes by single user."""
        entries = [
            AuditLogEntry(action="DELETE", user_email="deleter@example.com")
            for _ in range(15)
        ]

        anomalies = analyze_for_anomalies(entries)
        bulk_delete = [a for a in anomalies if a["type"] == "bulk_delete_single_user"]
        assert len(bulk_delete) == 1
        assert bulk_delete[0]["user"] == "deleter@example.com"

    def test_no_bulk_delete_multiple_users(self) -> None:
        """Test that bulk deletes by multiple users is not flagged."""
        entries = []
        for i in range(15):
            entries.append(
                AuditLogEntry(action="DELETE", user_email=f"user{i}@example.com")
            )

        anomalies = analyze_for_anomalies(entries)
        bulk_delete = [a for a in anomalies if a["type"] == "bulk_delete_single_user"]
        assert len(bulk_delete) == 0

    def test_off_hours_activity(self) -> None:
        """Test detection of off-hours activity."""
        entries = [
            AuditLogEntry(
                timestamp=datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC),  # 3 AM
                action="CREATE",
            )
            for _ in range(50)
        ]

        anomalies = analyze_for_anomalies(entries)
        off_hours = [a for a in anomalies if a["type"] == "off_hours_activity"]
        assert len(off_hours) >= 1


def test_rule_can_name_image_component():
    from cja_audit_log_monitor.alerts import AlertEngine

    rule = AlertRule(
        name="image_deletes",
        description="deleted images",
        actions=[ActionType.DELETE],
        components=[ComponentType("IMAGE")],
        threshold_count=1,
        threshold_window_minutes=60,
    )
    engine = AlertEngine(rules=[rule])
    entry = AuditLogEntry(
        id="1", timestamp=datetime.now(UTC), action="DELETE", component_type="IMAGE"
    )
    assert engine._matches_rule(entry, rule)


class TestOffHoursZone:
    """Off-hours anomalies can use local hours, and always name the zone."""

    @staticmethod
    def _at(entry_id, hour, minute):
        ts = datetime(2026, 11, 17, hour, minute, tzinfo=UTC)
        return AuditLogEntry(id=entry_id, user_id="u", timestamp=ts)

    def _entries(self):
        # 30 actions at 10:00 UTC (02:00 in Los Angeles), plus a spread of daytime ones.
        busy = [
            self._at(f"b{i}", 10, i) for i in range(30)
        ]
        spread = [
            self._at(f"s{h}", h, 0) for h in range(16, 23)
        ]
        return busy + spread

    def test_utc_by_default(self, los_angeles_tz):
        anomalies = analyze_for_anomalies(self._entries())
        assert not [a for a in anomalies if a["type"] == "off_hours_activity"]

    def test_local_hours_when_asked(self, los_angeles_tz):
        anomalies = analyze_for_anomalies(self._entries(), local=True)
        off = [a for a in anomalies if a["type"] == "off_hours_activity"]
        assert [a["hour"] for a in off] == [2]
        assert off[0]["description"].startswith("Unusual activity at 02:00 PST")

    def test_utc_description_names_utc(self):
        entries = [
            self._at(f"b{i}", 3, i) for i in range(30)
        ]
        off = [a for a in analyze_for_anomalies(entries) if a["type"] == "off_hours_activity"]
        assert off[0]["description"].startswith("Unusual activity at 03:00 UTC")
