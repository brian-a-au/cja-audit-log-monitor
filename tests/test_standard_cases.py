"""The shared cases of the Adobe credentials standard (version 1), run against this tool.

The case files in ``tests/standard_cases/`` are copies. ``SOURCE.json`` there records where
they came from. This module is the tool's adapter: it builds each case in a temporary home
and working folder, runs the lookup or the command, and checks what the case expects.

``known-differences.json`` at the repo root lists the cases the tool does not pass. Those
must fail here, and every other case must pass. A listed case that passes fails the run,
so the list can only get shorter.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import httpx
import pytest
import yaml
from click.testing import CliRunner

from cja_audit_log_monitor import __version__
from cja_audit_log_monitor import config as config_module
from cja_audit_log_monitor.cli import main
from cja_audit_log_monitor.config import load_config_with_report
from cja_audit_log_monitor.credentials import (
    CREDENTIAL_FIELDS,
    CredentialError,
    is_valid_profile_name,
    mask_client_id,
    mask_secret,
)

ROOT = Path(__file__).resolve().parents[1]
CASES = Path(__file__).resolve().parent / "standard_cases"
KNOWN_DIFFERENCES = ROOT / "known-differences.json"

pytestmark = pytest.mark.skipif(
    not KNOWN_DIFFERENCES.exists(), reason="known-differences.json is not in this copy"
)

TOOL = "cja-audit-log-monitor"
PRODUCT = "cja"
PROFILE_VARIABLE = "CJA_PROFILE"
IMS_URL = "https://ims-na1.adobelogin.com/ims/token/v3"
API_URL = re.compile(r"https://cja\.adobe\.io/auditlogs/api/v1/auditlogs\?.*")
# The parts of the standard this tool has no command for. Each must be in not_applicable.
UNSUPPORTED = {"run_child": "L1.1", "create_profile": "L1.3"}
# Shares no run of 4 characters with a secret in fixtures.json.
OTHER_SECRET = "ZZZZZZZZZZZZZZZZ"


def _json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


FIXTURES = _json(CASES / "fixtures.json")
KNOWN = _json(KNOWN_DIFFERENCES) if KNOWN_DIFFERENCES.exists() else {"differences": []}
EXPECTED_TO_FAIL = {case for item in KNOWN["differences"] for case in item.get("cases", [])}
ALL_CASES = [
    case
    for path in sorted(CASES.glob("*.json"))
    if path.name.split(".")[0] not in ("fixtures", "SOURCE", "codes-v1")
    and not path.name.endswith(".schema.json")
    for case in _json(path)["cases"]
]


def _unsupported(case: dict[str, Any]) -> str | None:
    given = case["given"]
    return next((k for k in UNSUPPORTED if k in (given.get("command"), given.get("action"))), None)


def _applies(case: dict[str, Any]) -> bool:
    return PRODUCT in case.get("products", [PRODUCT]) and TOOL in case.get("tools", [TOOL])


def _params() -> list[Any]:
    params = []
    for case in ALL_CASES:
        marks = []
        if case["id"] in EXPECTED_TO_FAIL:
            marks.append(pytest.mark.xfail(strict=True, raises=AssertionError))
        params.append(pytest.param(case, id=case["id"], marks=marks))
    return params


# ---------------------------------------------------------------------------
# A small JSON Schema check, so the tests need no extra library. It knows the
# keywords the two output shapes use.

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "boolean": (bool,),
    "null": (type(None),),
}


def schema_problems(value: Any, schema: dict[str, Any], where: str = "$") -> list[str]:
    """Every way ``value`` breaks ``schema``; an empty list when it fits."""
    problems: list[str] = []
    if "const" in schema and value != schema["const"]:
        problems.append(f"{where}: expected {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        problems.append(f"{where}: {value!r} is not one of {schema['enum']}")
    if "type" in schema:
        names = schema["type"] if isinstance(schema["type"], list) else [schema["type"]]
        if not any(isinstance(value, _TYPES[name]) for name in names):
            problems.append(f"{where}: expected {' or '.join(names)}")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                problems.append(f"{where}: {key} is missing")
        for key in schema.get("not", {}).get("required", []):
            if key in value:
                problems.append(f"{where}: {key} must not be there")
        for key, sub in schema.get("properties", {}).items():
            if key in value:
                problems += schema_problems(value[key], sub, f"{where}.{key}")
    if isinstance(value, list) and "items" in schema:
        for index, item in enumerate(value):
            problems += schema_problems(item, schema["items"], f"{where}[{index}]")
    return problems


def assert_shape(document: Any, name: str) -> None:
    schema = _json(CASES / f"{name}.schema.json")
    assert schema_problems(document, schema) == []


class TestSchemaCheck:
    """The small check must itself reject what the shapes forbid."""

    SCHEMA = _json(CASES / "config-check-v1.schema.json")

    def _good(self) -> dict[str, Any]:
        return {
            "schema": "adobe-credentials/v1/config-check",
            "tool": TOOL,
            "tool_version": "1",
            "product": "cja",
            "ok": True,
            "profile": None,
            "sources": [{"kind": "environment", "used": True, "fields": ["org_id"]}],
            "credential": {"org_id": "o", "client_id": "c", "secret_set": True, "scopes": "s"},
            "problems": [],
            "notices": [],
        }

    def test_a_good_document_fits(self) -> None:
        assert schema_problems(self._good(), self.SCHEMA) == []

    @pytest.mark.parametrize(
        ("change", "problem"),
        [
            (lambda d: d.pop("ok"), "$: ok is missing"),
            (lambda d: d.update(schema="x"), "$.schema: expected"),
            (lambda d: d.update(product="other"), "$.product: 'other' is not one of"),
            (lambda d: d.update(profile=3), "$.profile: expected string or null"),
            (lambda d: d["credential"].update(secret="s"), "$.credential: secret must not"),
            (lambda d: d["sources"][0].update(fields=["x"]), "$.sources[0].fields[0]: 'x'"),
        ],
    )
    def test_a_bad_document_is_reported(self, change, problem: str) -> None:
        document = self._good()
        change(document)
        assert any(text.startswith(problem) for text in schema_problems(document, self.SCHEMA))


# ---------------------------------------------------------------------------
# Building a case


def _credential(spec: dict[str, Any], secret: str | None) -> dict[str, Any]:
    """The fields a source holds: the fixture, less ``omit``, with ``override``."""
    values = dict(FIXTURES["credentials"][spec["credential"]]) if "credential" in spec else {}
    if secret is not None and "secret" in values:
        values["secret"] = secret
    for name in spec.get("omit", []):
        del values[name]
    values.update(spec.get("override", {}))
    return values


def _write(path: Path, text: str, spec: dict[str, Any]) -> None:
    """Write a credential file with the mode the case gives (private when it gives none)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    target = path
    if spec.get("through_symlink"):
        target = path.with_name("real-" + path.name)
        path.unlink(missing_ok=True)
        path.symlink_to(target)
    target.write_text(text, encoding="utf-8")
    target.chmod(int(spec.get("file_mode", "0600"), 8))


def _write_profile(spec: dict[str, Any], secret: str | None) -> None:
    if "credential" in spec:
        values = {**_credential(spec, secret), **spec.get("extra_keys", {})}
        path = Path.home() / ".cja" / "orgs" / spec["name"] / "config.json"
        _write(path, json.dumps(values), spec)


class Built:
    """A case set up on disk and in the environment."""

    def __init__(self, case: dict[str, Any], monkeypatch, tmp_path: Path, secret: str | None):
        self.flags: list[str] = []
        self.profile: str | None = None
        self.config_path: Path | None = None
        sources = dict(case["given"].get("sources", {}))
        if case["given"].get("command") == "live_test" and not sources:
            sources = {"environment": {"credential": "A"}}

        work = tmp_path / "parent" / "work"
        work.mkdir(parents=True, exist_ok=True)
        monkeypatch.chdir(work)
        default_config = Path.home() / ".cja-audit-log-monitor" / "config.yaml"
        monkeypatch.delenv("CJA_CONFIG_PATH", raising=False)
        monkeypatch.setattr(config_module, "DEFAULT_CONFIG_FILE", default_config)

        for kind, spec in sources.items():
            values = _credential(spec, secret)
            if kind == "flag_profile":
                _write_profile(spec, secret)
                self.profile = spec["name"]
                self.flags += ["--profile", spec["name"]]
            elif kind == "flag_config":
                # A JSON file, to show that -c reads one.
                self.config_path = work / "given.json"
                _write(self.config_path, json.dumps(values), spec)
                self.flags += ["-c", str(self.config_path)]
            elif kind == "profile_variable":
                _write_profile(spec, secret)
                monkeypatch.setenv(PROFILE_VARIABLE, spec["name"])
            elif kind == "profile_variable_target":
                _write_profile(spec, secret)
            elif kind == "environment":
                for name, value in values.items():
                    monkeypatch.setenv(name.upper(), value)
                if spec.get("other_settings"):
                    monkeypatch.setenv("MONITOR_INTERVAL", "30")
            elif kind == "dotenv":
                lines = {name.upper(): value for name, value in values.items()}
                for name, value in spec.get("extra_keys", {}).items():
                    lines[PROFILE_VARIABLE if name == "PROFILE_VARIABLE" else name] = value
                folder = work.parent if spec.get("location") == "parent_folder" else work
                text = "".join(f'{name}="{value}"\n' for name, value in lines.items())
                _write(folder / ".env", text, spec)
            elif kind == "default_config":
                values.update(spec.get("extra_keys", {}))
                _write(default_config, yaml.safe_dump(values), spec)
            else:  # pragma: no cover - a new kind of source in the cases
                raise AssertionError(f"the adapter does not know the source {kind}")
        self.other_settings = any(spec.get("other_settings") for spec in sources.values())


# ---------------------------------------------------------------------------
# Running a case


def _lookup(built: Built) -> dict[str, Any]:
    """The lookup alone: the winning source and credential, or the error code."""
    try:
        settings, report = load_config_with_report(built.config_path, profile=built.profile)
    except CredentialError as error:
        return {"error": error.code, "missing": error.missing}
    problems = report.problems()
    if problems:
        return {"error": problems[0]["code"], "missing": []}
    assert report.winner is not None
    return {
        "source": report.winner.kind,
        "credential": {
            "org_id": settings.org_id,
            "client_id": settings.client_id,
            "secret": settings.secret.get_secret_value(),
            "scopes": settings.scopes,
        },
        "monitor_interval": settings.monitor_interval,
    }


def _run(flags: list[str], command: str) -> tuple[Any, str]:
    """Run a command as text and as JSON. Returns the JSON document and all the output."""
    text = CliRunner().invoke(main, [*flags, "cli", command])
    as_json = CliRunner().invoke(main, [*flags, "cli", command, "-F", "json"])
    assert "Unexpected error" not in text.output + as_json.output
    try:
        document = json.loads(as_json.stdout)
    except ValueError:
        document = None
    return document, text.output + as_json.output


def _stub_adobe(case: dict[str, Any], httpx_mock, monkeypatch) -> None:
    """Stand in for the sign-in service and the audit log API. Each is asked twice at most."""
    monkeypatch.setattr("cja_audit_log_monitor.client.time.sleep", lambda seconds: None)
    sign_in = case["given"]["sign_in_answer"]
    if sign_in == "connection_error":
        httpx_mock.add_exception(httpx.ConnectError("down"), url=IMS_URL, is_reusable=True)
    else:
        httpx_mock.add_response(
            url=IMS_URL, status_code=sign_in["status"], json=sign_in["body"], is_reusable=True
        )
    product = case["given"].get("product_answer")
    if product == "has_access":
        page = {"content": [], "totalElements": 12, "totalPages": 1, "number": 0, "size": 1}
        httpx_mock.add_response(url=API_URL, json=page, is_reusable=True)
    elif product == "no_access":
        body = {"errorCode": "403003", "errorDescription": "Api Key is invalid"}
        httpx_mock.add_response(url=API_URL, status_code=403, json=body, is_reusable=True)
    elif product == "connection_error":
        httpx_mock.add_exception(httpx.ConnectError("down"), url=API_URL, is_reusable=True)


def _check_step(step: dict[str, Any], expect: dict[str, Any]) -> None:
    assert step["ok"] is expect["ok"]
    assert step["code"] == expect["code"]
    if "message_contains" in expect:
        assert expect["message_contains"] in step["message"]
    if "message_excludes" in expect:
        assert expect["message_excludes"] not in step["message"]
    if "message_contains_by_product" in expect:
        assert expect["message_contains_by_product"][PRODUCT] in step["message"]


def _leaks(real: str, other: str, secret: str) -> list[str]:
    """Runs of 4 characters of ``secret`` that the output shows because of the secret.

    ``other`` is the same output with a different secret. A run that is in both comes
    from fixed text, e.g. the word "credential" in the name of the JSON shape.
    """
    runs = {secret[i : i + 4] for i in range(len(secret) - 3)}
    return sorted(run for run in runs if run in real and run not in other)


@pytest.mark.httpx_mock(assert_all_responses_were_requested=False)
@pytest.mark.parametrize("case", _params())
def test_case(case: dict[str, Any], monkeypatch, tmp_path, caplog, httpx_mock) -> None:
    if not _applies(case):
        pytest.skip("the case is for another product or tool")
    if _unsupported(case):
        pytest.skip("the tool has no such command")
    given, expect = case["given"], case["expect"]

    # Pure input and output pairs.
    if "masked" in expect:
        if "client_id" in given:
            assert mask_client_id(given["client_id"]) == expect["masked"]
        else:
            assert mask_secret(given["secret"]) == expect["masked"]
        return
    if "valid" in expect:
        assert is_valid_profile_name(given["profile_name"]) is expect["valid"]
        return

    caplog.set_level(logging.DEBUG)
    command = given.get("command")
    built = Built(case, monkeypatch, tmp_path, secret=None)

    if command is None:
        result = _lookup(built)
        if "error" in expect:
            assert result.get("error") == expect["error"]
            assert result["missing"] == expect.get("missing", result["missing"])
            return
        assert result.get("source") == expect["source"]
        assert result["credential"] == FIXTURES["credentials"][expect["credential"]]
        if built.other_settings:
            assert result["monitor_interval"] == 30
        return

    if command == "live_test":
        _stub_adobe(case, httpx_mock, monkeypatch)
        document, output = _run(built.flags, "verify")
        if expect.get("json_schema"):
            assert_shape(document, expect["json_schema"])
        for step in ("sign_in", "product_access"):
            if step in expect:
                _check_step(document[step], expect[step])
    else:
        assert command == "config_check"
        document, output = _run(built.flags, "config")
        _check_config(document, expect, caplog)

    if expect.get("output_excludes_secret"):
        secret = FIXTURES["credentials"]["A"]["secret"]
        real = output + caplog.text
        caplog.clear()
        Built(case, monkeypatch, tmp_path, secret=OTHER_SECRET)
        other = _run(built.flags, "verify" if command == "live_test" else "config")[1]
        assert _leaks(real, other + caplog.text, secret) == []


def _keys(value: Any) -> set[str]:
    """Every key in a JSON document, at any depth."""
    if isinstance(value, dict):
        return set(value) | {key for item in value.values() for key in _keys(item)}
    if isinstance(value, list):
        return {key for item in value for key in _keys(item)}
    return set()


def _check_config(document: Any, expect: dict[str, Any], caplog) -> None:
    """Check the config check JSON, and the log lines, against ``expect``."""
    assert document is not None, "the config check wrote no JSON"
    assert_shape(document, "config-check-v1")
    used = [source for source in document["sources"] if source["used"]]
    codes = [problem["code"] for problem in document["problems"]]
    notices = [notice["code"] for notice in document["notices"]]
    warnings = [
        record.getMessage()
        for record in caplog.records
        if record.levelno == logging.WARNING and "readable by other users" in record.getMessage()
    ]
    for key, wanted in expect.items():
        if key == "json_schema":
            assert_shape(document, wanted)
        elif key == "ok":
            assert document["ok"] is wanted
        elif key == "source":
            assert [source["kind"] for source in used] == [wanted]
        elif key == "profile":
            assert document["profile"] == wanted
        elif key in ("client_id", "scopes", "secret_set"):
            assert document["credential"][key] == wanted
        elif key == "has_no_secret_field":
            assert "secret" not in _keys(document)
        elif key == "skipped_source":
            skipped = [s for s in document["sources"] if s["skipped"] == "partial"]
            assert [source["kind"] for source in skipped] == [wanted]
            assert skipped[0]["missing"] == expect["missing"]
        elif key in ("problem", "error"):
            assert wanted in codes
        elif key == "notice":
            assert wanted in notices
        elif key == "notice_one_of":
            assert set(wanted) & set(notices)
        elif key == "debug":
            assert wanted == "unknown_key"
            lines = [r for r in caplog.records if "'note'" in r.getMessage()]
            assert [record.levelno for record in lines] == [logging.DEBUG]
        elif key == "profile_folder":
            folder = Path(os.path.expanduser(used[0]["path"])).parent
            assert folder == Path(os.path.expanduser(wanted))
        elif key == "warning":
            assert wanted == "file_readable_by_others"
            assert warnings
        elif key == "warning_count":
            # The command ran twice, as text and as JSON, and each run warns once.
            assert len(warnings) == wanted * 2
        elif key == "missing":
            assert "skipped_source" in expect or "notice" in expect
        elif key != "output_excludes_secret":  # pragma: no cover - a new key in the cases
            raise AssertionError(f"the adapter does not know the expectation {key}")


# ---------------------------------------------------------------------------
# known-differences.json itself


def test_known_differences_has_the_shared_shape() -> None:
    schema = _json(CASES / "known-differences-v1.schema.json")
    assert schema_problems(KNOWN, schema) == []
    assert set(KNOWN) <= set(schema["properties"])
    assert KNOWN["tool"] == TOOL
    assert KNOWN["tool_version"] == __version__, "set the new version in known-differences.json"


def test_known_differences_names_real_cases() -> None:
    assert EXPECTED_TO_FAIL <= {case["id"] for case in ALL_CASES}


def test_skipped_commands_are_listed_as_not_applicable() -> None:
    skipped = {UNSUPPORTED[kind] for case in ALL_CASES if (kind := _unsupported(case))}
    assert skipped <= {item["rule"] for item in KNOWN["not_applicable"]}


def test_the_copied_cases_match_their_record() -> None:
    import hashlib

    record = _json(CASES / "SOURCE.json")
    for name, digest in record["files"].items():
        assert hashlib.sha256((CASES / name).read_bytes()).hexdigest() == digest, name


def test_the_fields_of_the_standard_are_the_fields_of_the_tool() -> None:
    assert set(CREDENTIAL_FIELDS) == set(FIXTURES["credentials"]["A"])
