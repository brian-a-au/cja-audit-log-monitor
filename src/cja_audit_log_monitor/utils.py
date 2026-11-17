"""Shared utilities for CJA Audit CLI."""

from .models import AuditLogEntry


def get_user_identifier(entry: AuditLogEntry, default: str = "unknown") -> str:
    """Get the user identifier from an audit log entry.

    Prefers user_email over user_id, with configurable default for missing values.

    Args:
        entry: The audit log entry.
        default: Default value if neither email nor ID is available.

    Returns:
        User email, user ID, or default value.
    """
    return entry.user_email or entry.user_id or default
