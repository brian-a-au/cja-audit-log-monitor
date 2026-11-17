"""Tests for export module."""

import csv
import json
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
