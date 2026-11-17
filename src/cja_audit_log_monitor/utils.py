"""Shared utilities for CJA Audit CLI."""

from pathlib import Path

from .models import AuditLogEntry


def display_path(path: Path | str) -> str:
    """Return ``path`` as text with the home directory shown as ``~``.

    Keeps the user's home folder (and username) out of the UI and screenshots.
    """
    path = Path(path)
    try:
        relative = path.relative_to(Path.home())
    except ValueError:
        return str(path)
    return "~" if str(relative) == "." else f"~/{relative}"


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
