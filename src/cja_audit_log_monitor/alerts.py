"""Alert system for suspicious activity detection."""

import logging
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from rich.panel import Panel

from .formatters import format_alert
from .models import ActionType, AlertRule, AuditLogEntry, ComponentType
from .utils import (
    get_user_identifier,
    get_user_key,
    group_by_user,
    local_tz_name,
    to_local,
    user_identities,
)

logger = logging.getLogger(__name__)

_EPOCH = datetime.min.replace(tzinfo=UTC)

# Anomaly thresholds: a check needs this much activity before it means anything.
OFF_HOURS_END = 5  # off-hours are 00:00 up to, not including, 05:00
OFF_HOURS_MIN_COUNT = 5
HIGH_ACTIVITY_MIN_COUNT = 20
BULK_DELETE_MIN_COUNT = 11


@dataclass
class FiredAlert:
    """A triggered alert with all data needed for display + delivery."""

    rule_name: str
    message: str
    entry: AuditLogEntry
    panel: Panel


# Default alert rules
DEFAULT_ALERT_RULES = [
    AlertRule(
        name="bulk_delete",
        description="Multiple delete operations in short timeframe",
        enabled=True,
        actions=[ActionType.DELETE],
        threshold_count=5,
        threshold_window_minutes=60,
        per_user=True,
    ),
    AlertRule(
        name="bulk_export",
        description="Multiple export operations",
        enabled=True,
        actions=[ActionType.EXPORT],
        threshold_count=3,
        threshold_window_minutes=30,
        per_user=True,
    ),
    AlertRule(
        name="sensitive_component_delete",
        description="Deletion of sensitive components",
        enabled=True,
        actions=[ActionType.DELETE],
        components=[
            ComponentType.DATA_VIEW,
            ComponentType.CONNECTION,
            ComponentType.FILTER,
            ComponentType.CALCULATED_METRIC,
        ],
        threshold_count=1,
        threshold_window_minutes=1,
    ),
    AlertRule(
        name="bulk_share",
        description="Bulk sharing activity",
        enabled=True,
        actions=[ActionType.SHARE],
        threshold_count=10,
        threshold_window_minutes=60,
        per_user=True,
    ),
]


def order_oldest_first(entries: list[AuditLogEntry]) -> list[AuditLogEntry]:
    """Sort entries by event time, oldest first, so rule windows slide forward.

    Entries without a timestamp are treated as happening now and go last.
    """
    return sorted(entries, key=lambda e: (e.timestamp is None, e.timestamp or _EPOCH))


class AlertEngine:
    """Engine for detecting suspicious patterns in audit logs."""

    def __init__(self, rules: list[AlertRule] | None = None) -> None:
        """Initialize alert engine.

        Args:
            rules: Alert rules to use. Defaults to DEFAULT_ALERT_RULES.
        """
        # Deep-copy so toggling a rule here never changes the caller's rule objects
        source = DEFAULT_ALERT_RULES if rules is None else rules
        self.rules = [rule.model_copy(deep=True) for rule in source]
        self._event_history: dict[tuple[str, str], list[tuple[datetime, AuditLogEntry]]] = (
            defaultdict(list)
        )

    def add_rule(self, rule: AlertRule) -> None:
        """Add an alert rule.

        Args:
            rule: Alert rule to add.
        """
        self.rules.append(rule)

    def remove_rule(self, name: str) -> bool:
        """Remove an alert rule by name.

        Args:
            name: Name of rule to remove.

        Returns:
            True if rule was found and removed.
        """
        for i, rule in enumerate(self.rules):
            if rule.name == name:
                self.rules.pop(i)
                return True
        return False

    def enable_rule(self, name: str) -> bool:
        """Enable an alert rule by name.

        Args:
            name: Name of rule to enable.

        Returns:
            True if rule was found.
        """
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = True
                return True
        return False

    def disable_rule(self, name: str) -> bool:
        """Disable an alert rule by name.

        Args:
            name: Name of rule to disable.

        Returns:
            True if rule was found.
        """
        for rule in self.rules:
            if rule.name == name:
                rule.enabled = False
                return True
        return False

    def _clean_old_events(self, key: tuple[str, str], window: timedelta, now: datetime) -> None:
        """Remove events older than the window, measured back from ``now``.

        ``now`` is the newest event time seen for the key, not the wall clock,
        so replayed or late-indexed events are judged by when they happened.

        Args:
            key: History key, ``(rule_name, user_key)``.
            window: Length of the rule's time window.
            now: Reference time; events at or before ``now - window`` are dropped.
        """
        cutoff = now - window
        self._event_history[key] = [
            (ts, entry) for ts, entry in self._event_history[key] if ts > cutoff
        ]

    def _matches_rule(self, entry: AuditLogEntry, rule: AlertRule) -> bool:
        """Check if entry matches rule criteria.

        Args:
            entry: Audit log entry.
            rule: Alert rule.

        Returns:
            True if entry matches rule criteria.
        """
        # Check action match (names are upper-cased strings; unknown ones match too)
        if rule.actions and (not entry.action or entry.action.upper() not in rule.actions):
            return False

        # Check component match
        if rule.components and (
            not entry.component_type or entry.component_type.upper() not in rule.components
        ):
            return False

        # Check user match
        if rule.users:
            # A rule may name a user by IMS id, email or display name.
            if not user_identities(entry) & set(rule.users):
                return False

        return True

    def check_entry(self, entry: AuditLogEntry) -> list[FiredAlert]:
        """Check an audit log entry against all rules.

        Args:
            entry: Audit log entry to check.

        Returns:
            List of FiredAlert objects for triggered rules.
        """
        fired: list[FiredAlert] = []
        timestamp = entry.timestamp or datetime.now(UTC)

        for rule in self.rules:
            if not rule.enabled:
                continue

            if not self._matches_rule(entry, rule):
                continue

            key = (rule.name, get_user_key(entry) if rule.per_user else "")

            # Add to event history
            self._event_history[key].append((timestamp, entry))

            # Clean old events, measured from the newest event time for this key. A
            # timestamp in the future must not push the window past real events.
            newest = max(ts for ts, _ in self._event_history[key])
            self._clean_old_events(
                key,
                timedelta(minutes=rule.threshold_window_minutes),
                min(newest, datetime.now(UTC)),
            )

            # Check threshold
            event_count = len(self._event_history[key])
            if event_count >= rule.threshold_count:
                message = (
                    f"{rule.description or rule.name}: "
                    f"{event_count} events in {rule.threshold_window_minutes} minutes"
                )
                panel = format_alert(entry, rule.name, message)
                fired.append(FiredAlert(
                    rule_name=rule.name,
                    message=message,
                    entry=entry,
                    panel=panel,
                ))

                # Log alert
                logger.warning(
                    "Alert triggered: %s - %s events by %s",
                    rule.name,
                    event_count,
                    get_user_identifier(entry),
                )

                # Clear history to avoid repeated alerts
                self._event_history[key] = []

        return fired

    def check_batch(self, entries: list[AuditLogEntry]) -> list[FiredAlert]:
        """Check a batch of entries against all rules.

        Entries are processed oldest first, whatever order they arrive in.

        Args:
            entries: List of audit log entries.

        Returns:
            List of FiredAlert objects for triggered rules.
        """
        ordered = order_oldest_first(entries)
        all_fired: list[FiredAlert] = []
        for entry in ordered:
            all_fired.extend(self.check_entry(entry))
        return all_fired

    def get_rule_status(self) -> list[dict[str, Any]]:
        """Get status of all rules.

        Returns:
            List of rule status dictionaries.
        """
        return [
            {
                "name": rule.name,
                "description": rule.description,
                "enabled": rule.enabled,
                "actions": list(rule.actions) if rule.actions else None,
                "components": list(rule.components) if rule.components else None,
                "users": list(rule.users) if rule.users else None,
                "per_user": rule.per_user,
                "threshold_count": rule.threshold_count,
                "threshold_window_minutes": rule.threshold_window_minutes,
                "pending_events": sum(
                    len(events)
                    for (name, _user), events in self._event_history.items()
                    if name == rule.name
                ),
            }
            for rule in self.rules
        ]


def analyze_for_anomalies(
    entries: list[AuditLogEntry], local: bool = False
) -> list[dict[str, Any]]:
    """Analyze entries for anomalous patterns.

    This performs batch analysis looking for unusual patterns.

    Args:
        entries: List of audit log entries.
        local: Judge off-hours (midnight to 5am) by the local time zone
            instead of UTC. The TUI sets this; the CLI keeps UTC.

    Returns:
        List of anomaly reports.

    Note:
        When adding new anomaly types, fields whose values fluctuate between
        cycles (counts, averages) must be added to
        ``notifications.AnomalyDedupFilter._EXCLUDED_FIELDS`` or per-cycle
        re-dispatch will silently break for that anomaly type.
    """
    anomalies: list[dict[str, Any]] = []

    if not entries:
        return anomalies

    # Group by user
    user_actions = group_by_user(entries)
    total_actions = len(entries)

    # Check for users with unusually high activity, judged against the other users
    if len(user_actions) > 1:
        for user, actions in user_actions.items():
            others_mean = (total_actions - len(actions)) / (len(user_actions) - 1)
            if len(actions) >= HIGH_ACTIVITY_MIN_COUNT and len(actions) > others_mean * 3:
                anomalies.append({
                    "type": "high_activity_user",
                    "user": user,
                    "action_count": len(actions),
                    "average": others_mean,
                    "description": (
                        f"User {user} has {len(actions)} actions "
                        f"({others_mean:.1f} avg for other users)"
                    ),
                })

    # Check for concentrated delete activity, one report per user
    delete_entries = [e for e in entries if e.action == ActionType.DELETE.value]
    for user, deletes in group_by_user(delete_entries).items():
        if len(deletes) >= BULK_DELETE_MIN_COUNT:
            anomalies.append({
                "type": "bulk_delete_single_user",
                "user": user,
                "delete_count": len(deletes),
                "description": f"User {user} performed {len(deletes)} deletes",
            })

    # Check for unusual time patterns (if timestamps available)
    # Hours are UTC unless ``local`` is set; the description names the zone either way.
    zone = local_tz_name() if local else "UTC"
    hour_counts: dict[int, int] = defaultdict(int)
    for entry in entries:
        if entry.timestamp:
            ts = to_local(entry.timestamp) if local else entry.timestamp
            hour_counts[ts.hour] += 1

    if hour_counts:
        avg_per_hour = sum(hour_counts.values()) / 24
        for hour, count in hour_counts.items():
            # Flag a real burst in off-hours (midnight up to OFF_HOURS_END)
            if (
                0 <= hour < OFF_HOURS_END
                and count >= OFF_HOURS_MIN_COUNT
                and count > avg_per_hour * 2
            ):
                anomalies.append({
                    "type": "off_hours_activity",
                    "hour": hour,
                    "action_count": count,
                    "description": (
                        f"Unusual activity at {hour:02d}:00 {zone} ({count} actions)"
                    ),
                })

    return anomalies
