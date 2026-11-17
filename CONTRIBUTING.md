# Contributing

Thank you for your interest in this project. Bug reports, ideas, and pull requests are welcome.

## Report a bug or ask for a feature

Open an issue on GitHub. For a bug, please include these details:

- The command you ran, or the TUI screen you were on.
- What you expected to happen and what happened instead.
- Your Python version and operating system.

Please remove credentials, org IDs, and user emails from any logs you paste.

## Set up a development environment

You need Python 3.11 or newer and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/brian-a-au/cja-audit-log-monitor
cd cja-audit-log-monitor
uv sync --all-extras
```

You do not need Adobe credentials to run the tests. The tests mock every API call.

## Make a change

1. Create a branch from `main`.
2. Write a test that fails without your change.
3. Make the change.
4. Run the tests and the linter. Both must pass.

```bash
uv run pytest
uv run ruff check src tests scripts
```

If you change how the TUI looks, regenerate the screenshots and include them in your pull request:

```bash
uv run python scripts/capture_screenshots.py
```

See [docs/development.md](docs/development.md) for the project layout.

## Open a pull request

Describe what the change does and why. Link the issue if there is one. Keep each pull request to one topic, so it is easy to review.
