"""The credential lookup: one source wins whole, in the order of the standard."""

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from cja_audit_log_monitor import __version__, cli
from cja_audit_log_monitor.cli import main
from cja_audit_log_monitor.config import ConfigError, load_config, load_config_with_report
from cja_audit_log_monitor.credentials import (
    NO_CREDENTIAL,
    CredentialError,
    Source,
    mask_client_id,
    mask_secret,
    profile_path,
)
from cja_audit_log_monitor.tui.app import CJAAuditApp
from cja_audit_log_monitor.tui.state import AppState

from .test_standard_cases import assert_shape

A = {
    "org_id": "A1B2C3D4E5F6A7B8C9D0E1F2@AdobeOrg",
    "client_id": "aaaa1111bbbb2222cccc3333dddd4444",
    "secret": "fake-secret-A-not-a-credential-0001",
    "scopes": "openid,AdobeID,additional_info.projectedProductContext",
}
B = {
    "org_id": "B9B8B7B6B5B4B3B2B1B0BABB@AdobeOrg",
    "client_id": "bbbb5555cccc6666dddd7777eeee8888",
    "secret": "fake-secret-B-not-a-credential-0002",
    "scopes": "openid,AdobeID,read_organizations",
}
IMS = "https://ims-na1.adobelogin.com/ims/token/v3"


def write_profile(name: str, values: dict, mode: int = 0o600) -> Path:
    path = Path.home() / ".cja" / "orgs" / name / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values) if isinstance(values, dict) else values)
    path.chmod(mode)
    return path


def set_env(monkeypatch, values: dict) -> None:
    for name, value in values.items():
        monkeypatch.setenv(name.upper(), value)


def write_dotenv(values: dict, mode: int = 0o600) -> Path:
    path = Path(".env")
    path.write_text("".join(f"{name.upper()}={value}\n" for name, value in values.items()))
    path.chmod(mode)
    return path


def write_config(path: Path, values: dict) -> Path:
    path.write_text(json.dumps(values))
    path.chmod(0o600)
    return path


def credential(settings) -> dict:
    return {
        "org_id": settings.org_id,
        "client_id": settings.client_id,
        "secret": settings.secret.get_secret_value(),
        "scopes": settings.scopes,
    }


class TestMasks:
    def test_client_id(self) -> None:
        assert mask_client_id("aaaa1111bbbb2222cccc3333dddd4444") == "aaaa****4444"
        assert mask_client_id("abcdefghi") == "abcd****fghi"
        assert mask_client_id("abcdefgh") == "****"
        assert mask_client_id("") == "(not set)"

    def test_secret_never_shows_its_length(self) -> None:
        assert mask_secret("abc") == mask_secret("a" * 40) == "****"
        assert mask_secret("") == "(not set)"

    def test_a_source_does_not_show_its_values(self) -> None:
        assert "fake-secret" not in repr(Source(kind="environment", name="x", values=A))


class TestLookupOrder:
    """Highest first: --profile or -c, CJA_PROFILE, environment, .env, default config."""

    def test_nothing_set_is_no_error_and_no_credential(self) -> None:
        settings, report = load_config_with_report()
        assert report.winner is None and report.sources == []
        assert credential(settings) == dict.fromkeys(A, "")
        assert report.problems() == [{"code": "no_credential", "message": NO_CREDENTIAL}]

    def test_the_default_config_file_is_the_last_place(self, tmp_path) -> None:
        write_config(tmp_path / "config.yaml", A)
        settings, report = load_config_with_report()
        assert report.winner.kind == "default_config"
        assert credential(settings) == A

    def test_dotenv_beats_the_default_config_file(self, tmp_path) -> None:
        write_config(tmp_path / "config.yaml", B)
        write_dotenv(A)
        settings, report = load_config_with_report()
        assert [(s.kind, s.used, s.skipped) for s in report.sources] == [
            ("dotenv", True, None),
            ("default_config", False, "lower_priority"),
        ]
        assert credential(settings) == A

    def test_environment_beats_dotenv(self, tmp_path, monkeypatch) -> None:
        write_dotenv(B)
        set_env(monkeypatch, A)
        settings, report = load_config_with_report()
        assert report.winner.kind == "environment"
        assert credential(settings) == A

    def test_environment_names_can_be_lower_case(self, monkeypatch) -> None:
        for name, value in A.items():
            monkeypatch.setenv(name, value)
        assert credential(load_config()) == A

    def test_the_profile_variable_beats_the_environment(self, monkeypatch) -> None:
        path = write_profile("prod", A)
        set_env(monkeypatch, B)
        monkeypatch.setenv("CJA_PROFILE", "prod")
        settings, report = load_config_with_report()
        winner = report.winner
        assert (winner.kind, winner.profile, winner.path) == ("profile_variable", "prod", path)
        assert credential(settings) == A

    def test_an_empty_profile_variable_is_not_set(self, monkeypatch) -> None:
        set_env(monkeypatch, B)
        monkeypatch.setenv("CJA_PROFILE", "")
        assert credential(load_config()) == B

    def test_the_profile_flag_beats_everything(self, tmp_path, monkeypatch) -> None:
        write_profile("prod", A)
        write_profile("other", B)
        monkeypatch.setenv("CJA_PROFILE", "other")
        set_env(monkeypatch, B)
        write_dotenv(B)
        write_config(tmp_path / "config.yaml", B)
        settings, report = load_config_with_report(profile="prod")
        assert [s.kind for s in report.sources] == [
            "flag_profile",
            "environment",
            "dotenv",
            "default_config",
        ]
        assert credential(settings) == A

    def test_the_config_flag_beats_the_environment(self, tmp_path, monkeypatch) -> None:
        path = write_config(tmp_path / "given.json", A)
        monkeypatch.setenv("CJA_PROFILE", "missing")
        set_env(monkeypatch, B)
        settings, report = load_config_with_report(path)
        assert report.winner.kind == "flag_config"
        assert credential(settings) == A

    def test_a_config_flag_file_without_a_credential_gives_way(self, tmp_path, monkeypatch):
        path = write_config(tmp_path / "given.yaml", {"monitor_interval": 30})
        set_env(monkeypatch, A)
        settings, report = load_config_with_report(path)
        assert report.winner.kind == "environment"
        assert credential(settings) == A
        assert settings.monitor_interval == 30

    def test_other_settings_still_come_from_other_sources(self, tmp_path, monkeypatch) -> None:
        write_profile("prod", A)
        write_config(tmp_path / "config.yaml", {**B, "default_days": 3, "monitor_interval": 30})
        monkeypatch.setenv("MONITOR_INTERVAL", "45")
        settings = load_config(profile="prod")
        assert credential(settings) == A
        assert (settings.default_days, settings.monitor_interval) == (3, 45)

    def test_dotenv_is_not_loaded_into_the_environment(self, monkeypatch) -> None:
        write_profile("other", B)
        write_dotenv({**A, "CJA_PROFILE": "other"})
        settings, report = load_config_with_report()
        assert report.winner.kind == "dotenv"
        assert credential(settings) == A

    def test_dotenv_in_a_parent_folder_is_not_read(self, tmp_path, monkeypatch) -> None:
        write_dotenv(A)
        (tmp_path / "sub").mkdir()
        monkeypatch.chdir(tmp_path / "sub")
        assert load_config_with_report()[1].winner is None


class TestOneSourceWinsWhole:
    def test_a_partial_environment_is_an_error(self, tmp_path, monkeypatch) -> None:
        write_config(tmp_path / "config.yaml", B)
        set_env(monkeypatch, {k: v for k, v in A.items() if k != "secret"})
        with pytest.raises(CredentialError) as info:
            load_config()
        assert (info.value.code, info.value.missing) == ("partial_source", ["secret"])
        assert "environment variables" in str(info.value) and "Missing: SECRET." in str(info.value)
        source = info.value.report.sources[0]
        assert (source.used, source.skipped) == (False, "partial")

    def test_no_built_in_scopes(self, tmp_path) -> None:
        path = write_config(tmp_path / "config.yaml", {k: v for k, v in A.items() if k != "scopes"})
        with pytest.raises(CredentialError) as info:
            load_config()
        assert info.value.missing == ["scopes"]
        assert f"config file {path}" in str(info.value).replace("~", str(Path.home()))
        assert "Missing: scopes." in str(info.value)

    def test_an_empty_value_counts_as_missing(self, monkeypatch) -> None:
        set_env(monkeypatch, {**A, "scopes": ""})
        with pytest.raises(CredentialError) as info:
            load_config()
        assert info.value.missing == ["scopes"]

    def test_a_partial_dotenv_is_an_error(self) -> None:
        write_dotenv({"org_id": A["org_id"]})
        with pytest.raises(CredentialError) as info:
            load_config()
        assert info.value.missing == ["client_id", "secret", "scopes"]
        assert ".env file" in str(info.value)

    def test_a_partial_config_flag_file_is_an_error(self, tmp_path, monkeypatch) -> None:
        set_env(monkeypatch, B)
        path = write_config(tmp_path / "given.yaml", {"client_id": "x"})
        with pytest.raises(CredentialError, match="Missing: org_id, secret, scopes"):
            load_config(path)

    def test_a_partial_profile_is_an_error_with_no_fall_back(self, monkeypatch) -> None:
        write_profile("prod", {})
        set_env(monkeypatch, B)
        with pytest.raises(CredentialError) as info:
            load_config(profile="prod")
        assert info.value.missing == list(A)
        assert "profile prod" in str(info.value)

    def test_the_error_never_holds_a_value(self, monkeypatch) -> None:
        set_env(monkeypatch, {k: v for k, v in A.items() if k != "scopes"})
        with pytest.raises(CredentialError) as info:
            load_config()
        text = str(info.value) + repr(info.value.report)
        assert A["secret"] not in text and A["client_id"] not in text


class TestProfiles:
    def test_profile_and_config_together_are_an_error(self, tmp_path) -> None:
        write_profile("prod", A)
        with pytest.raises(CredentialError) as info:
            load_config(tmp_path / "given.yaml", profile="prod")
        assert info.value.code == "profile_and_config_both_given"

    def test_a_missing_profile_is_an_error_with_no_fall_back(self, monkeypatch) -> None:
        set_env(monkeypatch, B)
        with pytest.raises(CredentialError) as info:
            load_config(profile="missing")
        assert info.value.code == "profile_not_found"
        assert "~/.cja/orgs/missing/config.json does not exist" in str(info.value)

    def test_a_missing_profile_in_the_variable_is_an_error(self, monkeypatch) -> None:
        set_env(monkeypatch, B)
        monkeypatch.setenv("CJA_PROFILE", "missing")
        with pytest.raises(CredentialError) as info:
            load_config()
        assert info.value.code == "profile_not_found"

    @pytest.mark.parametrize("name", ["../other", "..", ".hidden", "a/b", "a\\b", "", "a" * 65])
    def test_an_invalid_name_is_rejected_before_a_path_is_built(self, name: str) -> None:
        with pytest.raises(CredentialError) as info:
            profile_path(name)
        assert info.value.code == "invalid_profile_name"
        with pytest.raises(CredentialError):
            load_config(profile=name)

    def test_the_profile_file_is_never_written(self) -> None:
        path = write_profile("prod", A)
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        load_config(profile="prod")
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
        assert sorted(p.name for p in path.parent.iterdir()) == ["config.json"]

    def test_unknown_upper_case_and_sandbox_keys(self, caplog) -> None:
        write_profile("prod", {**A, "ORG_ID": "x", "note": "y", "sandbox": "dev"})
        with caplog.at_level(logging.DEBUG):
            settings, report = load_config_with_report(profile="prod")
        assert credential(settings) == A
        by_level = {r.levelno: r.getMessage() for r in caplog.records if "config.json" in r.message}
        assert "'ORG_ID' is in upper case and was not read" in by_level[logging.WARNING]
        assert "ignoring unknown key 'note'" in by_level[logging.DEBUG]
        assert "sandbox" not in caplog.text
        assert report.sources[0].as_json()["fields"] == [*A, "sandbox"]

    @pytest.mark.parametrize(
        ("content", "problem"),
        [("{not json", "not valid JSON"), ("[1]", "expected a JSON object at the top level")],
    )
    def test_a_profile_that_cannot_be_parsed_names_the_file(self, content, problem) -> None:
        path = write_profile("prod", content)
        with pytest.raises(ConfigError) as info:
            load_config(profile="prod")
        assert str(info.value) == f"{path}: {problem}"
        assert info.value.summary == f"config.json: {problem}"

    def test_a_profile_that_cannot_be_read_names_the_file(self) -> None:
        import os

        path = write_profile("prod", A, mode=0)
        if os.access(path, os.R_OK):
            pytest.skip("running as a user who can read any file")
        with pytest.raises(ConfigError, match=r"config\.json: cannot be read"):
            load_config(profile="prod")

    def test_an_invalid_value_names_the_profile_file_and_hides_the_value(self) -> None:
        path = write_profile("prod", {**A, "org_id": "not-an-org"})
        with pytest.raises(ConfigError) as info:
            load_config(profile="prod")
        assert str(info.value).startswith(f"{path}: org_id: ")
        assert "not-an-org" not in str(info.value)

    def test_an_invalid_value_in_dotenv_is_named_as_before(self) -> None:
        write_dotenv({**A, "org_id": "not-an-org"})
        with pytest.raises(ConfigError, match=r"^environment or \.env: org_id: "):
            load_config()


@pytest.mark.skipif("sys.platform == 'win32'")
class TestFilesReadableByOthers:
    def _warnings(self, caplog) -> list[str]:
        return [r.getMessage() for r in caplog.records if "readable by other users" in r.message]

    def test_a_profile_gives_one_warning(self, caplog) -> None:
        write_profile("prod", A, mode=0o644)
        load_config(profile="prod")
        assert self._warnings(caplog) == [
            "~/.cja/orgs/prod/config.json is readable by other users (mode 644); "
            "run: chmod 600 ~/.cja/orgs/prod/config.json"
        ]

    def test_a_dotenv_with_a_credential_gives_one_warning(self, caplog) -> None:
        write_dotenv(A, mode=0o640)
        load_config()
        assert len(self._warnings(caplog)) == 1

    def test_a_dotenv_without_a_credential_gives_none(self, caplog) -> None:
        write_dotenv({"monitor_interval": "30"}, mode=0o644)
        assert load_config().monitor_interval == 30
        assert self._warnings(caplog) == []

    def test_private_files_give_none(self, caplog) -> None:
        write_profile("prod", A)
        write_dotenv(B)
        load_config(profile="prod")
        assert self._warnings(caplog) == []


class TestConfigCommand:
    def test_text_shows_the_source_and_masks_the_credential(self, tmp_path) -> None:
        path = write_profile("prod", A)
        write_dotenv(B)
        result = CliRunner().invoke(main, ["--profile", "prod", "cli", "config"])
        assert result.exit_code == 0, result.output
        shown = str(path).replace(str(Path.home()), "~")
        assert f"Credential source: profile prod ({shown})" in result.stdout
        assert "Client ID: aaaa****4444" in result.stdout
        assert "Secret: ****" in result.stdout
        assert f"Scopes: {A['scopes']}" in result.stdout
        assert "Not used: .env file (a higher source gave the credential)" in result.stdout
        assert A["secret"] not in result.output and A["client_id"] not in result.output

    def test_text_with_no_credential_exits_0_and_says_how_to_give_one(self) -> None:
        result = CliRunner().invoke(main, ["cli", "config"])
        assert result.exit_code == 0
        assert "Credential source: (none)" in result.stdout
        assert "Secret: (not set)" in result.stdout and "Scopes: (not set)" in result.stdout
        assert "No credential was found." in result.stderr

    def test_text_reports_a_lookup_error_on_stderr(self) -> None:
        result = CliRunner().invoke(main, ["--profile", "missing", "cli", "config"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Configuration error: profile 'missing' was not found" in result.stderr

    def test_json_has_the_shared_shape(self, monkeypatch) -> None:
        set_env(monkeypatch, A)
        write_dotenv(B)
        result = CliRunner().invoke(main, ["cli", "config", "-F", "json"])
        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert_shape(document, "config-check-v1")
        assert document == {
            "schema": "adobe-credentials/v1/config-check",
            "tool": "cja-audit-log-monitor",
            "tool_version": __version__,
            "product": "cja",
            "ok": True,
            "profile": None,
            "sources": [
                {
                    "kind": "environment",
                    "name": "environment variables",
                    "path": None,
                    "used": True,
                    "fields": list(A),
                    "skipped": None,
                },
                {
                    "kind": "dotenv",
                    "name": ".env file",
                    "path": str(Path(".env").absolute()).replace(str(Path.home()), "~"),
                    "used": False,
                    "fields": list(A),
                    "skipped": "lower_priority",
                },
            ],
            "credential": {
                "org_id": A["org_id"],
                "client_id": "aaaa****4444",
                "secret_set": True,
                "scopes": A["scopes"],
            },
            "problems": [],
            "notices": [],
        }

    def test_json_with_no_credential(self) -> None:
        result = CliRunner().invoke(main, ["cli", "config", "-F", "json"])
        assert result.exit_code == 0
        document = json.loads(result.stdout)
        assert_shape(document, "config-check-v1")
        assert document["ok"] is False
        assert document["credential"] == {
            "org_id": None,
            "client_id": None,
            "secret_set": False,
            "scopes": None,
        }
        assert [p["code"] for p in document["problems"]] == ["no_credential"]

    def test_json_reports_a_partial_source_and_exits_1(self, monkeypatch) -> None:
        set_env(monkeypatch, {k: v for k, v in A.items() if k != "scopes"})
        result = CliRunner().invoke(main, ["cli", "config", "-F", "json"])
        assert result.exit_code == 1
        document = json.loads(result.stdout)
        assert_shape(document, "config-check-v1")
        assert document["ok"] is False
        assert document["sources"][0]["skipped"] == "partial"
        assert document["sources"][0]["missing"] == ["scopes"]
        assert document["problems"][0]["code"] == "partial_source"
        assert document["problems"][0]["missing"] == ["scopes"]
        assert A["secret"] not in result.output

    @pytest.mark.parametrize(
        ("flags", "code"),
        [
            (["--profile", "../x"], "invalid_profile_name"),
            (["--profile", "missing"], "profile_not_found"),
            (["--profile", "prod", "-c", "c.yaml"], "profile_and_config_both_given"),
        ],
    )
    def test_json_reports_profile_errors(self, flags: list[str], code: str) -> None:
        result = CliRunner().invoke(main, [*flags, "cli", "config", "-F", "json"])
        assert result.exit_code == 1
        document = json.loads(result.stdout)
        assert_shape(document, "config-check-v1")
        assert [p["code"] for p in document["problems"]] == [code]

    def test_a_broken_file_is_a_configuration_error_in_json_mode_too(self) -> None:
        write_profile("prod", "{")
        result = CliRunner().invoke(main, ["--profile", "prod", "cli", "config", "-F", "json"])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Configuration error:" in result.stderr and "not valid JSON" in result.stderr


def _token(httpx_mock) -> None:
    httpx_mock.add_response(url=IMS, json={"access_token": "stub-token", "expires_in": 86399})


API = "https://cja.adobe.io/auditlogs/api/v1/auditlogs?pageNumber=0&pageSize=1"
PAGE = {"content": [], "totalElements": 12, "totalPages": 1, "number": 0, "size": 1}


class TestVerifyCommand:
    """The live test reports sign-in and the log fetch separately."""

    def test_json_has_the_shared_shape(self, monkeypatch, httpx_mock) -> None:
        set_env(monkeypatch, A)
        _token(httpx_mock)
        httpx_mock.add_response(url=API, json=PAGE)
        result = CliRunner().invoke(main, ["cli", "verify", "-F", "json"])
        assert result.exit_code == 0, result.output
        document = json.loads(result.stdout)
        assert_shape(document, "live-test-v1")
        assert document == {
            "schema": "adobe-credentials/v1/live-test",
            "tool": "cja-audit-log-monitor",
            "tool_version": __version__,
            "product": "cja",
            "ok": True,
            "source": {"kind": "environment", "name": "environment variables"},
            "sign_in": {"ok": True, "code": None, "message": None},
            "product_access": {"ok": True, "code": None, "message": None},
            "org_id": A["org_id"],
            "api_url": "https://cja.adobe.io",
            "total_logs_available": 12,
        }

    def test_text_names_both_steps_and_the_source(self, httpx_mock) -> None:
        write_profile("prod", A)
        _token(httpx_mock)
        httpx_mock.add_response(url=API, json=PAGE)
        result = CliRunner().invoke(main, ["--profile", "prod", "cli", "verify"])
        assert result.exit_code == 0, result.output
        for line in (
            "Connection successful",
            "  Sign-in: ok",
            "  Log fetch: ok",
            "  Credential: profile prod (~/.cja/orgs/prod/config.json)",
            f"  Organization: {A['org_id']}",
            "  Total logs available: 12",
        ):
            assert line in result.stdout

    @pytest.mark.parametrize(
        ("status", "body", "code", "message"),
        [
            (400, {"error": "invalid_client", "error_description": "bad id"}, "bad_client_id", ""),
            (
                401,
                {"error": "invalid_client", "error_description": "invalid client_secret parameter"},
                "bad_secret",
                "invalid client_secret parameter",
            ),
            (400, {"error": "invalid_scope", "error_description": "no"}, "scopes_rejected", "no"),
            (400, {"error": "unauthorized_client"}, "sign_in_failed", "unauthorized_client"),
            (400, {}, "sign_in_failed", "HTTP 400"),
            (502, "<html>bad gateway</html>", "sign_in_failed", "<html>bad gateway</html>"),
            (503, "", "sign_in_failed", "HTTP 503"),
            (200, {"page": "login"}, "unreachable", "IMS response had no access_token"),
            (200, "<html>", "unreachable", "IMS returned a non-JSON response"),
        ],
    )
    def test_sign_in_codes(self, monkeypatch, httpx_mock, status, body, code, message) -> None:
        set_env(monkeypatch, A)
        if isinstance(body, str):
            httpx_mock.add_response(url=IMS, status_code=status, text=body)
        else:
            httpx_mock.add_response(url=IMS, status_code=status, json=body)
        result = CliRunner().invoke(main, ["cli", "verify", "-F", "json"])
        assert result.exit_code == 1
        document = json.loads(result.stdout)
        assert_shape(document, "live-test-v1")
        assert document["ok"] is False
        assert document["sign_in"]["ok"] is False
        assert document["sign_in"]["code"] == code
        assert message in document["sign_in"]["message"]
        assert document["product_access"] == {"ok": None, "code": None, "message": None}
        assert "total_logs_available" not in document
        assert A["secret"] not in result.output

    def test_adobes_message_is_cut_and_has_no_secret(self, monkeypatch, httpx_mock) -> None:
        set_env(monkeypatch, A)
        text = f"client_secret={A['secret']} " + "x" * 400
        httpx_mock.add_response(
            url=IMS, status_code=400, json={"error": "other", "error_description": text}
        )
        result = CliRunner().invoke(main, ["cli", "verify", "-F", "json"])
        message = json.loads(result.stdout)["sign_in"]["message"]
        assert len(message) == 200 and message.startswith("client_secret=*** xxx")
        assert A["secret"] not in result.output

    @pytest.mark.parametrize("status", [401, 403])
    def test_no_product_access(self, monkeypatch, httpx_mock, status: int) -> None:
        set_env(monkeypatch, A)
        httpx_mock.add_response(
            url=IMS, json={"access_token": "t", "expires_in": 86399}, is_reusable=True
        )
        httpx_mock.add_response(url=API, status_code=status, json={}, is_reusable=True)
        result = CliRunner().invoke(main, ["cli", "verify", "-F", "json"])
        assert result.exit_code == 1
        document = json.loads(result.stdout)
        assert_shape(document, "live-test-v1")
        assert document["sign_in"] == {"ok": True, "code": None, "message": None}
        assert document["product_access"]["code"] == "no_product_access"
        assert "cannot reach Customer Journey Analytics" in document["product_access"]["message"]
        assert "CJA product profile" in document["product_access"]["message"]

        text = CliRunner().invoke(main, ["cli", "verify"])
        assert text.exit_code == 1
        assert "Connection failed" in text.stdout and "  Sign-in: ok" in text.stdout
        assert "  Log fetch: failed (no_product_access). The credential cannot" in text.stdout

    def test_an_unreadable_product_answer_is_unreachable(self, monkeypatch, httpx_mock) -> None:
        set_env(monkeypatch, A)
        _token(httpx_mock)
        httpx_mock.add_response(url=API, text="<html>proxy</html>")
        result = CliRunner().invoke(main, ["cli", "verify", "-F", "json"])
        assert result.exit_code == 1
        step = json.loads(result.stdout)["product_access"]
        assert (step["ok"], step["code"]) == (False, "unreachable")
        assert "non-JSON response" in step["message"]

    def test_a_failed_sign_in_in_text(self, monkeypatch, httpx_mock) -> None:
        set_env(monkeypatch, A)
        httpx_mock.add_response(
            url=IMS, status_code=400, json={"error": "invalid_scope", "error_description": "no"}
        )
        result = CliRunner().invoke(main, ["cli", "verify"])
        assert result.exit_code == 1
        assert "Authentication failed: invalid_scope: no" in result.stdout
        assert "  Sign-in: failed (scopes_rejected). Copy the scopes exactly" in result.stdout
        assert "  Log fetch: not run" in result.stdout

    @pytest.mark.parametrize("fmt", ["table", "json"])
    def test_no_credential_is_an_error_before_any_call(self, fmt: str) -> None:
        result = CliRunner().invoke(main, ["cli", "verify", "-F", fmt])
        assert result.exit_code == 1
        assert result.stdout == ""
        assert "Configuration error: No credential was found." in result.stderr

    def test_other_commands_say_how_to_give_a_credential(self) -> None:
        result = CliRunner().invoke(main, ["cli", "list"])
        assert result.exit_code == 1
        assert "Authentication error: OAuth not configured. No credential was found." in (
            result.stderr
        )

    def test_a_partial_source_stops_every_command(self, monkeypatch) -> None:
        set_env(monkeypatch, {k: v for k, v in A.items() if k != "scopes"})
        result = CliRunner().invoke(main, ["cli", "list"])
        assert result.exit_code == 1
        assert "Configuration error: environment variables:" in result.stderr
        assert "Missing: SCOPES." in result.stderr


class TestTui:
    def test_the_tui_does_not_open_on_a_broken_config_file(self, tmp_path, monkeypatch) -> None:
        set_env(monkeypatch, A)
        path = tmp_path / "config.yaml"
        path.write_text("monitor_interval: [1, \n")
        with patch("cja_audit_log_monitor.tui.CJAAuditApp") as make_app:
            result = CliRunner().invoke(main, [])
        assert result.exit_code == 1
        make_app.assert_not_called()
        assert f"Configuration error: {path}: not valid YAML" in result.stderr.replace("\n", "")

    def test_the_tui_does_not_open_on_a_lookup_error(self) -> None:
        with patch("cja_audit_log_monitor.tui.CJAAuditApp") as make_app:
            result = CliRunner().invoke(main, ["--profile", "missing", "tui"])
        assert result.exit_code == 1
        make_app.assert_not_called()
        assert "Configuration error: profile 'missing' was not found" in result.stderr

    def test_the_tui_gets_the_profile_and_the_loaded_settings(self) -> None:
        write_profile("prod", A)
        app = MagicMock(return_code=0)
        with (
            patch("cja_audit_log_monitor.tui.CJAAuditApp", return_value=app) as make_app,
            patch.object(cli, "exit_without_waiting_for_workers"),
        ):
            result = CliRunner().invoke(main, ["--profile", "prod"])
        assert result.exit_code == 0, result.output
        args, kwargs = make_app.call_args
        assert args == (None,) and kwargs["profile"] == "prod"
        assert credential(kwargs["settings"]) == A

    async def test_a_warning_from_the_first_load_shows_as_a_toast(self, tmp_path) -> None:
        """The settings are loaded before the TUI opens, where stderr is still on screen."""
        path = tmp_path / "config.yaml"
        path.write_text("monitor_intervall: 30\n")
        path.chmod(0o644)
        made = []

        def make_app(*args, **kwargs):
            made.append(CJAAuditApp(*args, **kwargs))
            return MagicMock(return_code=0)

        with (
            patch("cja_audit_log_monitor.tui.CJAAuditApp", side_effect=make_app),
            patch.object(cli, "exit_without_waiting_for_workers"),
        ):
            cli.run_tui(path)
        (app,) = made
        app.state._client = MagicMock()
        async with app.run_test(size=(140, 40), notifications=True) as pilot:
            await pilot.pause()
            shown = [note.message for note in app._notifications]
        assert sum("chmod 600" in text for text in shown) == 1
        assert sum("ignoring unknown setting 'monitor_intervall'" in text for text in shown) == 1

    def test_the_state_uses_settings_that_are_already_loaded(self, monkeypatch) -> None:
        write_profile("prod", A)
        settings = load_config(profile="prod")
        set_env(monkeypatch, B)
        state = AppState(profile="prod", settings=settings)
        assert state.settings is settings

    def test_the_state_loads_and_reloads_with_the_profile(self, monkeypatch) -> None:
        write_profile("prod", A)
        set_env(monkeypatch, B)
        state = AppState(profile="prod")
        assert credential(state.settings) == A
        write_profile("prod", B)
        state.reload_settings()
        assert credential(state.settings) == B

    def test_a_lookup_error_leaves_the_state_without_a_credential(self, monkeypatch) -> None:
        set_env(monkeypatch, B)
        state = AppState(profile="missing")
        assert not state.settings.is_oauth_configured()
        assert "profile 'missing' was not found" in (state.config_error_summary or "")
