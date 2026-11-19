"""Shared utilities for CJA Audit Log Monitor."""

from collections import OrderedDict, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

from .models import AuditLogEntry


class RecentIds:
    """A bounded set of keys that forgets the oldest one when full."""

    def __init__(self, maxlen: int) -> None:
        self._maxlen = maxlen
        self._keys: OrderedDict[str, None] = OrderedDict()

    def add(self, key: str) -> bool:
        """Remember ``key``. Return True if it was new; a repeat refreshes its recency."""
        is_new = key not in self._keys
        self._keys[key] = None
        self._keys.move_to_end(key)
        while len(self._keys) > self._maxlen:
            self._keys.popitem(last=False)
        return is_new

    def __contains__(self, key: object) -> bool:
        return key in self._keys

    def __len__(self) -> int:
        return len(self._keys)


def entry_key(entry: AuditLogEntry) -> str:
    """Return a stable key for an entry: its id, or a fingerprint of its fields."""
    return (
        entry.id
        or f"{entry.timestamp}-{entry.action}-{entry.component_type}-{entry.component_id}-"
        f"{entry.user_id}-{entry.user_email}"
    )


def redact_url(url: str) -> str:
    """Return ``<scheme>://<host>/\u2026``: enough to tell channels apart, no secrets.

    Webhook URLs carry secrets in the path, query string or user info, so only the
    scheme and host (and port) are ever shown or logged.
    """
    try:
        parts = urlsplit(url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return "<invalid url>"
    if not parts.scheme or not host:
        return "<invalid url>"
    if ":" in host:  # IPv6 literal: keep the brackets the URL needs
        host = f"[{host}]"
    netloc = f"{host}:{port}" if port else host
    return f"{parts.scheme}://{netloc}/\u2026"


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

    Prefers user_email, then user_name, then user_id, with configurable default for missing values.

    Args:
        entry: The audit log entry.
        default: Default value if neither email nor ID is available.

    Returns:
        User email, user ID, or default value.
    """
    return entry.user_email or entry.user_name or entry.user_id or default


def to_local(dt: datetime) -> datetime:
    """Convert ``dt`` to the local time zone. A naive datetime is taken as UTC."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone()


def local_tz_name() -> str:
    """Short name of the local time zone right now, e.g. ``PST``."""
    return datetime.now(UTC).astimezone().tzname() or "local"


def get_user_key(entry: AuditLogEntry) -> str:
    """A stable key for the account behind ``entry``, for grouping and counting.

    Display names are not unique (two integrations can share one), so the
    IMS user id comes first.
    """
    return entry.user_id or entry.user_email or entry.user_name or "unknown"


def user_identities(entry: AuditLogEntry) -> set[str]:
    """Every value that identifies the user of ``entry``: id, email and name."""
    return {v for v in (entry.user_id, entry.user_email, entry.user_name) if v}


def group_by_user(entries: list[AuditLogEntry]) -> dict[str, list[AuditLogEntry]]:
    """Group entries by account, keyed by a display label that is unique per account.

    The label is the usual user identifier. When two accounts share it, each
    gets the start of its id appended, e.g. ``Integration (AAA11111)``.
    """
    labels: dict[str, str] = {}
    groups: dict[str, list[AuditLogEntry]] = defaultdict(list)
    for entry in entries:
        key = get_user_key(entry)
        labels.setdefault(key, get_user_identifier(entry))
        groups[key].append(entry)

    keys_per_label: dict[str, int] = defaultdict(int)
    for label in labels.values():
        keys_per_label[label] += 1

    result: dict[str, list[AuditLogEntry]] = {}
    for key, group in groups.items():
        label = labels[key]
        if keys_per_label[label] > 1:
            label = f"{label} ({key[:8]})"
        result[label] = group
    return result
