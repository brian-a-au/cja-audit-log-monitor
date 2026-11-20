"""scripts/changelog.py: the changelog entry files in changes/ and the release step."""

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "changelog.py"

pytestmark = pytest.mark.skipif(not SCRIPT.exists(), reason="scripts/ is not in the sdist")

CHANGELOG = """# Changelog

Intro.

## [Unreleased]

### Fixed

- An older fix.

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://example.com/repo/compare/v0.1.0...HEAD
[0.1.0]: https://example.com/repo/releases/tag/v0.1.0
"""


@pytest.fixture
def changelog():
    spec = importlib.util.spec_from_file_location("changelog_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def repo(tmp_path, changelog, monkeypatch):
    """A changes/ folder and CHANGELOG.md under tmp_path, used by the script's main()."""
    changes = tmp_path / "changes"
    changes.mkdir()
    (changes / "README.md").write_text("help, not an entry\n")
    path = tmp_path / "CHANGELOG.md"
    path.write_text(CHANGELOG)
    monkeypatch.setattr(changelog, "CHANGES", changes)
    monkeypatch.setattr(changelog, "CHANGELOG", path)
    return changes, path


def test_the_entry_files_in_this_repository_are_valid(changelog) -> None:
    assert changelog.check() == []


@pytest.mark.parametrize(
    ("name", "text", "problem"),
    [
        ("Bad Name.fixed.md", "- x\n", "name must look like"),
        ("thing.fix.md", "- x\n", "section must be one of"),
        ("thing.fixed.md", "\n\n", "the file is empty"),
        ("thing.fixed.md", "no dash\n", "must start with '- '"),
    ],
)
def test_check_names_each_problem(repo, changelog, name, text, problem) -> None:
    changes, _ = repo
    (changes / name).write_text(text)
    (problems,) = changelog.check(changes)
    assert problems.startswith(name) and problem in problems
    assert changelog.main(["check"]) == 1


def test_release_folds_unreleased_and_entry_files_into_a_section(repo, changelog) -> None:
    changes, path = repo
    (changes / "b-thing.fixed.md").write_text("- Newer fix B.\n")
    (changes / "a-thing.fixed.md").write_text("- Newer fix A,\n  on two lines.\n")
    (changes / "new.added.md").write_text("- A new feature.\n- And another.\n")
    assert changelog.main(["release", "0.2.0", "--date", "2026-02-02"]) == 0
    assert (
        path.read_text()
        == """# Changelog

Intro.

## [Unreleased]

## [0.2.0] - 2026-02-02

### Added

- A new feature.
- And another.

### Fixed

- Newer fix A,
  on two lines.
- Newer fix B.
- An older fix.

## [0.1.0] - 2026-01-01

### Added

- The first release.

[Unreleased]: https://example.com/repo/compare/v0.2.0...HEAD
[0.2.0]: https://example.com/repo/compare/v0.1.0...v0.2.0
[0.1.0]: https://example.com/repo/releases/tag/v0.1.0
"""
    )
    assert [p.name for p in changes.iterdir()] == ["README.md"]


def test_preview_shows_the_merged_unreleased_section(repo, changelog, capsys) -> None:
    changes, path = repo
    (changes / "x.changed.md").write_text("- A change.\n")
    assert changelog.main(["preview"]) == 0
    out = capsys.readouterr().out
    assert out == "## [Unreleased]\n\n### Fixed\n\n- An older fix.\n\n### Changed\n\n- A change.\n"
    assert path.read_text() == CHANGELOG
    assert changelog.main(["check"]) == 0
    assert "1 entry files are fine" in capsys.readouterr().out


def test_release_refuses_a_bad_version_a_repeat_or_nothing_to_release(repo, changelog) -> None:
    _, path = repo
    assert changelog.main(["release", "v0.2"]) == 1
    assert changelog.main(["release", "0.1.0"]) == 1
    path.write_text(CHANGELOG.replace("### Fixed\n\n- An older fix.\n\n", ""))
    assert changelog.main(["release", "0.2.0"]) == 1
    assert "## [0.2.0]" not in path.read_text()


def test_an_unknown_section_heading_is_kept(repo, changelog) -> None:
    _, path = repo
    path.write_text(CHANGELOG.replace("### Fixed", "Some words.\n\n### Notes"))
    assert changelog.main(["release", "0.2.0", "--date", "2026-02-02"]) == 0
    assert "## [0.2.0] - 2026-02-02\n\nSome words.\n\n### Notes\n\n- An older fix.\n" in (
        path.read_text()
    )


def test_a_missing_changes_folder_has_no_entries(tmp_path, changelog) -> None:
    assert changelog.fragment_files(tmp_path / "nope") == []


def test_a_changelog_without_compare_links_is_left_without_them(repo, changelog) -> None:
    _, path = repo
    path.write_text(CHANGELOG.split("\n[Unreleased]:")[0])
    assert changelog.main(["release", "0.2.0", "--date", "2026-02-02"]) == 0
    assert "]: " not in path.read_text()
