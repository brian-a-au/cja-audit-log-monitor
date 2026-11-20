# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- A date at the edge of the calendar with a time zone, such as `0001-01-01T00:00+05:00`, crashed the CLI. It is now a usage error that says the date is out of range.
- The export path check crashed on a lone surrogate character and passed a path with a null character, which then failed when the file was written. Both are now refused with a message.
- A webhook or Slack URL with a control character in its host could put that character into a log line or a toast. Redacted URLs are now cleaned like audit data.

### Changed

- Property-based tests (Hypothesis) now cover the date parser, text cleaning, CSV and TSV formula escaping, URL redaction, cell fitting and the export path check.
- Textual is now capped below version 9. A new major version can rename APIs, as Textual 8 did, so the cap is raised only after a check.

## [0.1.1] - 2026-11-19

### Fixed

- In the log browser, the filter **reset** button crashed the app with Textual 8.
- Opening entry details from the footer on an empty log table raised an error. It now shows "no entry selected".
- Pressing Ctrl+C in `cli monitor` could hang. The monitor now prints "Monitor stopped." after the poll ends, not from inside the signal handler.

### Changed

- Tests now measure branch coverage, and CI fails below 95%.

## [0.1.0] - 2026-11-19

This is the first public release. It is an unofficial, community tool and is not affiliated with Adobe.

### Added

Terminal app

- A terminal app with six views: dashboard, log browser, real-time monitor, statistics, alert rules, and config. Each view has its own key, and `?` lists every key.
- The dashboard shows the number of entries in the window, a chart of actions, the top users, and recent anomalies. It says when its charts use only the newest entries.
- The log browser shows audit entries in a table. You can filter by user, action, component, and text in the description, and page through the results. Press `Enter` to see every field of an entry.
- The monitor checks for new audit events at an interval you choose. It shows each event as it arrives and shows an alert when a rule fires. `Space` starts and stops it.
- The statistics view shows charts of actions, activity by hour and by day, and a ranking of users, for the number of days you choose.
- The alert rules view lets you turn rules on and off and test them against recent data.
- The config view shows the connection status and the settings in use, and lets you test the connection and load the settings again. It never shows the secret.
- The header shows the connection state. Each view names the kind of failure when something goes wrong: not connected, access denied, request rejected, or could not load data.
- Times in the terminal app use your local time zone, and the zone is named in the column heading.
- The layout fits terminals from 80x24 up to wide screens.
- Warnings, e.g. about the config file or a failed delivery, show as toasts. The terminal app has no log file.
- `q` quits at once, even while a request is in progress.

Command line

- A command line under `cja-audit-log-monitor cli` with commands to list, search, and query logs, and to look up a user, a component, an action, or a dashboard. The `show` command looks up one entry by its id.
- Commands for statistics, a timeline, top users, and a report that you can write to a file.
- Commands to watch for new events (`monitor` and `tail`) and to scan for anomalies (`anomalies`), once or on repeat.
- After a gap, e.g. a laptop asleep, the monitor reads the events it missed, up to 50,000 in one poll, and says how many it skipped past that. A short sign-in failure does not stop it, and Ctrl+C stops it at once.
- Commands to list the alert rules and test them against recent logs.
- Setup commands: `verify` checks the connection, `init` creates the config file, `config` shows the settings in use, and `actions` and `components` list the valid names.
- Most commands accept `-F json`. Data goes to stdout and messages go to stderr, so you can use the output in scripts. Exit codes tell you whether a command succeeded, failed, or was used incorrectly.
- Dates can be given as `YYYY-MM-DD`, `YYYYMMDD`, or a day and time. A value with no time zone is read as UTC, and times in CLI tables are in UTC.
- Each error prints one line that starts with its kind, e.g. `Configuration error:` or `Network error:`.
- `--version`, `-v` for debug logging, and `-c` to read a config file from another path.

Alerts and anomalies

- Four built-in alert rules: bulk deletes, bulk exports, deletes of sensitive components (data views, connections, filters, and calculated metrics), and bulk shares. A config file can replace them with your own rules.
- A rule can match by action, component type, and user, and you can set the count, the time window, and whether each account is counted on its own.
- Three anomaly checks: a burst of activity between midnight and 5am, one user with far more activity than the others, and one user with many deletes. The terminal app judges the hours in your local time zone, and the CLI judges them in UTC. Every off-hours anomaly names its time zone.

Notifications

- Optional delivery of alerts and anomalies to Slack and to webhooks. Delivery is off by default.
- While `anomalies --watch` runs, each anomaly reaches each channel once. A channel that failed gets it again on the next scan, and each failing channel gives its own warning.
- Messages and logs show only `https://` and the host name of a Slack or webhook URL, because the rest of the URL can hold a secret.

Export

- Export to JSON, CSV, or TSV from the terminal app and from the CLI. The CLI takes the format from the file name when `-F` is not given, writes to stdout with `-o -`, and replaces a file only with `--force`.
- Exports include the change details of each entry. When nothing matches, the file is still written, with no entries.
- In CSV and TSV, a cell that a spreadsheet could read as a formula starts with `'`. TSV uses no quotes.
- The terminal app can save every entry that matches the filters, up to 10,000, or only the page you see.

Configuration and security

- Sign-in uses an Adobe OAuth Server-to-Server credential. The tool reads the organization ID, client ID, and secret from environment variables, a `.env` file, or a config file, in that order of priority.
- The config file is created with mode 0600 in a folder with mode 0700. The tool logs a warning if other users can read it.
- Export files are created with mode 0600, because they can hold user emails and IP addresses.
- The API and sign-in addresses must use https. Plain http is allowed only for `localhost` and `127.0.0.1`.
- Error messages and debug logs never show the secret.
- Control characters in audit data, e.g. terminal escape sequences in a component name, are replaced before any output, so they never reach your terminal.
- The tool refreshes its access token before it expires and retries when the API limits the request rate.

[Unreleased]: https://github.com/brian-a-au/cja-audit-log-monitor/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/brian-a-au/cja-audit-log-monitor/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/brian-a-au/cja-audit-log-monitor/releases/tag/v0.1.0
