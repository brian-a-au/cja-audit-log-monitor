"""Tests for export module."""

import csv
import json
import os
import sys
from datetime import UTC, datetime
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
    def test_new_file_is_private(self, tmp_path: Path, sample_audit_entry: AuditLogEntry) -> None:
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


class TestFormulaInjection:
    """CSV and TSV cells that start like a spreadsheet formula are prefixed with '."""

    @staticmethod
    def _entry(component_name: str, description: str = "d") -> AuditLogEntry:
        return AuditLogEntry(
            id="e1",
            timestamp=datetime(2024, 1, 15, 10, 30, 0, tzinfo=UTC),
            action="UPDATE",
            component_name=component_name,
            description=description,
        )

    @pytest.mark.parametrize(("fn", "delimiter"), [(export_to_csv, ","), (export_to_tsv, "\t")])
    def test_formula_cell_is_prefixed(self, fn, delimiter) -> None:
        out = StringIO()
        fn([self._entry('=HYPERLINK("http://x")')], out)
        rows = list(csv.DictReader(StringIO(out.getvalue()), delimiter=delimiter))
        assert rows[0]["component_name"] == '\'=HYPERLINK("http://x")'

    @pytest.mark.parametrize(("fn", "delimiter"), [(export_to_csv, ","), (export_to_tsv, "\t")])
    def test_negative_looking_value_is_prefixed(self, fn, delimiter) -> None:
        out = StringIO()
        fn([self._entry("-5", "@cmd")], out)
        rows = list(csv.DictReader(StringIO(out.getvalue()), delimiter=delimiter))
        assert rows[0]["component_name"] == "'-5"
        assert rows[0]["description"] == "'@cmd"

    def test_timestamp_and_plain_text_unchanged(self) -> None:
        out = StringIO()
        export_to_csv([self._entry("Plain")], out)
        rows = list(csv.DictReader(StringIO(out.getvalue())))
        assert rows[0]["timestamp"].startswith("2024-01-15")
        assert rows[0]["component_name"] == "Plain"


class TestAtomicWrite:
    """atomic_write leaves nothing behind and never damages an existing file."""

    @staticmethod
    def _only(path: Path) -> list[str]:
        return sorted(p.name for p in path.parent.iterdir())

    def test_error_in_body_keeps_original_and_removes_temp(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import atomic_write

        target = tmp_path / "out.txt"
        target.write_text("old")
        with pytest.raises(RuntimeError, match="boom"):
            with atomic_write(target) as f:
                f.write("partial")
                raise RuntimeError("boom")
        assert target.read_text() == "old"
        assert self._only(target) == ["out.txt"]

    def test_failed_replace_keeps_original_and_removes_temp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cja_audit_log_monitor.export import atomic_write

        target = tmp_path / "out.txt"
        target.write_text("old")

        def broken_replace(src, dst):
            raise OSError("replace failed")

        monkeypatch.setattr("cja_audit_log_monitor.export.os.replace", broken_replace)
        with pytest.raises(OSError, match="replace failed"):
            with atomic_write(target) as f:
                f.write("new")
        assert target.read_text() == "old"
        assert self._only(target) == ["out.txt"]

    def test_keyboard_interrupt_cleans_up(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import atomic_write

        target = tmp_path / "out.txt"
        target.write_text("old")
        with pytest.raises(KeyboardInterrupt):
            with atomic_write(target) as f:
                f.write("partial")
                raise KeyboardInterrupt
        assert target.read_text() == "old"
        assert self._only(target) == ["out.txt"]

    def test_cleanup_failure_keeps_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cja_audit_log_monitor.export import atomic_write

        def broken_unlink(name):
            raise PermissionError("cannot unlink")

        monkeypatch.setattr("cja_audit_log_monitor.export.os.unlink", broken_unlink)
        with pytest.raises(RuntimeError, match="boom"):
            with atomic_write(tmp_path / "out.txt") as f:
                f.write("x")
                raise RuntimeError("boom")

    def test_no_overwrite_refuses_existing_file(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import atomic_write

        target = tmp_path / "out.txt"
        target.write_text("old")
        with pytest.raises(FileExistsError):
            with atomic_write(target, overwrite=False) as f:
                f.write("new")
        assert target.read_text() == "old"
        assert self._only(target) == ["out.txt"]

    def test_no_overwrite_creates_new_file(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import atomic_write

        target = tmp_path / "out.txt"
        with atomic_write(target, overwrite=False) as f:
            f.write("new")
        assert target.read_text() == "new"
        assert self._only(target) == ["out.txt"]

    def test_no_overwrite_falls_back_when_links_unsupported(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from cja_audit_log_monitor.export import atomic_write

        def no_links(src, dst):
            raise OSError("links not supported")

        monkeypatch.setattr("cja_audit_log_monitor.export.os.link", no_links)
        target = tmp_path / "out.txt"
        with atomic_write(target, overwrite=False) as f:
            f.write("new")
        assert target.read_text() == "new"
        target.write_text("old")
        with pytest.raises(FileExistsError):
            with atomic_write(target, overwrite=False) as f:
                f.write("new")
        assert target.read_text() == "old"
        assert self._only(target) == ["out.txt"]

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere"
    )
    def test_unwritable_folder_error_names_the_target(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import atomic_write

        folder = tmp_path / "locked"
        folder.mkdir()
        folder.chmod(0o500)
        try:
            with pytest.raises(PermissionError) as info:
                with atomic_write(folder / "out.json") as f:
                    f.write("x")
        finally:
            folder.chmod(0o700)
        assert "out.json" in str(info.value)
        assert ".tmp" not in str(info.value)
        assert info.value.errno is not None


class TestExportOverwriteFlag:
    def test_export_entries_overwrite_false_refuses_existing(
        self, sample_audit_entries: list[AuditLogEntry], tmp_path: Path
    ) -> None:
        target = tmp_path / "out.csv"
        target.write_text("old")
        with pytest.raises(FileExistsError):
            export_entries(sample_audit_entries, target, "csv", overwrite=False)
        assert target.read_text() == "old"

    @pytest.mark.parametrize("fmt", ["json", "csv", "tsv"])
    def test_export_entries_default_replaces(
        self, sample_audit_entries: list[AuditLogEntry], tmp_path: Path, fmt: str
    ) -> None:
        target = tmp_path / f"out.{fmt}"
        target.write_text("old")
        export_entries(sample_audit_entries, target, fmt)
        assert target.read_text() != "old"


class TestCellGuard:
    @pytest.mark.parametrize("prefix", ["=", "+", "-", "@", "\t", "\r"])
    def test_cell_prefixes_formula_starts(self, prefix: str) -> None:
        from cja_audit_log_monitor.export import _cell

        assert _cell(f"{prefix}SUM(A1)") == f"'{prefix}SUM(A1)"

    def test_cell_leaves_plain_text_and_none(self) -> None:
        from cja_audit_log_monitor.export import _cell

        assert _cell("hello") == "hello"
        assert _cell(None) == ""

    def test_header_row_is_not_prefixed(self, sample_audit_entry: AuditLogEntry) -> None:
        out = StringIO()
        export_to_csv([sample_audit_entry], out)
        assert out.getvalue().splitlines()[0].startswith("id,timestamp,user_id")


class TestStreamOutput:
    def test_json_stream_ends_with_newline(self, sample_audit_entry: AuditLogEntry) -> None:
        out = StringIO()
        export_to_json([sample_audit_entry], out)
        assert out.getvalue().endswith("}\n")

    def test_tsv_to_stream_via_export_entries(self, sample_audit_entry: AuditLogEntry) -> None:
        out = StringIO()
        count = export_entries([sample_audit_entry], out, "tsv")
        assert count == 1
        assert out.getvalue().splitlines()[0].startswith("id\ttimestamp")


class TestCheckExportPath:
    """One path check for the CLI and the dialog; it never raises (G22, G25, G44)."""

    def test_good_path(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import check_export_path

        path, problem, exists = check_export_path(str(tmp_path / "out.json"))
        assert (path, problem, exists) == (tmp_path / "out.json", None, False)

    @pytest.mark.parametrize("raw", ["~backup.json", "~no-such-user-zz/x.json", "~.json"])
    def test_unknown_home_folder(self, raw: str) -> None:
        from cja_audit_log_monitor.export import check_export_path

        path, problem, _ = check_export_path(raw)
        assert path is None and problem

    def test_trailing_slash_is_a_folder(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import check_export_path

        _, problem, _ = check_export_path(str(tmp_path / "newfolder") + "/")
        assert problem == "that path is a folder, not a file"

    def test_dangling_symlink_counts_as_existing(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import check_export_path

        link = tmp_path / "out.json"
        link.symlink_to(tmp_path / "gone.json")
        _, problem, exists = check_export_path(str(link))
        assert problem is None and exists is True

    @pytest.mark.skipif(
        hasattr(os, "geteuid") and os.geteuid() == 0, reason="root can write anywhere"
    )
    def test_unwritable_folder(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import check_export_path

        folder = tmp_path / "locked"
        folder.mkdir()
        folder.chmod(0o500)
        try:
            _, problem, _ = check_export_path(str(folder / "out.json"))
        finally:
            folder.chmod(0o700)
        assert problem and "cannot write" in problem

    def test_name_too_long(self, tmp_path: Path) -> None:
        from cja_audit_log_monitor.export import check_export_path

        _, problem, _ = check_export_path(str(tmp_path / ("x" * 300 + ".json")))
        assert problem == "the file name is too long"


class TestChangesInExports:
    """The `changes` field is in every format (G26)."""

    ENTRY = AuditLogEntry(
        id="c1",
        action="EDIT",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        changes={"name": {"old": "a", "new": "=b"}},
    )

    def test_json_has_changes(self) -> None:
        out = StringIO()
        export_entries([self.ENTRY], out, output_format="json")
        assert json.loads(out.getvalue())["entries"][0]["changes"] == self.ENTRY.changes

    @pytest.mark.parametrize(("fmt", "sep"), [("csv", ","), ("tsv", "\t")])
    def test_delimited_has_a_changes_column(self, fmt: str, sep: str) -> None:
        out = StringIO()
        export_entries([self.ENTRY], out, output_format=fmt)
        rows = list(csv.reader(StringIO(out.getvalue()), delimiter=sep))
        assert rows[0][-1] == "changes"
        assert json.loads(rows[1][-1]) == self.ENTRY.changes

    def test_no_changes_is_an_empty_cell(self) -> None:
        out = StringIO()
        export_entries([self.ENTRY.model_copy(update={"changes": None})], out, output_format="csv")
        rows = list(csv.reader(StringIO(out.getvalue())))
        assert rows[1][-1] == ""


class TestExportDetails:
    """Plain TSV, UTF-8 JSON, long names (G44)."""

    ENTRY = AuditLogEntry(
        id="d1",
        action="EDIT",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        component_name='日本 "quoted"\tname\nline two',
        user_email="u@example.com",
    )

    def test_tsv_is_plain(self) -> None:
        out = StringIO()
        export_entries([self.ENTRY], out, output_format="tsv")
        lines = out.getvalue().splitlines()
        assert len(lines) == 2  # no line break inside a cell
        cells = lines[1].split("\t")
        assert len(cells) == len(lines[0].split("\t"))
        assert '日本 "quoted" name line two' in cells

    def test_json_file_keeps_utf8_and_ends_with_a_newline(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        export_entries([self.ENTRY], target, output_format="json")
        text = target.read_text(encoding="utf-8")
        assert "日本" in text
        assert text.endswith("\n")

    @pytest.mark.parametrize("length", [242, 255])
    def test_long_file_name(self, tmp_path: Path, length: int) -> None:
        target = tmp_path / ("x" * (length - 5) + ".json")
        export_entries([self.ENTRY], target, output_format="json")
        assert target.exists()
        assert [p.name for p in tmp_path.iterdir()] == [target.name]
