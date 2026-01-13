"""Alert system for suspicious activity detection."""

import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from rich.panel import Panel

from .formatters import format_alert
from .models import ActionType, AlertRule, AuditLogEntry, ComponentType
from .utils import get_user_identifier

logger = logging.getLogger(__name__)


# Default alert rules
DEFAULT_ALERT_RULES = [
    AlertRule(
        name="bulk_delete",
        description="Multiple delete operations in short timeframe",
        enabled=True,
        actions=[ActionType.DELETE],
        threshold_count=5,
        threshold_window_minutes=60,
    ),
    AlertRule(
        name="bulk_export",
        description="Multiple export operations",
        enabled=True,
        actions=[ActionType.EXPORT],
        threshold_count=3,
        threshold_window_minutes=30,
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
    ),
]


class AlertEngine:
    """Engine for detecting suspicious patterns in audit logs."""

    def __init__(self, rules: list[AlertRule] | None = None) -> None:
        """Initialize alert engine.

        Args:
            rules: Alert rules to use. Defaults to DEFAULT_ALERT_RULES.
        """
        self.rules = rules if rules is not None else DEFAULT_ALERT_RULES
        self._event_history: dict[str, list[tuple[datetime, AuditLogEntry]]] = defaultdict(list)

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

    def _clean_old_events(self, rule: AlertRule) -> None:
        """Remove events outside the rule's time window.

        Args:
            rule: Rule to clean events for.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=rule.threshold_window_minutes)
        key = rule.name

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
        # Check action match
        if rule.actions:
            if not entry.action:
                return False
            try:
                entry_action = ActionType(entry.action)
                if entry_action not in rule.actions:
                    return False
            except ValueError:
                return False

        # Check component match
        if rule.components:
            if not entry.component_type:
                return False
            try:
                entry_component = ComponentType(entry.component_type)
                if entry_component not in rule.components:
                    return False
            except ValueError:
                return False

        # Check user match
        if rule.users:
            user = get_user_identifier(entry)
            if user not in rule.users:
                return False

        return True

    def check_entry(self, entry: AuditLogEntry) -> list[Panel]:
        """Check an audit log entry against all rules.

        Args:
            entry: Audit log entry to check.

        Returns:
            List of alert panels for triggered alerts.
        """
        alerts: list[Panel] = []
        timestamp = entry.timestamp or datetime.now(timezone.utc)

        for rule in self.rules:
            if not rule.enabled:
                continue

            if not self._matches_rule(entry, rule):
                continue

            # Add to event history
            self._event_history[rule.name].append((timestamp, entry))

            # Clean old events
            self._clean_old_events(rule)

            # Check threshold
            event_count = len(self._event_history[rule.name])
            if event_count >= rule.threshold_count:
                message = (
                    f"{rule.description or rule.name}: "
                    f"{event_count} events in {rule.threshold_window_minutes} minutes"
                )
                alert = format_alert(entry, rule.name, message)
                alerts.append(alert)

                # Log alert
                logger.warning(
                    "Alert triggered: %s - %s events by %s",
                    rule.name,
                    event_count,
                    get_user_identifier(entry),
                )

                # Clear history to avoid repeated alerts
                self._event_history[rule.name] = []

        return alerts

    def check_batch(self, entries: list[AuditLogEntry]) -> list[Panel]:
        """Check a batch of entries against all rules.

        Args:
            entries: List of audit log entries.

        Returns:
            List of alert panels for triggered alerts.
        """
        all_alerts: list[Panel] = []
        for entry in entries:
            alerts = self.check_entry(entry)
            all_alerts.extend(alerts)
        return all_alerts

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
                "actions": [a.value for a in rule.actions] if rule.actions else None,
                "components": [c.value for c in rule.components] if rule.components else None,
                "threshold_count": rule.threshold_count,
                "threshold_window_minutes": rule.threshold_window_minutes,
                "pending_events": len(self._event_history[rule.name]),
            }
            for rule in self.rules
        ]


def analyze_for_anomalies(entries: list[AuditLogEntry]) -> list[dict[str, Any]]:
    """Analyze entries for anomalous patterns.

    This performs batch analysis looking for unusual patterns.

    Args:
        entries: List of audit log entries.

    Returns:
        List of anomaly reports.
    """
    anomalies: list[dict[str, Any]] = []

    if not entries:
        return anomalies

    # Group by user
    user_actions: dict[str, list[AuditLogEntry]] = defaultdict(list)
    for entry in entries:
        user = get_user_identifier(entry)
        user_actions[user].append(entry)

    # Check for users with unusually high activity
    total_actions = len(entries)
    avg_per_user = total_actions / len(user_actions) if user_actions else 0

    for user, actions in user_actions.items():
        if len(actions) > avg_per_user * 3:  # 3x average
            anomalies.append({
                "type": "high_activity_user",
                "user": user,
                "action_count": len(actions),
                "average": avg_per_user,
                "description": f"User {user} has {len(actions)} actions ({avg_per_user:.1f} avg)",
            })

    # Check for concentrated delete activity
    delete_entries = [e for e in entries if e.action == ActionType.DELETE.value]
    if len(delete_entries) > 10:
        delete_users = set(get_user_identifier(e) for e in delete_entries)
        if len(delete_users) == 1:
            anomalies.append({
                "type": "bulk_delete_single_user",
                "user": list(delete_users)[0],
                "delete_count": len(delete_entries),
                "description": f"Single user performed {len(delete_entries)} deletes",
            })

    # Check for unusual time patterns (if timestamps available)
    hour_counts: dict[int, int] = defaultdict(int)
    for entry in entries:
        if entry.timestamp:
            hour_counts[entry.timestamp.hour] += 1

    if hour_counts:
        avg_per_hour = sum(hour_counts.values()) / 24
        for hour, count in hour_counts.items():
            # Flag unusual activity in off-hours (midnight to 5am)
            if 0 <= hour <= 5 and count > avg_per_hour * 2:
                anomalies.append({
                    "type": "off_hours_activity",
                    "hour": hour,
                    "action_count": count,
                    "description": f"Unusual activity at {hour}:00 ({count} actions)",
                })

    return anomalies
