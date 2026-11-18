# Changelog

All notable changes to this project are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- A slideshow of the app at the top of the README. `scripts/make_showcase.py` makes it from synthetic data.

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
- Entries from the live API now show their user and component. The API sends these as nested objects, which the app did not read before. This also fixes the user list, the component alert rules, and exports.
- Paging works against the live API. The app sent `page`, which the API ignores, so every page showed the first page.
- Filtering by an email address works. The app now sends emails as `userEmail`, because the API matches `userId` only against IMS user IDs.
- The dashboard and statistics show the true number of entries in the window, and say when the charts use only the newest entries.
- The app no longer crashes when the export dialog closes itself after an export.
- Component types `IMAGE`, `CONTAINER` and `FULL_TABLE_EXPORT`, and actions `FAVORITE`, `UNFAVORITE`, `PIN` and `LABEL`, are now known. You can filter by them and name them in alert rules.
- Users are counted per account, so two accounts with the same display name stay separate. Alert rules match a user by IMS ID, email or name.
- The dashboard's active users count includes every account, not just the top 10.
- `n` on the last page of the log browser no longer goes past the end.
- Paging skips entries repeated across pages when new events arrive mid-fetch.
- Views name the kind of failure: not connected, access denied, request rejected, or could not load data. The header updates when any view loses or regains the connection.
- In the TUI, off-hours anomalies use your local hours, and every off-hours anomaly names its time zone.
- CLI commands that fetch every entry ask for pages of 1,000, the API's largest, so they make about ten times fewer requests.
- CLI tables, entry details and alerts say their times are in UTC. At 80 columns the CLI table keeps the time, action and component type whole.
- In the TUI, the top users list, the daily chart and the user ranking fit their column at any width. Long values in the entry detail panel wrap inside their own column.
- The narrow hourly chart keeps its 23 label, and time zone names refresh on each load.

### Added in the TUI

- Export can save every entry that matches the filters, up to 10,000, not only the current page.
- The help overlay lists every key, including `n`, `p` and `space`.
- All times in the TUI are in your local time zone, and the zone is named, e.g., `time (PST)`.
- The sidebar shows the key for each view, so the footer has room for the actions.

[Unreleased]: https://github.com/brian-a-au/cja-audit-log-monitor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/brian-a-au/cja-audit-log-monitor/releases/tag/v0.1.0
