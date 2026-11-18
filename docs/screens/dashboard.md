# Dashboard

The Dashboard is the home screen of the TUI — your at-a-glance situational view of the last 7 days of audit activity. Press `d` from anywhere to return here.

![Dashboard](../screenshots/dashboard.svg)

## What you see

- **Connection status** (in the header row, on every screen): `connecting`, `connected` with the Adobe org, or `disconnected` with the first line of the error. Any view that loses the connection updates it, and the next successful load sets it back to `connected`.
- **Stat cards**: the total number of entries in the last 7 days, the number of active users, the number of recent anomalies (highlighted in warning color when non-zero), and the dates of the window.
- **A sample note** under the cards when the window has more than 1,000 entries. The charts and lists then use the newest 1,000 entries, and the note says so.
- **Left column**: an action distribution chart (bars colored by action severity, with counts and percentages) and an hourly activity chart in your local time zone.
- **Right column**: the top active users in the last 7 days with their action counts, and recent anomalies.
- **Recent anomalies**: up to five auto-detected unusual patterns (bulk deletes, off-hours activity, exports) flagged from the same window. The Dashboard shows recent anomalies as a passive review surface — the TUI does not dispatch them. To dispatch anomalies to Slack/webhooks, run `cja-audit-log-monitor cli anomalies [--watch]` (see [CLI Reference → `anomalies`](../cli.md#anomalies--detect-and-deliver-anomalies) and [Alert Rules → Anomaly delivery](../alert-rules.md#anomaly-delivery)).
- **Last updated** timestamp and a `refresh` button.

## What you can do

- **Refresh on demand** — press `r` or click the `refresh` button to re-pull the last 7 days.
- **Verify connectivity** at a glance — if the header indicator is red, the dashboard shows the error and points you to the config screen (`c`) or `cja-audit-log-monitor cli verify`.
- **Spot anomalies** that the alert engine surfaced from the most recent window without configuring rules first.
- **Pivot quickly** — press `l` to drill into the Log Browser, `s` for full statistics, `m` for live monitoring, or `a` to tune the rules that produced the anomalies list.

## Use cases & benefits

- **Daily standup view**: open the TUI, glance at totals + top users + anomalies, close it. No SQL, no dashboard build-out.
- **Incident first-look**: when a stakeholder asks "is something weird happening?", the dashboard answers in under a second — total volume, who's active, and whether anything tripped a rule.
- **Connectivity smoke test**: a working dashboard means OAuth, scopes, product profiles, and API access are all wired up correctly. If the dashboard renders, the rest of the app will work.
- **Lightweight by design**: the charts use at most the newest 1,000 entries, which takes one API request, so the screen is fast even on large orgs. The total still counts every entry in the window. Use the Statistics screen for more entries or longer windows.
