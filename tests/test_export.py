"""Tests for export module."""

import csv
import json
import sys
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from cja_audit_log_monitor.export import (
    entry_to_dict,
    export_entries,
    export_to_csv,
    export_to_json,
    export_to_tsv,
)
from cja_audit_log_monitor.models import AuditLogEntry


class TestEntryToDict:
    """Tests for entry_to_dict function."""

    def test_conversion(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test converting entry to dict."""
        result = entry_to_dict(sample_audit_entry)

        assert result["id"] == "entry-123"
        assert result["user_email"] == "user@example.com"
        assert result["action"] == "CREATE"
        assert "timestamp" in result

    def test_none_values(self) -> None:
        """Test handling of None values."""
        entry = AuditLogEntry()
        result = entry_to_dict(entry)

        assert result["id"] is None
        assert result["timestamp"] is None

    def test_timestamp_formatting(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test timestamp is ISO formatted."""
        result = entry_to_dict(sample_audit_entry)
        assert "T" in result["timestamp"]  # ISO format has T separator


class TestExportToJson:
    """Tests for export_to_json function."""

    def test_export_to_file(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test JSON export to file."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.json"
            count = export_to_json(sample_audit_entries, output_path)

            assert count == len(sample_audit_entries)
            assert output_path.exists()

            with open(output_path) as f:
                data = json.load(f)

            assert data["count"] == len(sample_audit_entries)
            assert len(data["entries"]) == len(sample_audit_entries)

    def test_export_to_stringio(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test JSON export to StringIO."""
        output = StringIO()
        count = export_to_json([sample_audit_entry], output)

        assert count == 1
        output.seek(0)
        data = json.load(output)
        assert data["count"] == 1

    def test_pretty_print(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test pretty vs compact JSON output."""
        pretty_output = StringIO()
        compact_output = StringIO()

        export_to_json([sample_audit_entry], pretty_output, pretty=True)
        export_to_json([sample_audit_entry], compact_output, pretty=False)

        pretty_output.seek(0)
        compact_output.seek(0)

        # Pretty print should have newlines and indentation
        assert len(pretty_output.read()) > len(compact_output.read())

    def test_export_empty_list(self) -> None:
        """Test exporting empty list."""
        output = StringIO()
        count = export_to_json([], output)

        assert count == 0
        output.seek(0)
        data = json.load(output)
        assert data["count"] == 0
        assert data["entries"] == []


class TestExportToCsv:
    """Tests for export_to_csv function."""

    def test_export_to_file(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test CSV export to file."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.csv"
            count = export_to_csv(sample_audit_entries, output_path)

            assert count == len(sample_audit_entries)

            with open(output_path) as f:
                reader = csv.DictReader(f)
                rows = list(reader)

            assert len(rows) == len(sample_audit_entries)

    def test_csv_headers(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test CSV has correct headers."""
        output = StringIO()
        export_to_csv([sample_audit_entry], output)

        output.seek(0)
        reader = csv.DictReader(output)
        headers = reader.fieldnames

        assert "id" in headers
        assert "timestamp" in headers
        assert "user_email" in headers
        assert "action" in headers

    def test_export_to_stringio(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test CSV export to StringIO."""
        output = StringIO()
        count = export_to_csv([sample_audit_entry], output)

        assert count == 1


class TestExportToTsv:
    """Tests for export_to_tsv function."""

    def test_export_to_file(self, sample_audit_entries: list[AuditLogEntry]) -> None:
        """Test TSV export to file."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.tsv"
            count = export_to_tsv(sample_audit_entries, output_path)

            assert count == len(sample_audit_entries)

            with open(output_path) as f:
                reader = csv.DictReader(f, delimiter="\t")
                rows = list(reader)

            assert len(rows) == len(sample_audit_entries)

    def test_tsv_uses_tabs(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test TSV uses tab delimiters."""
        output = StringIO()
        export_to_tsv([sample_audit_entry], output)

        output.seek(0)
        content = output.read()
        assert "\t" in content

    def test_tsv_headers(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test TSV has correct headers."""
        output = StringIO()
        export_to_tsv([sample_audit_entry], output)

        output.seek(0)
        reader = csv.DictReader(output, delimiter="\t")
        headers = reader.fieldnames

        assert "id" in headers
        assert "timestamp" in headers
        assert "user_email" in headers


class TestExportEntries:
    """Tests for export_entries function."""

    def test_json_format(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test export with JSON format."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.json"
            count = export_entries([sample_audit_entry], output_path, output_format="json")
            assert count == 1

    def test_csv_format(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test export with CSV format."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.csv"
            count = export_entries([sample_audit_entry], output_path, output_format="csv")
            assert count == 1

    def test_tsv_format(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test export with TSV format."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.tsv"
            count = export_entries([sample_audit_entry], output_path, output_format="tsv")
            assert count == 1

    def test_invalid_format(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test error on invalid format."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.txt"
            with pytest.raises(ValueError) as exc_info:
                export_entries([sample_audit_entry], output_path, output_format="xml")
            assert "Unsupported" in str(exc_info.value)

    def test_format_case_insensitive(self, sample_audit_entry: AuditLogEntry) -> None:
        """Test that format is case insensitive."""
        with TemporaryDirectory() as tmpdir:
            output_path = Path(tmpdir) / "export.json"
            count = export_entries([sample_audit_entry], output_path, output_format="JSON")
            assert count == 1


class TestUserName:
    """Exports include the user's display name from the live API."""

    def _entry(self):
        return AuditLogEntry(id="1", user_id="u1", user_name="Pat Example", action="EDIT")

    def test_dict_has_user_name(self):
        assert entry_to_dict(self._entry())["user_name"] == "Pat Example"

    def test_csv_has_user_name_column(self):
        out = StringIO()
        export_to_csv([self._entry()], out)
        rows = list(csv.DictReader(StringIO(out.getvalue())))
        assert rows[0]["user_name"] == "Pat Example"

    def test_tsv_has_user_name_column(self):
        out = StringIO()
        export_to_tsv([self._entry()], out)
        rows = list(csv.DictReader(StringIO(out.getvalue()), delimiter="\t"))
        assert rows[0]["user_name"] == "Pat Example"


def _exploding(entries: list[AuditLogEntry]):
    for i, entry in enumerate(entries):
        if i == 2:
            raise RuntimeError("boom")
        yield entry


class TestAtomicWrites:
    """Exports write atomically, privately and as UTF-8."""

    @pytest.mark.parametrize("fmt", ["json", "csv", "tsv"])
    def test_failed_export_leaves_nothing(
        self, tmp_path: Path, sample_audit_entries: list[AuditLogEntry], fmt: str
    ) -> None:
        target = tmp_path / f"out.{fmt}"
        with pytest.raises(RuntimeError):
            export_entries(_exploding(sample_audit_entries), target, fmt)
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.parametrize("fmt", ["json", "csv", "tsv"])
    def test_failed_export_keeps_existing_file(
        self, tmp_path: Path, sample_audit_entries: list[AuditLogEntry], fmt: str
    ) -> None:
        target = tmp_path / f"out.{fmt}"
        target.write_text("original", encoding="utf-8")
        with pytest.raises(RuntimeError):
            export_entries(_exploding(sample_audit_entries), target, fmt)
        assert target.read_text(encoding="utf-8") == "original"
        assert [p.name for p in tmp_path.iterdir()] == [target.name]

    @pytest.mark.skipif(sys.platform == "win32", reason="symlinks need privileges on Windows")
    def test_symlink_is_replaced_not_followed(
        self, tmp_path: Path, sample_audit_entry: AuditLogEntry
    ) -> None:
        real = tmp_path / "real.json"
        real.write_text("keep", encoding="utf-8")
        link = tmp_path / "link.json"
        link.symlink_to(real)
        export_to_json([sample_audit_entry], link)
        assert real.read_text(encoding="utf-8") == "keep"
        assert not link.is_symlink()
        assert json.loads(link.read_text(encoding="utf-8"))["count"] == 1

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
    def test_new_file_is_private(
        self, tmp_path: Path, sample_audit_entry: AuditLogEntry
    ) -> None:
        target = tmp_path / "out.csv"
        export_to_csv([sample_audit_entry], target)
        assert target.stat().st_mode & 0o777 == 0o600

    def test_unicode_round_trips(self, tmp_path: Path) -> None:
        entry = AuditLogEntry(id="u1", description="✓ 日本")
        json_path = tmp_path / "u.json"
        csv_path = tmp_path / "u.csv"
        export_to_json([entry], json_path)
        export_to_csv([entry], csv_path)
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["entries"][0]["description"] == "✓ 日本"
        with open(csv_path, encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["description"] == "✓ 日本"

    def test_exported_at_is_utc(self, sample_audit_entry: AuditLogEntry) -> None:
        output = StringIO()
        export_to_json([sample_audit_entry], output)
        assert json.loads(output.getvalue())["exported_at"].endswith("+00:00")
