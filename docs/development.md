# Development

## Setup

```bash
# Install with dev dependencies
uv sync --all-extras
```

This installs `pytest`, `pytest-asyncio`, `pytest-httpx`, `hypothesis`, and `ruff` alongside the runtime dependencies.

## Tests

```bash
# Whole suite
uv run pytest

# A single file
uv run pytest tests/test_client.py

# A single test
uv run pytest tests/test_client.py::TestAuditLogsClient::test_get_logs

# With coverage (fails below 95%)
uv run pytest --cov

# A longer search in the property tests (5,000 examples each)
uv run pytest tests/test_properties.py --hypothesis-profile=deep
```

`tests/test_properties.py` uses Hypothesis to feed hostile text (control characters, lone surrogates, CJK, emoji and combining marks) to the date parser, the text cleaners, the CSV and TSV writers, the URL redactor and the export path check.

CI measures branch coverage on each Python version and fails below the `fail_under` value in `pyproject.toml`. If you raise coverage, raise that value and the README badge to match.

Tests use `pytest-httpx` to mock HTTP calls. When testing the client, mock both the IMS token endpoint and the CJA API endpoint. CLI tests use Click's `CliRunner` and must prefix subgroup commands with `["cli", ...]`.

## Linting and formatting

```bash
# Check
uv run ruff check src tests scripts
uv run ruff format --check src tests scripts

# Fix
uv run ruff check src tests scripts --fix
uv run ruff format src tests scripts
```

Ruff checks lines up to 100 characters and targets Python 3.11. It uses the rule sets `E`, `F`, `I`, `N`, `W` and `UP`.

## Full CI run

```bash
# All supported versions (3.11 to 3.14)
scripts/ci.sh

# Only some versions
scripts/ci.sh 3.11 3.14
```

The script runs the same steps as `.github/workflows/ci.yml`:
- lint and tests on each Python version, each in its own environment under `.ci/`
- the floors step, which installs the lowest versions of the direct dependencies that `pyproject.toml` allows and runs the tests on Python 3.11
- the newest step, which installs the newest versions of the dependencies and runs the tests on Python 3.14
- a build of the sdist and wheel
- a test install of the wheel, which then runs `cja-audit-log-monitor --help`

Each version step runs `ruff check`, `ruff format --check` and the tests. `uv.lock` is tracked in the repository, so `uv sync` installs the same versions on every machine. Your normal `.venv` is not changed. uv downloads any Python version you do not have.

GitHub runs the same jobs on every pull request and every push to `main`, and you can start them by hand from the Actions tab.

## Before you open a pull request

- Write a test that fails without your change, and check that it passes with it.
- Run `scripts/ci.sh`, or at least the tests and both ruff commands.
- If you change how the TUI looks, regenerate the screenshots (see below) and look at them.
- Never put credentials, org IDs, real names or emails in code, tests, screenshots or commit messages. Test data uses example.com.

## Releases

1. Set the new version in `pyproject.toml` and add a dated section to `CHANGELOG.md`.
2. Merge that change to `main`.
3. Push a tag that matches the version, e.g. `git tag v0.2.0 && git push origin v0.2.0`.

The tag starts `.github/workflows/release.yml`. It runs CI, checks that the tag matches the version, builds the package, and waits for the maintainer to approve the `pypi` environment. It then publishes to PyPI through trusted publishing, with no stored token, and creates the GitHub release.

## Project layout

The package lives in `src/cja_audit_log_monitor/`. Core modules: `cli.py`, `auth.py`, `client.py`, `config.py`, `models.py`, `alerts.py`, `monitor.py`, `notifications.py`, `formatters.py`, `stats.py`, `export.py`, `utils.py`. The TUI lives under `src/cja_audit_log_monitor/tui/` (app, state, styles, screens, widgets, modals).

Each TUI view (`tui/screens/*.py`) subclasses `ContentView`, a plain widget that the app mounts once, on first visit, into a `ContentSwitcher`. Views are not Textual `Screen` objects. A `Screen` mounted as a child gets no space on the screen and shows nothing.

## Screenshots

The images in `docs/screenshots/` come from the real app, run headless with only the API client mocked:

```bash
uv run python scripts/capture_screenshots.py                                 # 140x42, into docs/screenshots
uv run python scripts/capture_screenshots.py --size 100x30 --out /tmp/shots  # check a narrow terminal
```

The slideshow at the top of the README, `docs/showcase.gif`, uses the same synthetic data. The script drives the app through seven views, saves a screenshot of each, and joins them into a GIF. It also saves the first slide as `docs/showcase.png`. You need Google Chrome and FFmpeg:

```bash
uv run python scripts/make_showcase.py   # writes docs/showcase.gif and docs/showcase.png
```
