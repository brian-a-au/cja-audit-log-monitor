# Dashboard

The Dashboard is the home screen of the TUI — your at-a-glance situational view of the last 7 days of audit activity. Press `d` from anywhere to return here.

![Dashboard](../screenshots/dashboard.svg)

## What you see

- **Connection status**: a colored indicator confirming the CJA API is reachable and which Adobe org the session is bound to.
- **Stat cards**: total entries pulled, the date range covered, count of active users, and a count of recent anomalies (highlighted in warning color when non-zero).
- **Action distribution chart**: a horizontal bar chart of the top eight action types (CREATE / EDIT / DELETE / SHARE / EXPORT / etc.), color-coded to match the rest of the TUI.
- **Top 5 active users**: the most active accounts in the last 7 days with their action counts.
- **Recent anomalies**: up to five auto-detected unusual patterns (bulk deletes, off-hours activity, exports) flagged from the same window.
- **Last updated** timestamp and a `refresh` button.

## What you can do

- **Refresh on demand** — press `r` or click the `refresh` button to re-pull the last 7 days.
- **Verify connectivity** at a glance — if the indicator is red, you'll know before drilling into another screen.
- **Spot anomalies** that the alert engine surfaced from the most recent window without configuring rules first.
- **Pivot quickly** — press `l` to drill into the Log Browser, `s` for full statistics, `m` for live monitoring, or `a` to tune the rules that produced the anomalies list.

## Use cases & benefits

- **Daily standup view**: open the TUI, glance at totals + top users + anomalies, close it. No SQL, no dashboard build-out.
- **Incident first-look**: when a stakeholder asks "is something weird happening?", the dashboard answers in under a second — total volume, who's active, and whether anything tripped a rule.
- **Connectivity smoke test**: a working dashboard means OAuth, scopes, product profiles, and API access are all wired up correctly. If the dashboard renders, the rest of the app will work.
- **Lightweight by design**: only the most recent 1,000 entries are loaded so the screen is fast even on large orgs. Use the Statistics screen for longer windows.
