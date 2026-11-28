"""Find the Adobe credential, as the Adobe credentials standard (version 1) describes.

The credential is the four fields ``org_id``, ``client_id``, ``secret`` and ``scopes``.
The tool looks in these places, in this order, and uses the first one that holds any of
the four fields:

1. ``--profile <name>`` or ``-c/--config <path>`` (both together is an error)
2. the profile named by ``CJA_PROFILE``
3. the environment variables ``ORG_ID``, ``CLIENT_ID``, ``SECRET`` and ``SCOPES``
4. ``.env`` in the working folder
5. the default config file

One source gives all four fields. A source with some of them and not all is an error,
and fields are never mixed between two sources. Nothing here prints a secret.
"""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from .utils import display_path

logger = logging.getLogger(__name__)

SPEC = "adobe-credentials/v1"
TOOL = "cja-audit-log-monitor"
PRODUCT = "cja"
PROFILE_VARIABLE = "CJA_PROFILE"
CREDENTIAL_FIELDS = ("org_id", "client_id", "secret", "scopes")
MASKED = "****"
NOT_SET = "(not set)"

NO_CREDENTIAL = (
    "No credential was found. Give one with --profile, with -c, with the CJA_PROFILE "
    "variable, with the ORG_ID, CLIENT_ID, SECRET and SCOPES environment variables, in a "
    ".env file in the working folder, or in the config file."
)

_PROFILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
_PROFILE_KINDS = ("flag_profile", "profile_variable")
_VARIABLE_KINDS = ("environment", "dotenv")


class ConfigError(Exception):
    """The config file could not be read or holds invalid settings.

    ``str(error)`` is the full message; ``summary`` is a one-line version for
    tight spaces such as the TUI header.
    """

    def __init__(self, message: str, summary: str | None = None) -> None:
        super().__init__(message)
        first_line = (message.strip().splitlines() or [""])[0]
        self.summary = summary or first_line


class CredentialError(ConfigError):
    """The credential lookup failed. ``code`` is an error code of the standard."""

    def __init__(self, code: str, message: str, missing: list[str] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.missing = missing or []
        self.report: CredentialReport | None = None


def mask_client_id(client_id: str) -> str:
    """The first 4 and last 4 characters around ``****``; 8 or fewer shows as ``****``."""
    if not client_id:
        return NOT_SET
    if len(client_id) <= 8:
        return MASKED
    return f"{client_id[:4]}{MASKED}{client_id[-4:]}"


def mask_secret(secret: str) -> str:
    """``****`` for any secret that is set, so its length is not shown."""
    return MASKED if secret else NOT_SET


def is_valid_profile_name(name: str) -> bool:
    """Letters, digits, dots, underscores and hyphens; a letter or digit first; 64 at most."""
    return _PROFILE_NAME.fullmatch(name) is not None


def profiles_dir() -> Path:
    """The folder the CJA tools share for profiles."""
    return Path.home() / ".cja" / "orgs"


def profile_path(name: str) -> Path:
    """The file of profile ``name``. The name is checked before the path is built."""
    if not is_valid_profile_name(name):
        raise CredentialError(
            "invalid_profile_name",
            f"profile name {name!r} is not valid. Use letters, digits, dots, underscores and "
            "hyphens, start with a letter or a digit, and use 64 characters or fewer.",
        )
    return profiles_dir() / name / "config.json"


def warn_if_not_private(path: Path) -> None:
    """Warn when a credential file is readable by group or others (POSIX only).

    ``stat`` follows a symlink, so the mode checked is the mode of the link's target.
    """
    if sys.platform == "win32":
        return
    status = path.stat()
    if not stat.S_ISREG(status.st_mode):
        return  # e.g. a folder: the caller reports it, and chmod 600 would be wrong advice
    mode = stat.S_IMODE(status.st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        where = display_path(path)  # ~ works in the shell command too
        logger.warning(
            "%s is readable by other users (mode %o); run: chmod 600 %s", where, mode, where
        )


@dataclass
class Source:
    """One place that holds credential fields."""

    kind: str
    name: str
    path: Path | None = None
    # Holds the secret: never shown, and kept out of the repr.
    values: dict[str, Any] = field(default_factory=dict, repr=False)
    profile: str | None = None
    sandbox: bool = False
    used: bool = False
    skipped: str | None = None

    @property
    def missing(self) -> list[str]:
        """The credential fields this source lacks."""
        return [name for name in CREDENTIAL_FIELDS if name not in self.values]

    def as_json(self) -> dict[str, Any]:
        """The source for the config check. Field names only, never a value."""
        data: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "path": display_path(self.path) if self.path else None,
            "used": self.used,
            "fields": [*self.values, *(["sandbox"] if self.sandbox else [])],
            "skipped": self.skipped,
        }
        if self.skipped == "partial":
            data["missing"] = self.missing
        return data


@dataclass
class CredentialReport:
    """Where the tool looked for the credential and what it found."""

    sources: list[Source] = field(default_factory=list)
    error: CredentialError | None = None

    @property
    def winner(self) -> Source | None:
        """The source the credential comes from, or None."""
        return next((source for source in self.sources if source.used), None)

    @property
    def values(self) -> dict[str, Any]:
        """The four fields of the credential; each is empty when no source won."""
        found = self.winner.values if self.winner else {}
        return {name: found.get(name, "") for name in CREDENTIAL_FIELDS}

    def problems(self) -> list[dict[str, Any]]:
        """The problems of the lookup, each with a code of the standard."""
        if self.error is not None:
            problem: dict[str, Any] = {"code": self.error.code, "message": str(self.error)}
            if self.error.missing:
                problem["missing"] = self.error.missing
            return [problem]
        if self.winner is None:
            return [{"code": "no_credential", "message": NO_CREDENTIAL}]
        return []

    def as_json(self, tool_version: str) -> dict[str, Any]:
        """The config check document (``adobe-credentials/v1/config-check``)."""
        winner = self.winner
        problems = self.problems()
        return {
            "schema": f"{SPEC}/config-check",
            "tool": TOOL,
            "tool_version": tool_version,
            "product": PRODUCT,
            "ok": not problems,
            "profile": winner.profile if winner else None,
            "sources": [source.as_json() for source in self.sources],
            "credential": {
                "org_id": winner.values["org_id"] if winner else None,
                "client_id": mask_client_id(winner.values["client_id"]) if winner else None,
                "secret_set": winner is not None,
                "scopes": winner.values["scopes"] if winner else None,
            },
            "problems": problems,
            "notices": [],
        }


def credential_values(data: dict[str, Any]) -> dict[str, Any]:
    """The credential fields of ``data`` that are set. An empty value counts as not set."""
    return {name: data[name] for name in CREDENTIAL_FIELDS if data.get(name) not in (None, "")}


def _read_profile(name: str, kind: str) -> Source:
    """Read profile ``name``. The file is never written."""
    path = profile_path(name)
    where = display_path(path)
    if not path.is_file():
        raise CredentialError(
            "profile_not_found", f"profile {name!r} was not found: {where} does not exist"
        )

    def fail(problem: str) -> ConfigError:
        return ConfigError(f"{path}: {problem}", f"{path.name}: {problem}")

    # Each error is raised ``from None``, so a traceback never carries the file's content.
    try:
        warn_if_not_private(path)
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as e:
        raise fail(f"cannot be read ({e.strerror or type(e).__name__})") from None
    except (ValueError, RecursionError):
        raise fail("not valid JSON") from None
    if not isinstance(data, dict):
        raise fail("expected a JSON object at the top level")
    for key in data:
        if key in CREDENTIAL_FIELDS or key == "sandbox":
            continue
        if key.lower() in CREDENTIAL_FIELDS:
            logger.warning(
                "%s: the key %r is in upper case and was not read; write it as %r",
                where,
                key,
                key.lower(),
            )
        else:
            logger.debug("%s: ignoring unknown key %r", where, key)
    return Source(
        kind=kind,
        name=f"profile {name}",
        path=path,
        values=credential_values(data),
        profile=name,
        sandbox="sandbox" in data,
    )


def _read_dotenv() -> Source:
    """Read ``.env`` in the working folder as a source of its own.

    The file is not loaded into the environment, and parent folders are not searched.
    """
    path = Path(".env")
    values: dict[str, Any] = {}
    if path.is_file():
        try:
            raw = dotenv_values(path, encoding="utf-8")
        except UnicodeDecodeError:
            text = ".env is not UTF-8 text"
            raise ConfigError(text, text) from None
        except OSError as e:
            text = f".env cannot be read ({e.strerror or type(e).__name__})"
            raise ConfigError(text, text) from None
        values = credential_values({key.lower(): value for key, value in raw.items()})
        if values:
            warn_if_not_private(path)
    return Source(kind="dotenv", name=".env file", path=path.absolute(), values=values)


def _find_sources(
    profile: str | None, config_data: dict[str, Any], config_path: Path, config_is_flag: bool
) -> list[Source]:
    """Every source that holds a credential field, highest first."""
    config_file = Source(
        kind="flag_config" if config_is_flag else "default_config",
        name=f"config file {display_path(config_path)}",
        path=config_path,
        values=credential_values(config_data),
        sandbox="sandbox" in config_data,
    )
    sources: list[Source] = []
    if profile is not None:
        sources.append(_read_profile(profile, "flag_profile"))
    elif config_is_flag and config_file.values:
        sources.append(config_file)
    variable = os.environ.get(PROFILE_VARIABLE)
    if not sources and variable:
        sources.append(_read_profile(variable, "profile_variable"))
    environment = Source(
        kind="environment",
        name="environment variables",
        values=credential_values({key.lower(): value for key, value in os.environ.items()}),
    )
    lower = [environment, _read_dotenv()]
    if not config_is_flag:
        lower.append(config_file)
    return sources + [source for source in lower if source.values]


def resolve_credential(
    *,
    profile: str | None,
    config_data: dict[str, Any],
    config_path: Path,
    config_is_flag: bool,
) -> CredentialReport:
    """Look for the credential. The first source that holds a field gives all four.

    A lookup that fails is returned in ``report.error`` and is not raised, so the config
    check can report it. A file that cannot be read or parsed raises ConfigError.
    """
    report = CredentialReport()
    try:
        if profile is not None and config_is_flag:
            raise CredentialError(
                "profile_and_config_both_given",
                "--profile and --config were both given. Use one of them.",
            )
        report.sources = _find_sources(profile, config_data, config_path, config_is_flag)
        if report.sources:
            first = report.sources[0]
            for source in report.sources[1:]:
                source.skipped = "lower_priority"
            if first.missing:
                first.skipped = "partial"
                names = first.missing
                if first.kind in _VARIABLE_KINDS:
                    names = [name.upper() for name in names]
                raise CredentialError(
                    "partial_source",
                    f"{first.name}: only some of the four credential fields are set. "
                    f"Missing: {', '.join(names)}. One source must give all four.",
                    missing=first.missing,
                )
            first.used = True
    except CredentialError as error:
        error.report = report
        report.error = error
    return report
