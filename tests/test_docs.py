"""Docs drift: the commands, flags and defaults in the docs must match the CLI itself."""

import re
import shlex
from pathlib import Path

import click
import pytest

from cja_audit_log_monitor.cli import cli, main
from cja_audit_log_monitor.config import CJASettings

ROOT = Path(__file__).resolve().parent.parent
CLI_DOC = ROOT / "docs" / "cli.md"
DOCS = [ROOT / "README.md", *sorted((ROOT / "docs").glob("*.md"))]
DOCS += sorted((ROOT / "docs" / "screens").glob("*.md"))


def _commands() -> dict[str, click.Command]:
    """Every CLI command by its documented name, e.g. ``list`` or ``alerts test``."""
    found: dict[str, click.Command] = {}
    for name, command in cli.commands.items():
        if isinstance(command, click.Group):
            for sub_name, sub in command.commands.items():
                found[f"{name} {sub_name}"] = sub
        else:
            found[name] = command
    return found


def _flags(command: click.Command) -> set[str]:
    flags: set[str] = set()
    for param in command.params:
        if isinstance(param, click.Option):
            flags.update(param.opts)
            flags.update(param.secondary_opts)
    flags.discard("--help")
    return flags


def _sections(text: str) -> dict[str, str]:
    """Each ``### `name` `` section of a page, by name."""
    parts = re.split(r"^(#{2,3} .*)$", text, flags=re.M)
    sections: dict[str, str] = {}
    for heading, body in zip(parts[1::2], parts[2::2], strict=True):
        match = re.fullmatch(r"### `([a-z -]+)`", heading.strip())
        if match:
            sections[match.group(1)] = body
    return sections


def _flag_rows(section: str) -> list[tuple[list[str], str]]:
    """The rows of a section's ``| Flag | Default | Meaning |`` table: (flags, default)."""
    rows: list[tuple[list[str], str]] = []
    in_table = False
    for line in section.splitlines():
        if line.startswith("| Flag | Default |"):
            in_table = True
            continue
        if in_table and line.startswith("|---"):
            continue
        if in_table and line.startswith("|"):
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            flags = re.findall(r"`(-[^`]+)`", cells[0])
            rows.append((flags, cells[1]))
        elif in_table:
            break
    return rows


SECTIONS = _sections(CLI_DOC.read_text())
COMMANDS = _commands()


def _other_commands() -> set[str]:
    """Commands listed in the "Other commands" table instead of having a section."""
    text = CLI_DOC.read_text().split("## Other commands", 1)[1]
    return set(re.findall(r"^\| `cli ([a-z -]+)` \|", text, flags=re.M))


def test_every_command_is_documented_once() -> None:
    other = _other_commands()
    assert set(SECTIONS) | other == set(COMMANDS)
    assert not set(SECTIONS) & other


@pytest.mark.parametrize("name", sorted(SECTIONS))
def test_documented_flags_match_the_command(name: str) -> None:
    documented = {flag for flags, _ in _flag_rows(SECTIONS[name]) for flag in flags}
    assert documented == _flags(COMMANDS[name])


def test_other_commands_have_no_flags_but_the_ones_named() -> None:
    for name in _other_commands():
        flags = _flags(COMMANDS[name])
        if name in ("config", "verify"):
            assert flags == {"-F", "--output-format"}
        else:
            assert flags == set(), name


_CONFIG_DEFAULTS = {
    "--days": CJASettings.model_fields["default_days"].default,
    "--interval": CJASettings.model_fields["monitor_interval"].default,
}
# What the docs write for "no default": a filter that matches everything, no limit, and so on.
_EMPTY_WORDS = {"all", "any", "none", "no limit", "stdout", "", "off"}
# Defaults the command works out at run time, so the docs describe them in words.
_WORKED_OUT = {("export", "-F"): "from the file suffix"}
# Click 8.3 marks "no default" with a sentinel; Click 8.2 uses None.
_UNSET = getattr(click.core, "UNSET", None)


def _expected_text(param: click.Option) -> str | None:
    """How a default should read in the docs, or None when any empty word fits."""
    if param.required:
        return "required"
    default = param.default
    # Click 8.3 and later can give a flag the UNSET sentinel, which is truthy: compare to True.
    if param.is_flag and param.secondary_opts:
        return f"`{param.opts[0] if default is True else param.secondary_opts[0]}`"
    if param.is_flag:
        return "on" if default is True else None  # "off", or blank for the query presets
    if param.show_default is False:
        return None
    if default is None or default is _UNSET or default == ():
        long_flag = max(param.opts, key=len)
        if long_flag in _CONFIG_DEFAULTS:
            return f"from config ({_CONFIG_DEFAULTS[long_flag]})"
        return None
    if isinstance(param.type, click.Choice):
        return f"`{default}`"
    return str(default)


@pytest.mark.parametrize("name", sorted(SECTIONS))
def test_documented_defaults_match_the_command(name: str) -> None:
    params = {
        opt: p for p in COMMANDS[name].params if isinstance(p, click.Option) for opt in p.opts
    }
    for flags, written in _flag_rows(SECTIONS[name]):
        param = params[flags[0]]
        if (name, flags[0]) in _WORKED_OUT:
            assert written == _WORKED_OUT[name, flags[0]]
            assert param.show_default is False, "--help must not show a fixed default"
            continue
        expected = _expected_text(param)
        if expected is None:
            assert written in _EMPTY_WORDS, (name, flags, written)
        else:
            assert written == expected, (name, flags)


def test_json_output_list_matches_the_commands() -> None:
    text = CLI_DOC.read_text()
    line = next(line for line in text.splitlines() if line.startswith("These commands accept"))
    documented = set(re.findall(r"`([a-z -]+)`", line.split(":", 1)[1]))
    with_json = {
        name
        for name, command in COMMANDS.items()
        for p in command.params
        if "--output-format" in getattr(p, "opts", [])
        and isinstance(p.type, click.Choice)
        and "json" in p.type.choices
        and set(p.type.choices) == {"table", "json"}
    }
    assert documented == with_json


def test_global_options_match_the_main_group() -> None:
    text = CLI_DOC.read_text().split("## Options for the whole tool", 1)[1].split("## ", 1)[0]
    documented = set(re.findall(r"`(--?[a-z-]+)", text))
    assert documented == _flags(main) | {"--help"}


# ---------------------------------------------------------------------------
# Every example command in the README and the docs must parse


def _examples() -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for doc in DOCS:
        text = doc.read_text()
        blocks = re.findall(r"```(?:bash|sh|console)?\n(.*?)```", text, flags=re.S)
        lines = [line for block in blocks for line in block.splitlines()]
        lines += re.findall(r"`(cja-audit-log-monitor [^`]+)`", text)
        for line in lines:
            line = line.strip().removeprefix("$ ")
            if line.startswith("cja-audit-log-monitor"):
                found.append((doc.name, line))
    return found


def _check_example(line: str) -> None:
    # Only the command itself: stop at a pipe, a redirect or a comment.
    line = re.split(r"\s(?:\||>|2>|&&|#)", line, maxsplit=1)[0]
    tokens = shlex.split(line)[1:]
    command: click.Command = main
    while tokens:
        token = tokens.pop(0)
        if token.startswith("-"):
            flag = token.split("=", 1)[0]
            options = {o: p for p in command.params for o in getattr(p, "opts", [])}
            options.update({o: p for p in command.params for o in getattr(p, "secondary_opts", [])})
            assert flag in options or flag == "--help", f"unknown flag {flag}"
            param = options.get(flag)
            if param is not None and not param.is_flag and "=" not in token and tokens:
                tokens.pop(0)  # the flag's value
        elif isinstance(command, click.Group):
            if token.isupper() or token.startswith("<") or token == "...":
                return  # a placeholder such as COMMAND or <command>
            assert token in command.commands, f"unknown command {token}"
            command = command.commands[token]
        # Anything else is an argument, e.g. an entry id.


EXAMPLES = _examples()


def test_the_docs_have_examples() -> None:
    assert len(EXAMPLES) > 20


@pytest.mark.parametrize("doc,line", EXAMPLES)
def test_every_example_command_parses(doc: str, line: str) -> None:
    _check_example(line)
