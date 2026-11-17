# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - Unreleased

This is the first public release.

### Added

- A terminal UI with six views. The views are dashboard, log browser, real-time monitor, statistics, alert rules, and config.
- A CLI under `cja-audit-log-monitor cli` for listing, searching, exporting, statistics, monitoring, and anomaly detection.
- Alert rules that detect bulk deletes, exports, and activity outside business hours.
- Optional delivery of alerts and anomalies to Slack and webhooks.
- Export to JSON, CSV, or TSV.

### Changed

- The project, command, and Python package are now named `cja-audit-log-monitor` (package `cja_audit_log_monitor`). The config folder is now `~/.cja-audit-log-monitor/`.
- The TUI layout is cleaner. Charts are colored by action, controls take one row, and the dashboard uses two columns.
- The header shows the real connection state, and views explain when there is no data or no connection.

### Fixed

- The TUI main pane no longer renders blank.
- The entry detail panel in the log browser no longer crashes when it opens.
- The log table no longer scrolls sideways.

[Unreleased]: https://github.com/brian-a-au/cja-audit-log-monitor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/brian-a-au/cja-audit-log-monitor/releases/tag/v0.1.0
