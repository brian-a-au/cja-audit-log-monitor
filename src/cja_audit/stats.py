"""Statistics and reporting for audit logs."""

from collections import Counter
from datetime import datetime, timedelta, timezone

from .models import AuditLogEntry, AuditLogQuery
from .utils import get_user_identifier


def calculate_stats(entries: list[AuditLogEntry]) -> dict:
    """Calculate summary statistics from audit log entries.

    Args:
        entries: List of audit log entries.

    Returns:
        Dictionary containing various statistics.
    """
    if not entries:
        return {
            "total_entries": 0,
            "top_users": [],
            "action_counts": {},
            "component_counts": {},
            "date_range": None,
        }

    # Count by user
    user_counter: Counter[str] = Counter()
    for entry in entries:
        user = get_user_identifier(entry)
        user_counter[user] += 1

    # Count by action
    action_counter: Counter[str] = Counter()
    for entry in entries:
        if entry.action:
            action_counter[entry.action] += 1

    # Count by component type
    component_counter: Counter[str] = Counter()
    for entry in entries:
        if entry.component_type:
            component_counter[entry.component_type] += 1

    # Date range
    timestamps = [e.timestamp for e in entries if e.timestamp]
    date_range = None
    if timestamps:
        min_ts = min(timestamps)
        max_ts = max(timestamps)
        date_range = {
            "start": min_ts.strftime("%Y-%m-%d %H:%M:%S"),
            "end": max_ts.strftime("%Y-%m-%d %H:%M:%S"),
        }

    return {
        "total_entries": len(entries),
        "top_users": user_counter.most_common(10),
        "action_counts": dict(action_counter),
        "component_counts": dict(component_counter),
        "date_range": date_range,
    }


def get_hourly_distribution(entries: list[AuditLogEntry]) -> dict[int, int]:
    """Get distribution of events by hour of day.

    Args:
        entries: List of audit log entries.

    Returns:
        Dictionary mapping hour (0-23) to count.
    """
    hourly: Counter[int] = Counter()
    for entry in entries:
        if entry.timestamp:
            hourly[entry.timestamp.hour] += 1

    # Ensure all hours are represented
    return {hour: hourly.get(hour, 0) for hour in range(24)}


def get_daily_distribution(entries: list[AuditLogEntry]) -> dict[str, int]:
    """Get distribution of events by day.

    Args:
        entries: List of audit log entries.

    Returns:
        Dictionary mapping date string to count.
    """
    daily: Counter[str] = Counter()
    for entry in entries:
        if entry.timestamp:
            date_str = entry.timestamp.strftime("%Y-%m-%d")
            daily[date_str] += 1

    return dict(sorted(daily.items()))


def get_user_activity(entries: list[AuditLogEntry]) -> list[tuple[str, int]]:
    """Get user activity ranking.

    Args:
        entries: List of audit log entries.

    Returns:
        List of (user, count) tuples sorted by count descending.
    """
    user_counter: Counter[str] = Counter()
    for entry in entries:
        user = get_user_identifier(entry)
        user_counter[user] += 1

    return user_counter.most_common()


def get_action_distribution(entries: list[AuditLogEntry]) -> dict[str, int]:
    """Get distribution of actions.

    Args:
        entries: List of audit log entries.

    Returns:
        Dictionary mapping action to count.
    """
    action_counter: Counter[str] = Counter()
    for entry in entries:
        if entry.action:
            action_counter[entry.action] += 1

    return dict(action_counter)


def get_component_distribution(entries: list[AuditLogEntry]) -> dict[str, int]:
    """Get distribution of component types.

    Args:
        entries: List of audit log entries.

    Returns:
        Dictionary mapping component type to count.
    """
    component_counter: Counter[str] = Counter()
    for entry in entries:
        if entry.component_type:
            component_counter[entry.component_type] += 1

    return dict(component_counter)


def get_trend(
    entries: list[AuditLogEntry],
    days: int = 7,
) -> dict[str, dict[str, int]]:
    """Get activity trend over time by action type.

    Args:
        entries: List of audit log entries.
        days: Number of days to analyze.

    Returns:
        Dictionary with date keys and action counts as values.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    recent = [e for e in entries if e.timestamp and e.timestamp >= cutoff]

    trend: dict[str, Counter[str]] = {}
    for entry in recent:
        if entry.timestamp and entry.action:
            date_str = entry.timestamp.strftime("%Y-%m-%d")
            if date_str not in trend:
                trend[date_str] = Counter()
            trend[date_str][entry.action] += 1

    return {date: dict(counts) for date, counts in sorted(trend.items())}


def generate_report(entries: list[AuditLogEntry]) -> dict:
    """Generate a comprehensive report from audit logs.

    Args:
        entries: List of audit log entries.

    Returns:
        Dictionary containing all report data.
    """
    return {
        "summary": calculate_stats(entries),
        "user_activity": get_user_activity(entries)[:20],
        "action_distribution": get_action_distribution(entries),
        "component_distribution": get_component_distribution(entries),
        "hourly_distribution": get_hourly_distribution(entries),
        "daily_distribution": get_daily_distribution(entries),
        "trend_7_day": get_trend(entries, days=7),
    }


def build_date_range_query(days: int) -> AuditLogQuery:
    """Build a query for the last N days.

    Args:
        days: Number of days to query.

    Returns:
        AuditLogQuery with date range set.
    """
    end_date = datetime.now(timezone.utc)
    start_date = end_date - timedelta(days=days)

    return AuditLogQuery(
        start_date=start_date,
        end_date=end_date,
    )
