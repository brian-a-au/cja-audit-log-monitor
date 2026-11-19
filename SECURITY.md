# Security policy

## Supported versions

Only the latest release receives security fixes.

## Reporting a vulnerability

Report privately through
[GitHub private vulnerability reporting](https://github.com/brian-a-au/cja-audit-log-monitor/security/advisories/new).
The repository setting is enabled, so outside reporters can open a private
report without repository access.

Do not open a public issue for a vulnerability. Include the affected version,
the impact, the steps to reproduce it, and any suggested fix. Do not add
credentials, tokens, webhook URLs, audit log entries, or other data from Adobe.
The maintainer aims to acknowledge a report within one week.

## What the tool protects

The tool holds Adobe OAuth credentials, and it reads audit log data that names
users, components and IP addresses. It treats that data as unsafe and protects
these things:

- **Credentials.** The secret and the access token are never printed, logged,
  stored or shown in an error message or a traceback. The config file is created
  so that only you can read it (mode 0600), and the tool warns when other users
  can read it.
- **Notification URLs.** Slack and webhook URLs can hold a secret, so messages and
  logs show only the scheme and the host, e.g. `https://hooks.slack.com/…`.
- **Your terminal.** Control characters in audit data, e.g. terminal escape
  sequences in a component name, are replaced before any output. Text from the
  data is never read as Rich or Textual markup.
- **Files you export.** Export files can be read only by you (mode 0600). A CSV or
  TSV cell that a spreadsheet could read as a formula starts with `'`. An export
  never follows a symbolic link, and it replaces an existing file only with
  `--force` in the CLI or your confirmation in the TUI.
- **Adobe.** The tool only reads from the CJA audit log API. It never changes data
  in Adobe.

A way around any of these protections is in scope. So is a way to make the tool
change data in Adobe, or reveal a credential, a token or a notification URL.
