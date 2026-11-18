"""Export functionality for audit logs."""

import csv
import json
import os
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from .models import AuditLogEntry


@contextmanager
def atomic_write(path: Path, newline: str | None = None) -> Iterator[TextIO]:
    """Write a UTF-8 text file atomically with private (0o600) permissions.

    The data goes to a temp file in the same folder and replaces ``path`` only
    when the block finishes. On any error the temp file is removed and an
    existing ``path`` is left untouched. A symlink at ``path`` is replaced, not
    followed.
    """
    fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            yield f
        os.replace(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def entry_to_dict(entry: AuditLogEntry) -> dict[str, Any]:
    """Convert audit log entry to dictionary for export.

    Args:
        entry: Audit log entry.

    Returns:
        Dictionary representation.
    """
    return {
        "id": entry.id,
        "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
        "user_id": entry.user_id,
        "user_email": entry.user_email,
        "user_name": entry.user_name,
        "action": entry.action,
        "component_type": entry.component_type,
        "component_id": entry.component_id,
        "component_name": entry.component_name,
        "description": entry.description,
        "org_id": entry.org_id,
        "ip_address": entry.ip_address,
    }


def export_to_json(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    pretty: bool = True,
) -> int:
    """Export audit logs to JSON file.

    Args:
        entries: Audit log entries to export.
        output: Output file path or file object.
        pretty: Whether to format JSON with indentation.

    Returns:
        Number of entries exported.
    """
    # Convert entries to list if iterator
    if not isinstance(entries, list):
        entries = list(entries)

    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "count": len(entries),
        "entries": [entry_to_dict(e) for e in entries],
    }

    if isinstance(output, Path):
        with atomic_write(output) as f:
            if pretty:
                json.dump(data, f, indent=2, default=str)
            else:
                json.dump(data, f, default=str)
    else:
        if pretty:
            json.dump(data, output, indent=2, default=str)
        else:
            json.dump(data, output, default=str)

    return len(entries)


_EXPORT_FIELDS = [
    "id",
    "timestamp",
    "user_id",
    "user_email",
    "user_name",
    "action",
    "component_type",
    "component_id",
    "component_name",
    "description",
    "org_id",
    "ip_address",
]

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> str:
    """Render a cell, prefixing ``'`` when a spreadsheet could read it as a formula.

    Text starting with ``=``, ``+``, ``-``, ``@``, tab or carriage return gets a
    leading apostrophe. This also marks plain negative numbers such as ``-5``;
    that is a deliberate trade-off. ``None`` becomes an empty cell.
    """
    if value is None:
        return ""
    text = str(value)
    if text.startswith(_FORMULA_PREFIXES):
        return "'" + text
    return text


def _write_delimited(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry], f: TextIO, delimiter: str
) -> int:
    """Write entries as delimited text with a header row; return the entry count."""
    writer = csv.writer(f, delimiter=delimiter)
    writer.writerow(_EXPORT_FIELDS)
    count = 0
    for entry in entries:
        row = entry_to_dict(entry)
        writer.writerow([_cell(row[name]) for name in _EXPORT_FIELDS])
        count += 1
    return count


def _export_delimited(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    delimiter: str,
) -> int:
    if isinstance(output, Path):
        with atomic_write(output, newline="") as f:
            return _write_delimited(entries, f, delimiter)
    return _write_delimited(entries, output, delimiter)


def export_to_csv(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
) -> int:
    """Export audit logs to CSV file.

    Args:
        entries: Audit log entries to export.
        output: Output file path or file object.

    Returns:
        Number of entries exported.
    """
    return _export_delimited(entries, output, ",")


def export_to_tsv(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
) -> int:
    """Export audit logs to TSV (tab-separated values) file.

    Args:
        entries: Audit log entries to export.
        output: Output file path or file object.

    Returns:
        Number of entries exported.
    """
    return _export_delimited(entries, output, "\t")


def export_entries(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output_path: Path,
    output_format: str = "json",
    pretty: bool = True,
) -> int:
    """Export audit logs to file in specified format.

    Args:
        entries: Audit log entries to export.
        output_path: Output file path.
        output_format: Output format ('json', 'csv', or 'tsv').
        pretty: For JSON, whether to pretty-print.

    Returns:
        Number of entries exported.

    Raises:
        ValueError: If format is not supported.
    """
    output_format = output_format.lower()

    if output_format == "json":
        return export_to_json(entries, output_path, pretty=pretty)
    elif output_format == "csv":
        return export_to_csv(entries, output_path)
    elif output_format == "tsv":
        return export_to_tsv(entries, output_path)
    else:
        raise ValueError(
            f"Unsupported export format: {output_format}. Use 'json', 'csv', or 'tsv'."
        )


def export_stats_to_json(
    stats: dict[str, Any],
    output: Path | TextIO,
    pretty: bool = True,
) -> None:
    """Export statistics to JSON file.

    Args:
        stats: Statistics dictionary.
        output: Output file path or file object.
        pretty: Whether to format JSON with indentation.
    """
    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "statistics": stats,
    }

    if isinstance(output, Path):
        with atomic_write(output) as f:
            if pretty:
                json.dump(data, f, indent=2, default=str)
            else:
                json.dump(data, f, default=str)
    else:
        if pretty:
            json.dump(data, output, indent=2, default=str)
        else:
            json.dump(data, output, default=str)
