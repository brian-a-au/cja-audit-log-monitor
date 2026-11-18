# Settings

The Settings screen is a read-only view of the active configuration plus a one-click connection check. It's the first place to look when something doesn't behave as expected. Press `c` to open it.

![Settings](../screenshots/settings.svg)

## What you see

- **Connection status**: green dot + org ID + API URL + total logs available when authenticated; red dot + error string when not.
- **API configuration**: the resolved config file path (your home folder is shown as `~`), the CJA API base URL, and the IMS base URL.
- **Authentication**: organization ID (truncated), client ID (truncated), and an `oauth configured` yes/no indicator. Secrets are never displayed.
- **Defaults**: `default_page_size`, `default_days` and `monitor_interval`. The log browser shows that many rows per page (the CLI does not use this setting), the dashboard and stats look back that many days, and the monitor interval box starts at that interval. The same values are the CLI defaults for `--days` and `--interval` (monitor).
- **Alert rules**: the count of rules currently configured (full detail lives on the Alerts screen).
- **Notifications**: presence indicators for the `notifications:` block — Slack (`configured` / `not configured`), webhook count, and the `notify_on_alerts` / `notify_on_anomalies` toggle states. No URLs or secrets shown — safe to screen-share.
- **Action buttons**: `verify connection` and `reload settings`. Sections are laid out in a two-column grid.

## What you can do

- **Verify the API end-to-end** with `verify connection` — runs the same OAuth handshake and ping that the CLI's `cja-audit-log-monitor cli verify` uses, but right inside the TUI.
- **Refresh settings** after editing `.env` or `~/.cja-audit-log-monitor/config.yaml` — `reload settings` re-reads the config file, rebuilds the client, and applies the new page size, days and monitor interval to the views you have already opened (they reload). It is refused while the monitor is running.
- **Confirm credential precedence**: the displayed org ID and client ID prefixes tell you which credentials the app actually loaded — useful when env vars and config files might both be in play.
- **Sanity-check the API target** before assuming a bug is in the tool — wrong API base URL is a common misconfiguration.

## Use cases & benefits

- **First-line troubleshooting**: when a screen shows no data, open Settings. A red connection status with an error string is almost always more actionable than a silent empty table elsewhere.
- **Onboarding check**: after running through the README's credential setup, `Settings → verify connection` is the moment you confirm the OAuth project is wired up correctly.
- **No-restart workflow**: editing the config file and clicking `reload settings` is faster than killing the TUI, and avoids losing any in-session state.
- **Safe to share over a screen-share**: secrets are masked, so you can show this screen to a teammate without redacting a single field.
