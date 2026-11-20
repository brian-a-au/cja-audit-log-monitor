# Contributing to cja-audit-log-monitor

Bug reports, ideas and pull requests are welcome. [docs/development.md](docs/development.md) is the main guide for people and coding agents. It covers setup, the checks that must pass, where the code is, and how releases work.

To report a bug, open an issue with the command you ran or the TUI view you were on, what you expected and what happened, and your Python version and operating system. Remove credentials, org IDs and user emails from anything you paste.

Open an issue to discuss a large feature before you write it. For a bug fix, write a test that fails without your change. In the pull request, describe the change and say how you checked it, and keep each pull request to one topic. Add a changelog entry as a file in `changes/` (see `changes/README.md`), not in `CHANGELOG.md`. You do not need Adobe credentials to run the tests, because they mock every API call.

By taking part, you agree to follow the [code of conduct](CODE_OF_CONDUCT.md). Report security issues privately, as [SECURITY.md](SECURITY.md) describes.
