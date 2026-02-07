"""Export functionality for audit logs."""

import csv
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO

from .models import AuditLogEntry


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
        "exported_at": datetime.now().isoformat(),
        "count": len(entries),
        "entries": [entry_to_dict(e) for e in entries],
    }

    if isinstance(output, Path):
        with open(output, "w") as f:
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
    fieldnames = [
        "id",
        "timestamp",
        "user_id",
        "user_email",
        "action",
        "component_type",
        "component_id",
        "component_name",
        "description",
        "org_id",
        "ip_address",
    ]

    count = 0

    def write_csv(f: TextIO) -> int:
        nonlocal count
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()

        for entry in entries:
            row = entry_to_dict(entry)
            # Format timestamp for CSV
            if row["timestamp"]:
                row["timestamp"] = row["timestamp"]
            writer.writerow(row)
            count += 1

        return count

    if isinstance(output, Path):
        with open(output, "w", newline="") as f:
            write_csv(f)
    else:
        write_csv(output)

    return count


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
    fieldnames = [
        "id",
        "timestamp",
        "user_id",
        "user_email",
        "action",
        "component_type",
        "component_id",
        "component_name",
        "description",
        "org_id",
        "ip_address",
    ]

    count = 0

    def write_tsv(f: TextIO) -> int:
        nonlocal count
        writer = csv.DictWriter(
            f, fieldnames=fieldnames, extrasaction="ignore", delimiter="\t"
        )
        writer.writeheader()

        for entry in entries:
            row = entry_to_dict(entry)
            writer.writerow(row)
            count += 1

        return count

    if isinstance(output, Path):
        with open(output, "w", newline="") as f:
            write_tsv(f)
    else:
        write_tsv(output)

    return count


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
        "exported_at": datetime.now().isoformat(),
        "statistics": stats,
    }

    if isinstance(output, Path):
        with open(output, "w") as f:
            if pretty:
                json.dump(data, f, indent=2, default=str)
            else:
                json.dump(data, f, default=str)
    else:
        if pretty:
            json.dump(data, output, indent=2, default=str)
        else:
            json.dump(data, output, default=str)
