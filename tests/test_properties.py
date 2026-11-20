"""Property-based tests: hostile and unusual input must never crash these helpers."""

import csv
import io
import os
import re
from datetime import UTC, datetime

import click
import pytest
from hypothesis import HealthCheck, assume, example, given, settings
from hypothesis import strategies as st
from rich.cells import cell_len

from cja_audit_log_monitor.cli import parse_date
from cja_audit_log_monitor.export import _EXPORT_FIELDS, check_export_path, export_entries
from cja_audit_log_monitor.formatters import cut_cells, fit_cells
from cja_audit_log_monitor.models import AuditLogEntry, printable
from cja_audit_log_monitor.utils import redact_url

# Everything printable() must remove: C0 controls but tab and line feed, DEL, C1, surrogates.
_UNSAFE = re.compile("[\x00-\x08\x0b-\x1f\x7f-\x9f\ud800-\udfff]")

# Text that mixes ASCII, controls, CJK, emoji, combining marks and zero-width characters.
_TRICKY_CHARS = st.sampled_from(
    list("aZ09 =+-@'\"[]\\/~.")
    + ["\t", "\n", "\r", "\x1b", "\x00", "\x7f", "\x9b"]
    # zero-width space and joiner, emoji variation selector, combining marks, CJK, emoji
    + [chr(c) for c in (0x200B, 0x200D, 0xFE0F, 0x0301, 0x0308, 0x20DD)]
    + [chr(c) for c in (0x6F22, 0x5B57, 0xD55C, 0xFF71, 0x1F600)]
)
# Clusters of several code points: a skin tone, a flag, a family joined with ZWJ.
_CLUSTERS = st.sampled_from(
    [
        chr(0x1F44D) + chr(0x1F3FD),
        chr(0x1F1EF) + chr(0x1F1F5),
        chr(0x200D).join(chr(c) for c in (0x1F468, 0x1F469, 0x1F467)),
    ]
)
tricky_text = st.one_of(
    st.text(),
    st.text(alphabet=_TRICKY_CHARS),
    st.lists(st.one_of(_TRICKY_CHARS, _CLUSTERS)).map("".join),
)


# ---------------------------------------------------------------------------
# parse_date


@given(st.text())
@example("0001-01-01T00:00+05:00")
@example("9999-12-31T23:59-05:00")
@example("9999-12-31")
@example("٢٠٢٦-٠١-١٥")
def test_parse_date_returns_utc_or_rejects_cleanly(raw: str) -> None:
    """Any text is either a UTC datetime or a click.BadParameter, never another error."""
    for end_of_day in (False, True):
        try:
            result = parse_date(raw, end_of_day=end_of_day)
        except click.BadParameter:
            continue
        if result is not None:
            assert result.utcoffset() is not None
            assert result.utcoffset().total_seconds() == 0


@given(st.datetimes(min_value=datetime(1, 1, 2), max_value=datetime(9999, 12, 30)))
def test_parse_date_round_trips_iso(dt: datetime) -> None:
    """An ISO timestamp with Z comes back as the same instant."""
    text = dt.replace(microsecond=0).isoformat() + "Z"
    assert parse_date(text) == dt.replace(microsecond=0, tzinfo=UTC)


@given(st.dates(min_value=datetime(1, 1, 1).date()))
def test_parse_date_end_of_day_covers_the_whole_day(day) -> None:
    start = parse_date(day.isoformat())
    end = parse_date(day.isoformat(), end_of_day=True)
    assert start is not None and end is not None
    assert (end - start).total_seconds() == 86399


# ---------------------------------------------------------------------------
# printable and the entry validators


@given(tricky_text)
def test_printable_removes_every_control_character(text: str) -> None:
    out = printable(text)
    assert not _UNSAFE.search(out)
    assert "\t" not in out
    assert out.count("\n") == text.count("\n")  # line breaks are kept
    assert printable(out) == out  # idempotent


_STR_FIELDS = [
    "id",
    "userId",
    "userEmail",
    "userName",
    "action",
    "componentType",
    "componentId",
    "componentName",
    "description",
    "orgId",
    "ipAddress",
]


@given(st.dictionaries(st.sampled_from(_STR_FIELDS), tricky_text))
def test_entry_string_fields_are_always_printable(data: dict[str, str]) -> None:
    entry = AuditLogEntry.model_validate(data)
    for name, value in entry.model_dump(exclude={"timestamp", "changes"}).items():
        if value is not None:
            assert not _UNSAFE.search(value), name
            assert "\t" not in value, name


@given(
    user=st.one_of(
        st.none(),
        st.integers(),
        st.text(),
        st.lists(st.text()),
        st.dictionaries(st.text(), st.text()),
    ),
    component=st.one_of(st.none(), st.integers(), st.text(), st.dictionaries(st.text(), st.text())),
)
def test_entry_tolerates_odd_nested_shapes(user, component) -> None:
    """The live-API flattening never crashes on unexpected nested values."""
    from pydantic import ValidationError

    try:
        AuditLogEntry.model_validate({"user": user, "component": component})
    except ValidationError:
        pass


@given(
    st.datetimes(
        min_value=datetime(1, 1, 2),
        max_value=datetime(9999, 12, 30),
        timezones=st.one_of(st.none(), st.timezones()),
    )
)
def test_entry_timestamps_are_stored_in_utc(dt: datetime) -> None:
    entry = AuditLogEntry.model_validate({"dateCreated": dt})
    assert entry.timestamp is not None
    assert entry.timestamp.utcoffset().total_seconds() == 0


# ---------------------------------------------------------------------------
# CSV and TSV formula escaping

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

cell_text = st.one_of(
    tricky_text,
    st.tuples(st.sampled_from(_FORMULA_START), tricky_text).map("".join),
)


def _entries_from(values: list[str]) -> list[AuditLogEntry]:
    return [
        AuditLogEntry(
            id=v,
            user_email=v,
            user_name=v,
            action=v,
            component_name=v,
            description=v,
            changes={"k": v} if v else None,
        )
        for v in values
    ]


@given(st.lists(cell_text, min_size=1, max_size=5))
def test_csv_cells_never_start_a_formula_and_round_trip(values: list[str]) -> None:
    entries = _entries_from(values)
    buf = io.StringIO(newline="")
    export_entries(entries, buf, "csv")
    rows = list(csv.reader(io.StringIO(buf.getvalue(), newline="")))
    assert rows[0] == _EXPORT_FIELDS
    assert len(rows) == len(entries) + 1
    for entry, row in zip(entries, rows[1:], strict=True):
        assert len(row) == len(_EXPORT_FIELDS)
        for cell in row:
            assert not cell.startswith(_FORMULA_START)
        # Removing the guard apostrophe gives back the stored value.
        name = row[_EXPORT_FIELDS.index("component_name")]
        stored = entry.component_name or ""
        assert name in (stored, "'" + stored)
        if name != stored:
            assert stored.startswith(_FORMULA_START)


@given(st.lists(cell_text, min_size=1, max_size=5))
def test_tsv_rows_stay_one_line_with_fixed_columns(values: list[str]) -> None:
    entries = _entries_from(values)
    buf = io.StringIO(newline="")
    export_entries(entries, buf, "tsv")
    lines = buf.getvalue().split("\n")
    assert lines[-1] == ""
    lines = lines[:-1]
    assert len(lines) == len(entries) + 1
    for line in lines:
        assert "\r" not in line
        cells = line.split("\t")
        assert len(cells) == len(_EXPORT_FIELDS)
        for cell in cells:
            assert not cell.startswith(_FORMULA_START)


# ---------------------------------------------------------------------------
# redact_url

_hosts = st.from_regex(r"\A[a-z0-9]([a-z0-9-]{0,20}[a-z0-9])?(\.[a-z0-9]{1,10}){0,3}\Z")
_secret = st.text(alphabet="ABCDEFGHJKMNPQRSTUVWXYZ23456789", min_size=8, max_size=20)


@given(
    scheme=st.sampled_from(["http", "https"]),
    host=_hosts,
    port=st.one_of(st.none(), st.integers(1, 65535)),
    user=st.one_of(st.none(), _secret),
    path=_secret,
    query=st.one_of(st.none(), _secret),
    fragment=st.one_of(st.none(), _secret),
)
def test_redact_url_keeps_only_scheme_host_and_port(
    scheme, host, port, user, path, query, fragment
) -> None:
    assume(not any(s and s.lower() in host for s in (user, path, query, fragment)))
    url = f"{scheme}://"
    if user:
        url += f"{user}:{user}@"
    url += host + (f":{port}" if port else "") + "/" + path
    if query:
        url += f"?token={query}"
    if fragment:
        url += f"#{fragment}"
    out = redact_url(url)
    assert out == f"{scheme}://{host}{f':{port}' if port else ''}/…"
    for secret in (user, path, query, fragment):
        if secret:
            assert secret not in out


@given(tricky_text)
@example("http://ho\x1bst/x")
@example("https://[::1")
@example("https://h:99999/")
def test_redact_url_never_raises_and_is_printable(url: str) -> None:
    out = redact_url(url)
    assert out == "<invalid url>" or out.endswith("/…")
    assert not _UNSAFE.search(out)


# ---------------------------------------------------------------------------
# fit_cells and cut_cells


@given(tricky_text, st.integers(-3, 60))
def test_cut_cells_fits_the_width(text: str, width: int) -> None:
    out = cut_cells(text, width)
    if width < 1:
        assert out == ""
        return
    assert cell_len(out) <= width
    if cell_len(text) <= width:
        assert out == text
    else:
        assert out.endswith("…")


@given(tricky_text, st.integers(1, 60))
def test_fit_cells_is_exactly_the_width(text: str, width: int) -> None:
    assert cell_len(fit_cells(text, width)) == width


# ---------------------------------------------------------------------------
# check_export_path


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(
    st.one_of(
        st.text(),
        st.text(alphabet=_TRICKY_CHARS),
        st.tuples(st.sampled_from(["", "~", "~/", "./", "/", "~nouser-x/"]), st.text()).map(
            "".join
        ),
    )
)
@example("a\x00b")
@example("~\x00")
@example("~\ud800/x")
@example("x\ud800")
@example("~/\udcff")
@example("/dev/null")
def test_check_export_path_never_raises(tmp_path, monkeypatch, raw: str) -> None:
    monkeypatch.chdir(tmp_path)
    path, problem, exists = check_export_path(raw)
    assert (path is None) == (problem is not None)
    if path is not None:
        # A usable path really can be opened by the OS layer.
        os.fsencode(path)
        assert "\x00" not in str(path)
        assert not exists or os.path.lexists(path)


@pytest.mark.parametrize("raw", ["a\x00b", "x\ud800", "ok\ud800/name"])
def test_check_export_path_rejects_names_the_os_cannot_take(tmp_path, monkeypatch, raw) -> None:
    monkeypatch.chdir(tmp_path)
    path, problem, _ = check_export_path(raw)
    assert path is None
    assert problem
