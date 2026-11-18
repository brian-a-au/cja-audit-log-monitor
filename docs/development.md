# Development

## Setup

```bash
# Install with dev dependencies
uv sync --all-extras
```

This installs `pytest`, `pytest-asyncio`, `pytest-httpx`, and `ruff` alongside the runtime dependencies.

## Tests

```bash
# Whole suite
uv run pytest

# A single file
uv run pytest tests/test_client.py

# A single test
uv run pytest tests/test_client.py::TestAuditLogsClient::test_get_logs
```

Tests use `pytest-httpx` to mock HTTP calls. When testing the client, mock both the IMS token endpoint and the CJA API endpoint. CLI tests use Click's `CliRunner` and must prefix subgroup commands with `["cli", ...]`.

## Linting

```bash
# Check
uv run ruff check src tests

# Auto-fix
uv run ruff check src tests --fix
```

Ruff settings: line-length 100, target Python 3.11+. Selected rules: `E`, `F`, `I`, `N`, `W`, `UP`.

## Full CI run

```bash
# All supported versions (3.11 to 3.14)
scripts/ci.sh

# Only some versions
scripts/ci.sh 3.11 3.14
```

The script runs the same steps as `.github/workflows/ci.yml`:
- lint and tests on each Python version, each in its own environment under `.ci/`
- a build of the sdist and wheel
- a test install of the wheel, which then runs `cja-audit-log-monitor --help`

Your normal `.venv` is not changed. uv downloads any Python version you do not have.

The GitHub CI jobs are skipped while the repository is private, because Actions minutes are limited for private repositories. Run `scripts/ci.sh` before you merge to `main`. The GitHub jobs run again on their own once the repository is public.

## Project layout

The package lives in `src/cja_audit_log_monitor/`. Core modules: `cli.py`, `auth.py`, `client.py`, `config.py`, `models.py`, `alerts.py`, `monitor.py`, `formatters.py`, `stats.py`, `export.py`. The TUI lives under `src/cja_audit_log_monitor/tui/` (app, state, styles, screens, widgets, modals).

Each TUI view (`tui/screens/*.py`) subclasses `ContentView`, a plain widget that the app mounts once, on first visit, into a `ContentSwitcher`. Views are not Textual `Screen` objects: a `Screen` mounted as a child gets a zero-size region and renders nothing.

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
