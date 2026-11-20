"""Changelog entries kept as one small file per change, folded into CHANGELOG.md on release.

Each pull request adds a file to ``changes/`` instead of editing CHANGELOG.md, so open pull
requests never conflict over the top of the changelog. A file is named
``<short-name>.<section>.md``, where the section is one of SECTIONS, and holds one or more
``- `` list items in the changelog's own style.

Usage:
    python scripts/changelog.py check             check every file in changes/
    python scripts/changelog.py preview           print the Unreleased section with them
    python scripts/changelog.py release 0.1.3     write them into a 0.1.3 section and
                                                  delete them (add --date YYYY-MM-DD)
"""

from __future__ import annotations

import argparse
import datetime
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANGES = ROOT / "changes"
CHANGELOG = ROOT / "CHANGELOG.md"

# Sections in the order they appear in a release, as in this project's changelog so far.
SECTIONS = ["added", "fixed", "changed", "deprecated", "removed", "security"]
UNRELEASED = "## [Unreleased]"
NAME = re.compile(r"^[a-z0-9][a-z0-9-]*\.(?P<section>[a-z]+)\.md$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")


def fragment_files(changes: Path = CHANGES) -> list[Path]:
    """The entry files in ``changes``, by name. README.md is the folder's own help."""
    if not changes.is_dir():
        return []
    return sorted(p for p in changes.iterdir() if p.is_file() and p.name != "README.md")


def _items(text: str) -> list[str]:
    """Split text into list items. A line that does not start with ``- `` continues the last."""
    items: list[str] = []
    for line in text.splitlines():
        if not line.strip():
            continue
        if line.startswith("- ") or not items:
            items.append(line.rstrip())
        else:
            items[-1] += "\n" + line.rstrip()
    return items


def check(changes: Path = CHANGES) -> list[str]:
    """Problems with the entry files; an empty list when all of them are fine."""
    problems = []
    for path in fragment_files(changes):
        match = NAME.match(path.name)
        if match is None:
            problems.append(f"{path.name}: name must look like short-name.fixed.md")
            continue
        if match["section"] not in SECTIONS:
            problems.append(f"{path.name}: section must be one of {', '.join(SECTIONS)}")
            continue
        items = _items(path.read_text(encoding="utf-8"))
        if not items:
            problems.append(f"{path.name}: the file is empty")
        elif any(not item.startswith("- ") for item in items):
            problems.append(f"{path.name}: each entry must start with '- '")
    return problems


def _split(text: str) -> tuple[str, str, str]:
    """Split the changelog into (head with the Unreleased heading, Unreleased body, rest)."""
    start = text.index(UNRELEASED) + len(UNRELEASED)
    end = text.find("\n## [", start)
    end = len(text) if end == -1 else end + 1
    return text[:start], text[start:end], text[end:]


def _sections(body: str) -> tuple[str, dict[str, list[str]]]:
    """Parse an Unreleased body into its text before any heading and its items by section."""
    intro: list[str] = []
    sections: dict[str, list[str]] = {}
    current: str | None = None
    lines: dict[str, list[str]] = {}
    for line in body.splitlines():
        heading = re.match(r"^### (.+)$", line)
        if heading:
            current = heading.group(1).strip().lower()
            lines.setdefault(current, [])
        elif current is None:
            intro.append(line)
        else:
            lines[current].append(line)
    for name, section_lines in lines.items():
        sections[name] = _items("\n".join(section_lines))
    return "\n".join(intro).strip(), sections


def merged_body(body: str, changes: Path = CHANGES) -> str:
    """The Unreleased body with the entry files added at the top of their sections."""
    intro, sections = _sections(body)
    for path in reversed(fragment_files(changes)):
        section = NAME.match(path.name)["section"]  # type: ignore[index]
        sections[section] = _items(path.read_text(encoding="utf-8")) + sections.get(section, [])
    order = [s for s in SECTIONS if s in sections] + [s for s in sections if s not in SECTIONS]
    parts = [intro] if intro else []
    for name in order:
        if sections[name]:
            parts.append(f"### {name.capitalize()}\n\n" + "\n".join(sections[name]))
    return "\n\n".join(parts)


def _update_links(text: str, version: str) -> str:
    """Point the ``[Unreleased]`` compare link at the new tag and add a link for ``version``.

    ``[Unreleased]: <repo>/compare/vOLD...HEAD`` becomes ``.../compare/vNEW...HEAD``, with
    ``[NEW]: <repo>/compare/vOLD...vNEW`` under it. Text without that link is unchanged.
    """
    link = re.compile(r"^\[Unreleased\]: (?P<repo>\S+)/compare/(?P<old>\S+)\.\.\.HEAD$", re.M)
    match = link.search(text)
    if match is None:
        return text
    repo, old = match["repo"], match["old"]
    new = (
        f"[Unreleased]: {repo}/compare/v{version}...HEAD\n"
        f"[{version}]: {repo}/compare/{old}...v{version}"
    )
    return text[: match.start()] + new + text[match.end() :]


def release(version: str, date: str, changes: Path = CHANGES, changelog: Path = CHANGELOG) -> None:
    """Move the Unreleased entries and the entry files into a new section for ``version``.

    Raises:
        ValueError: There is nothing to release, or ``version`` already has a section.
    """
    text = changelog.read_text(encoding="utf-8")
    if f"## [{version}]" in text:
        raise ValueError(f"CHANGELOG.md already has a {version} section")
    head, body, rest = _split(text)
    merged = merged_body(body, changes)
    if not merged:
        raise ValueError("nothing to release: no Unreleased entries and no entry files")
    new_text = f"{head}\n\n## [{version}] - {date}\n\n{merged}\n\n{rest}"
    changelog.write_text(_update_links(new_text, version), encoding="utf-8")
    for path in fragment_files(changes):
        path.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="check every file in changes/")
    commands.add_parser("preview", help="print the Unreleased section with the entry files")
    release_parser = commands.add_parser("release", help="write a release section")
    release_parser.add_argument("version")
    release_parser.add_argument("--date", default=datetime.date.today().isoformat())
    args = parser.parse_args(argv)

    problems = check(CHANGES)
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    if args.command == "check":
        print(f"{len(fragment_files(CHANGES))} entry files are fine")
    elif args.command == "preview":
        _, body, _ = _split(CHANGELOG.read_text(encoding="utf-8"))
        print(f"{UNRELEASED}\n\n{merged_body(body, CHANGES)}")
    else:
        if not VERSION.match(args.version):
            print("version must look like 1.2.3", file=sys.stderr)
            return 1
        try:
            release(args.version, args.date, CHANGES, CHANGELOG)
        except ValueError as error:
            print(error, file=sys.stderr)
            return 1
        print(f"wrote the {args.version} section of CHANGELOG.md and removed the entry files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
