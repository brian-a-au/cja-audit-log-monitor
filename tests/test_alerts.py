"""Tests for alerts module."""

import random
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
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
            AuditLogEntry(action="DELETE", user_email="deleter@example.com") for _ in range(15)
        ]

        anomalies = analyze_for_anomalies(entries)
        bulk_delete = [a for a in anomalies if a["type"] == "bulk_delete_single_user"]
        assert len(bulk_delete) == 1
        assert bulk_delete[0]["user"] == "deleter@example.com"

    def test_no_bulk_delete_multiple_users(self) -> None:
        """Test that bulk deletes by multiple users is not flagged."""
        entries = []
        for i in range(15):
            entries.append(AuditLogEntry(action="DELETE", user_email=f"user{i}@example.com"))

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


class TestAnomalyThresholds:
    """Anomaly checks need enough activity to mean something."""

    @staticmethod
    def _at(i, hour, user="u"):
        ts = datetime(2026, 11, 17, hour, i % 60, tzinfo=UTC)
        return AuditLogEntry(id=f"e{hour}-{i}", user_id=user, timestamp=ts)

    def _spread(self, count):
        return [self._at(i, 6 + i % 18) for i in range(count)]

    @staticmethod
    def _types(entries, kind):
        return [a for a in analyze_for_anomalies(entries) if a["type"] == kind]

    def test_single_off_hours_event_is_not_flagged(self):
        entries = self._spread(4) + [self._at(0, 3)]
        assert self._types(entries, "off_hours_activity") == []

    def test_six_events_at_three_am_are_flagged(self):
        entries = self._spread(44) + [self._at(i, 3) for i in range(6)]
        off = self._types(entries, "off_hours_activity")
        assert [a["hour"] for a in off] == [3]
        assert off[0]["action_count"] == 6

    def test_six_events_at_five_am_are_not_off_hours(self):
        entries = self._spread(44) + [self._at(i, 5) for i in range(6)]
        assert self._types(entries, "off_hours_activity") == []

    def test_high_activity_compares_with_other_users(self):
        entries = [self._at(i, 9, "a") for i in range(98)] + [
            self._at(0, 9, "b"),
            self._at(1, 9, "c"),
        ]
        high = self._types(entries, "high_activity_user")
        assert [a["user"] for a in high] == ["a"]
        assert high[0]["action_count"] == 98
        assert high[0]["average"] == 1

    def test_single_user_is_never_high_activity(self):
        entries = [self._at(i, 9, "a") for i in range(100)]
        assert self._types(entries, "high_activity_user") == []

    def test_bulk_delete_is_reported_per_user(self):
        entries = [AuditLogEntry(id=f"d{i}", action="DELETE", user_id="a") for i in range(100)] + [
            AuditLogEntry(id="x", action="DELETE", user_id="b")
        ]
        bulk = self._types(entries, "bulk_delete_single_user")
        assert [a["user"] for a in bulk] == ["a"]
        assert bulk[0]["delete_count"] == 100

    def test_ten_deletes_are_not_bulk(self):
        entries = [AuditLogEntry(id=f"d{i}", action="DELETE", user_id="a") for i in range(10)]
        assert self._types(entries, "bulk_delete_single_user") == []


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
        busy = [self._at(f"b{i}", 10, i) for i in range(30)]
        spread = [self._at(f"s{h}", h, 0) for h in range(16, 23)]
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
        entries = [self._at(f"b{i}", 3, i) for i in range(30)]
        off = [a for a in analyze_for_anomalies(entries) if a["type"] == "off_hours_activity"]
        assert off[0]["description"].startswith("Unusual activity at 03:00 UTC")


class TestAccountMatching:
    def _rule(self, users):
        return AlertRule(
            name="r",
            description="d",
            actions=[ActionType.DELETE],
            users=users,
            threshold_count=1,
            threshold_window_minutes=60,
        )

    @pytest.mark.parametrize("listed", ["ABC@techacct.adobe.com", "My Integration"])
    def test_rule_matches_ims_id_or_name(self, listed):
        engine = AlertEngine(rules=[])
        entry = AuditLogEntry(
            id="1", action="DELETE", user_id="ABC@techacct.adobe.com", user_name="My Integration"
        )
        assert engine._matches_rule(entry, self._rule([listed]))

    def test_rule_matches_email(self):
        engine = AlertEngine(rules=[])
        entry = AuditLogEntry(
            id="1", action="DELETE", user_id="X@abc.e", user_email="pat@example.com"
        )
        assert engine._matches_rule(entry, self._rule(["pat@example.com"]))
        assert engine._matches_rule(entry, self._rule(["X@abc.e"]))

    def test_anomalies_do_not_merge_accounts_with_same_name(self):
        entries = (
            [
                AuditLogEntry(id=f"a{i}", user_id="A@techacct.adobe.com", user_name="Integration")
                for i in range(5)
            ]
            + [
                AuditLogEntry(id=f"b{i}", user_id="B@techacct.adobe.com", user_name="Integration")
                for i in range(5)
            ]
            + [
                AuditLogEntry(id=f"c{i}", user_id=f"C{i}@x.e", user_email=f"c{i}@example.com")
                for i in range(4)
            ]
        )
        high = [a for a in analyze_for_anomalies(entries) if a["type"] == "high_activity_user"]
        # 14 actions over 6 accounts: average 2.3, so no account has 3x the average.
        assert high == []


class TestEventTimeWindows:
    """Rule windows follow event time, never the wall clock."""

    BASE = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    def _deletes(self, count, start, step_minutes=1, component_type=None):
        return [
            AuditLogEntry(
                action="DELETE",
                component_type=component_type,
                timestamp=start + timedelta(minutes=i * step_minutes),
                user_id="u1",
            )
            for i in range(count)
        ]

    def _default_engine(self):
        return AlertEngine(rules=[r.model_copy() for r in DEFAULT_ALERT_RULES])

    def test_old_burst_fires_by_event_time(self):
        entries = self._deletes(10, self.BASE - timedelta(hours=2))
        fired = self._default_engine().check_batch(entries)
        assert [a.rule_name for a in fired] == ["bulk_delete", "bulk_delete"]

    def test_shuffled_batch_gives_same_result(self):
        entries = self._deletes(10, self.BASE - timedelta(hours=2))
        random.Random(7).shuffle(entries)
        fired = self._default_engine().check_batch(entries)
        assert [a.rule_name for a in fired] == ["bulk_delete", "bulk_delete"]

    def test_newest_first_batch_gives_the_sorted_result(self):
        """Pages come newest first; the result must not depend on that order."""
        rule = AlertRule(
            name="three",
            actions=[ActionType.DELETE],
            threshold_count=3,
            threshold_window_minutes=10,
        )
        early = self._deletes(3, self.BASE - timedelta(hours=2), step_minutes=1)
        late = self._deletes(2, self.BASE - timedelta(minutes=30), step_minutes=1)
        oldest_first = early + late
        sorted_fired = AlertEngine(rules=[rule]).check_batch(oldest_first)
        newest_first = AlertEngine(rules=[rule.model_copy()]).check_batch(oldest_first[::-1])
        assert len(sorted_fired) == 1
        assert len(newest_first) == len(sorted_fired)

    def test_sensitive_delete_two_minutes_old_fires(self):
        entry = AuditLogEntry(
            action="DELETE",
            component_type="DATA_VIEW",
            timestamp=self.BASE - timedelta(minutes=2),
        )
        fired = self._default_engine().check_batch([entry])
        assert "sensitive_component_delete" in [a.rule_name for a in fired]

    def test_events_outside_window_never_count_together(self):
        rule = AlertRule(
            name="pair",
            actions=[ActionType.DELETE],
            threshold_count=2,
            threshold_window_minutes=60,
        )
        engine = AlertEngine(rules=[rule])
        assert engine.check_batch(self._deletes(2, self.BASE, step_minutes=90)) == []


class FrozenClock(datetime):
    """datetime whose now() is fixed, for patching the alerts module clock."""

    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 3, 1, 12, 0, tzinfo=UTC)


class TestFutureTimestamps:
    """The reference time for pruning never runs ahead of the clock."""

    NOW = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    def _engine(self):
        rule = AlertRule(
            name="trio",
            actions=[ActionType.DELETE],
            threshold_count=3,
            threshold_window_minutes=60,
        )
        return AlertEngine(rules=[rule])

    def _delete(self, when):
        return AuditLogEntry(action="DELETE", timestamp=when, user_id="u1")

    def test_future_stamped_event_does_not_hide_real_events(self, monkeypatch):
        monkeypatch.setattr("cja_audit_log_monitor.alerts.datetime", FrozenClock)
        engine = self._engine()
        assert engine.check_entry(self._delete(self.NOW - timedelta(minutes=10))) == []
        assert engine.check_entry(self._delete(self.NOW - timedelta(minutes=5))) == []
        # The future-stamped event still counts, and the two real events are kept with it.
        fired = engine.check_entry(self._delete(self.NOW + timedelta(days=3650)))
        assert [a.rule_name for a in fired] == ["trio"]

    def test_late_event_inside_window_still_counts(self, monkeypatch):
        monkeypatch.setattr("cja_audit_log_monitor.alerts.datetime", FrozenClock)
        engine = self._engine()
        engine.check_entry(self._delete(self.NOW - timedelta(minutes=1)))
        engine.check_entry(self._delete(self.NOW - timedelta(minutes=2)))
        fired = engine.check_entry(self._delete(self.NOW - timedelta(minutes=50)))
        assert [a.rule_name for a in fired] == ["trio"]

    def test_late_event_outside_window_is_dropped(self, monkeypatch):
        monkeypatch.setattr("cja_audit_log_monitor.alerts.datetime", FrozenClock)
        engine = self._engine()
        engine.check_entry(self._delete(self.NOW - timedelta(minutes=1)))
        engine.check_entry(self._delete(self.NOW - timedelta(minutes=2)))
        assert engine.check_entry(self._delete(self.NOW - timedelta(minutes=90))) == []
        assert len(engine._event_history[("trio", "")]) == 2


class TestPerUserRules:
    """Per-user rules count each person's events separately."""

    BASE = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    def _deletes(self, users):
        return [
            AuditLogEntry(
                action="DELETE",
                timestamp=self.BASE + timedelta(minutes=i),
                user_id=f"id-{u}",
                user_email=f"{u}@example.com",
            )
            for i, u in enumerate(users)
        ]

    def test_five_users_deleting_once_do_not_fire(self) -> None:
        fired = AlertEngine().check_batch(self._deletes([f"u{i}" for i in range(5)]))
        assert [a.rule_name for a in fired if a.rule_name == "bulk_delete"] == []

    def test_one_user_deleting_five_times_fires_and_names_user(self) -> None:
        fired = AlertEngine().check_batch(self._deletes(["u1"] * 5))
        bulk = [a for a in fired if a.rule_name == "bulk_delete"]
        assert len(bulk) == 1
        assert bulk[0].entry.user_email == "u1@example.com"

    def test_non_per_user_rule_still_counts_everyone(self) -> None:
        rule = AlertRule(name="all", actions=["DELETE"], threshold_count=3)
        fired = AlertEngine(rules=[rule]).check_batch(self._deletes(["a", "b", "c"]))
        assert len(fired) == 1

    def test_defaults_are_per_user(self) -> None:
        per_user = {r.name for r in DEFAULT_ALERT_RULES if r.per_user}
        assert per_user == {"bulk_delete", "bulk_export", "bulk_share"}

    def test_rule_status_has_users_and_per_user(self) -> None:
        row = AlertEngine().get_rule_status()[0]
        assert "users" in row and "per_user" in row
        assert row["per_user"] is True

    def test_unknown_action_matches_by_string(self) -> None:
        rule = AlertRule(name="arch", actions=["archive"], threshold_count=1)
        entry = AuditLogEntry(action="ARCHIVE", timestamp=self.BASE)
        assert AlertEngine(rules=[rule]).check_entry(entry)

    def test_same_display_name_different_ids_do_not_share_a_bucket(self) -> None:
        def delete(i, uid):
            return AuditLogEntry(
                action="DELETE",
                timestamp=self.BASE + timedelta(minutes=i),
                user_id=uid,
                user_name="Integration",
            )

        mixed = [delete(i, "AAA11111" if i % 2 else "BBB22222") for i in range(6)]
        assert AlertEngine().check_batch(mixed) == []
        one = [delete(i, "AAA11111") for i in range(5)]
        fired = AlertEngine().check_batch(one)
        assert len(fired) == 1
        assert fired[0].entry.user_id == "AAA11111"


class TestEngineCopiesRules:
    """The engine must not share rule objects with its caller."""

    def test_toggling_a_rule_leaves_the_callers_rule_alone(self):
        original = AlertRule(name="mine", enabled=True)
        engine = AlertEngine([original])
        engine.rules[0].enabled = False
        assert original.enabled is True


class TestRuleDefinitions:
    """Rule definitions mean what they say (G13, G17, G43)."""

    def test_duplicate_rule_names_are_a_config_error(self, tmp_path) -> None:
        from cja_audit_log_monitor.config import ConfigError, load_config

        path = tmp_path / "config.yaml"
        path.write_text(
            "alert_rules:\n"
            "  - {name: deletes, actions: [DELETE], threshold_count: 2}\n"
            "  - {name: deletes, actions: [DELETE], threshold_count: 2}\n"
        )
        path.chmod(0o600)
        with pytest.raises(ConfigError, match="deletes"):
            load_config(path)

    def test_users_match_ignores_case_and_spaces(self) -> None:
        rule = AlertRule(name="named", users=[" Someone@Example.com "])
        engine = AlertEngine(rules=[rule])
        entry = AuditLogEntry(
            id="1",
            action="DELETE",
            user_email="someone@example.com",
            timestamp=datetime.now(UTC),
        )
        assert [a.rule_name for a in engine.check_entry(entry)] == ["named"]

    def test_window_has_an_upper_limit(self) -> None:
        with pytest.raises(ValidationError):
            AlertRule(name="r", threshold_window_minutes=999_999_999_999)
        assert AlertRule(name="r", threshold_window_minutes=525_600)

    @pytest.mark.parametrize("field", ["actions", "components", "users"])
    def test_empty_list_is_an_error(self, field) -> None:
        with pytest.raises(ValidationError, match="leave it out"):
            AlertRule(name="r", **{field: []})

    def test_empty_alert_rules_means_no_rules(self, tmp_path) -> None:
        from cja_audit_log_monitor.alerts import engine_rules
        from cja_audit_log_monitor.config import load_config

        path = tmp_path / "config.yaml"
        path.write_text("alert_rules: []\n")
        path.chmod(0o600)
        assert AlertEngine(engine_rules(load_config(path))).rules == []
        empty = tmp_path / "empty.yaml"
        empty.write_text("monitor_interval: 30\n")
        empty.chmod(0o600)
        assert len(AlertEngine(engine_rules(load_config(empty))).rules) == 4

    def test_lower_case_delete_counts_for_the_bulk_delete_anomaly(self) -> None:
        entries = [
            AuditLogEntry(
                id=str(i),
                action="delete",
                user_email="u@example.com",
                timestamp=datetime.now(UTC),
            )
            for i in range(20)
        ]
        kinds = [a["type"] for a in analyze_for_anomalies(entries)]
        assert "bulk_delete_single_user" in kinds


class MovableClock(datetime):
    """datetime whose now() the test sets."""

    current = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    @classmethod
    def now(cls, tz=None):
        return cls.current


class TestFutureTimestampsAgeOut:
    """An event stamped in the future is counted at the wall clock time (G18)."""

    T = datetime(2026, 3, 1, 12, 0, tzinfo=UTC)

    @staticmethod
    def _delete(when: datetime) -> AuditLogEntry:
        return AuditLogEntry(action="DELETE", timestamp=when, user_id="u1")

    def test_future_event_ages_out_of_the_window(self, monkeypatch) -> None:
        monkeypatch.setattr("cja_audit_log_monitor.alerts.datetime", MovableClock)
        rule = AlertRule(name="trio", actions=[ActionType.DELETE], threshold_count=3)
        engine = AlertEngine(rules=[rule])
        MovableClock.current = self.T
        engine.check_entry(self._delete(self.T + timedelta(days=365)))
        MovableClock.current = self.T + timedelta(hours=2)
        later = self.T + timedelta(hours=2)
        fired = [
            alert
            for seconds in (10, 20)
            for alert in engine.check_entry(self._delete(later - timedelta(seconds=seconds)))
        ]
        assert fired == []  # two real deletes do not make three


def test_short_lookback_steady_night_is_not_flagged() -> None:
    day = datetime(2026, 3, 1, tzinfo=UTC)
    entries = [
        AuditLogEntry(
            id=f"{h}-{i}",
            action="EDIT",
            user_id=f"u{i}",
            timestamp=day + timedelta(hours=h, minutes=i),
        )
        for h in (2, 3)
        for i in range(10)
    ]
    kinds = [a["type"] for a in analyze_for_anomalies(entries, lookback_hours=2)]
    assert "off_hours_activity" not in kinds
    # Over a full day the same two busy night hours stand out.
    kinds = [a["type"] for a in analyze_for_anomalies(entries)]
    assert "off_hours_activity" in kinds


def test_anomalies_command_passes_its_lookback() -> None:
    from unittest.mock import MagicMock, patch

    from click.testing import CliRunner

    from cja_audit_log_monitor.cli import main

    client = MagicMock()
    client.get_all_logs.return_value = []
    client.__enter__ = MagicMock(return_value=client)
    client.__exit__ = MagicMock(return_value=False)
    with (
        patch("cja_audit_log_monitor.cli.get_client", return_value=(client, MagicMock())),
        patch("cja_audit_log_monitor.cli.analyze_for_anomalies", return_value=[]) as analyze,
    ):
        CliRunner().invoke(main, ["cli", "anomalies", "--lookback", "2"])
    assert analyze.call_args.kwargs.get("lookback_hours") == 2


class TestAlertTexts:
    """Alert texts name the user once and read correctly (G19, G43)."""

    @staticmethod
    def _deletes(count, user="mallory@example.com"):
        now = datetime.now(UTC)
        return [
            AuditLogEntry(
                id=f"{user}{i}",
                action="DELETE",
                user_email=user,
                timestamp=now - timedelta(seconds=count - i),
            )
            for i in range(count)
        ]

    def test_per_user_summary_names_the_user_and_the_rule_once(self) -> None:
        engine = AlertEngine()  # built-in rules: bulk_delete counts each user
        fired = engine.check_batch(self._deletes(5))
        bulk = [a for a in fired if a.rule_name == "bulk_delete"]
        assert bulk[0].summary == "bulk_delete: 5 events in 60 minutes by mallory@example.com"

    def test_all_users_rule_says_latest_user(self) -> None:
        rule = AlertRule(name="team", actions=[ActionType.DELETE], threshold_count=2)
        fired = AlertEngine([rule]).check_batch(self._deletes(2))
        assert fired[0].summary == "team: 2 events in 60 minutes, latest by mallory@example.com"

    def test_sensitive_delete_message_has_no_count(self) -> None:
        entry = AuditLogEntry(
            id="1",
            action="DELETE",
            component_type="DATA_VIEW",
            user_email="u@example.com",
            timestamp=datetime.now(UTC),
        )
        fired = [
            a
            for a in AlertEngine().check_entry(entry)
            if a.rule_name == "sensitive_component_delete"
        ]
        assert fired[0].message == "Deletion of sensitive components"
        assert "1 events" not in fired[0].summary
        assert "1 minutes" not in fired[0].summary
