"""Export functionality for audit logs."""

import csv
import errno
import json
import os
import re
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TextIO

from .models import AuditLogEntry


@contextmanager
def atomic_write(
    path: Path, newline: str | None = None, overwrite: bool = True
) -> Iterator[TextIO]:
    """Write a UTF-8 text file atomically with private (0o600) permissions.

    The data goes to a temp file in the same folder and appears at ``path`` only
    when the block finishes. On any error the temp file is removed and an
    existing ``path`` is left untouched. A symlink at ``path`` is replaced, not
    followed.

    With ``overwrite=False`` an existing ``path`` is never replaced, even one
    that appears while the block runs: ``FileExistsError`` is raised instead.
    """
    try:
        # A short temp name, so a file name near the 255 byte limit still works.
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".cja-", suffix=".tmp")
    except OSError as e:
        raise type(e)(e.errno, e.strerror, str(path)) from e
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline=newline) as f:
            yield f
        if overwrite:
            os.replace(tmp_name, path)
        else:
            _publish_without_overwrite(tmp_name, path)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass  # keep the original error
        raise
    if not overwrite:
        with suppress(OSError):
            os.unlink(tmp_name)


def _publish_without_overwrite(tmp_name: str, path: Path) -> None:
    """Move ``tmp_name`` to ``path`` unless ``path`` exists; raise FileExistsError if it does."""
    try:
        os.link(tmp_name, path)  # fails atomically when path exists
    except FileExistsError:
        raise
    except OSError:
        # No hard links here (some network or FAT volumes): check, then replace.
        if path.exists():
            raise FileExistsError(errno.EEXIST, os.strerror(errno.EEXIST), str(path)) from None
        os.replace(tmp_name, path)


# Most file systems allow 255 bytes in one file name.
_MAX_NAME_BYTES = 255


def check_export_path(raw: str) -> tuple[Path | None, str | None, bool]:
    """Check an export path typed by a user. Never raises.

    Returns:
        The path with ``~`` expanded (None when it cannot be used), the reason it
        cannot be used (None when it can), and whether something already exists
        there (a dangling symlink counts, since writing would replace it).
    """
    raw = raw.strip()
    if not raw:
        return None, "enter a file path", False
    if raw.endswith(("/", os.sep)):
        return None, "that path is a folder, not a file", False
    if "\x00" in raw:
        return None, "the path has a null character in it", False
    try:
        path = Path(raw).expanduser()
    except RuntimeError:  # "~name" for a user that does not exist, or no home folder
        return None, f"cannot find the home folder in {raw.split('/')[0]!r}", False
    except UnicodeEncodeError:  # Python 3.11 and 3.12 fail here on "~\ud800"
        return None, "the path has characters this system cannot use in a file name", False
    try:
        os.fsencode(path)
    except UnicodeEncodeError:
        return None, "the path has characters this system cannot use in a file name", False
    if len(os.fsencode(path.name)) > _MAX_NAME_BYTES:
        return None, "the file name is too long", False
    try:
        if path.is_dir():
            return None, "that path is a folder, not a file", False
        if not path.parent.is_dir():
            return None, f"folder does not exist: {path.parent}", False
        if not os.access(path.parent, os.W_OK | os.X_OK):
            return None, f"cannot write to folder {path.parent}", False
        exists = os.path.lexists(path)
    except OSError as e:
        return None, f"cannot use that path ({e.strerror or type(e).__name__})", False
    return path, None, exists


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
        "changes": entry.changes,
    }


def export_to_json(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    pretty: bool = True,
    overwrite: bool = True,
) -> int:
    """Export audit logs to JSON file.

    Args:
        entries: Audit log entries to export.
        output: Output file path or file object.
        pretty: Whether to format JSON with indentation.
        overwrite: When False, refuse (FileExistsError) to replace an existing file.

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

    indent = 2 if pretty else None
    if isinstance(output, Path):
        with atomic_write(output, overwrite=overwrite) as f:
            json.dump(data, f, indent=indent, default=str, ensure_ascii=False)
            f.write("\n")
    else:
        json.dump(data, output, indent=indent, default=str, ensure_ascii=False)
        output.write("\n")

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
    "changes",
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
    """Write entries as delimited text with a header row; return the entry count.

    CSV uses standard quoting. TSV is plain, with no quoting, so ``cut`` and ``awk`` can
    read it: tabs and line breaks inside a cell become spaces.
    """
    if delimiter == "\t":

        def write_row(cells: list[str]) -> None:
            f.write("\t".join(_TSV_UNSAFE.sub(" ", cell) for cell in cells) + "\n")
    else:
        write_row = csv.writer(f, delimiter=delimiter).writerow
    write_row(_EXPORT_FIELDS)
    count = 0
    for entry in entries:
        row = entry_to_dict(entry)
        if row["changes"] is not None:  # one cell: compact JSON
            row["changes"] = json.dumps(
                row["changes"], separators=(",", ":"), default=str, ensure_ascii=False
            )
        write_row([_cell(row[name]) for name in _EXPORT_FIELDS])
        count += 1
    return count


_TSV_UNSAFE = re.compile(r"[\t\r\n]")


def _export_delimited(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    delimiter: str,
    overwrite: bool = True,
) -> int:
    if isinstance(output, Path):
        with atomic_write(output, newline="", overwrite=overwrite) as f:
            return _write_delimited(entries, f, delimiter)
    return _write_delimited(entries, output, delimiter)


def export_to_csv(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    overwrite: bool = True,
) -> int:
    """Export audit logs to CSV file.

    Args:
        entries: Audit log entries to export.
        output: Output file path or file object.
        overwrite: When False, refuse (FileExistsError) to replace an existing file.

    Returns:
        Number of entries exported.
    """
    return _export_delimited(entries, output, ",", overwrite)


def export_to_tsv(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    overwrite: bool = True,
) -> int:
    """Export audit logs to TSV (tab-separated values) file.

    Args:
        entries: Audit log entries to export.
        output: Output file path or file object.
        overwrite: When False, refuse (FileExistsError) to replace an existing file.

    Returns:
        Number of entries exported.
    """
    return _export_delimited(entries, output, "\t", overwrite)


def export_entries(
    entries: list[AuditLogEntry] | Iterator[AuditLogEntry],
    output: Path | TextIO,
    output_format: str = "json",
    pretty: bool = True,
    overwrite: bool = True,
) -> int:
    """Export audit logs to a file or an open text stream in the specified format.

    Args:
        entries: Audit log entries to export.
        output: Output file path (written atomically) or a text stream.
        output_format: Output format ('json', 'csv', or 'tsv').
        pretty: For JSON, whether to pretty-print.
        overwrite: When False, refuse (FileExistsError) to replace an existing file.

    Returns:
        Number of entries exported.

    Raises:
        ValueError: If format is not supported.
    """
    output_format = output_format.lower()

    if output_format == "json":
        return export_to_json(entries, output, pretty=pretty, overwrite=overwrite)
    elif output_format == "csv":
        return export_to_csv(entries, output, overwrite)
    elif output_format == "tsv":
        return export_to_tsv(entries, output, overwrite)
    else:
        raise ValueError(
            f"Unsupported export format: {output_format}. Use 'json', 'csv', or 'tsv'."
        )
