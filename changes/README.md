# Changelog entries

Each pull request adds one file here instead of editing `CHANGELOG.md`. Open pull requests then never conflict over the top of the changelog.

Name the file `<short-name>.<section>.md`, where the section is one of `added`, `fixed`, `changed`, `deprecated`, `removed` or `security`. For example: `monitor-empty-stream.fixed.md`.

Write one or more list items in the changelog's own style, each starting with `- `:

```markdown
- In the TUI, the monitor's live stream showed only its column headers before monitoring started. It now says how to start it.
```

Check the files with `python scripts/changelog.py check`, and see the Unreleased section they make with `python scripts/changelog.py preview`. A test runs the same check on every pull request.

At release time, `python scripts/changelog.py release 1.2.3` writes a dated `1.2.3` section to `CHANGELOG.md` from the Unreleased entries and these files, then deletes the files.
