# CLI Reference

The CLI is for scripts and automation. Every CLI command starts with `cja-audit-log-monitor cli`. Running `cja-audit-log-monitor` with no command opens the TUI instead.

Run any command with `--help` to see its flags and their defaults. The tables on this page come from that help.

## Common tasks

```bash
# List the 100 newest entries
cja-audit-log-monitor cli list --limit 100

# Search with filters
cja-audit-log-monitor cli search --user user@example.com --action DELETE

# Export the last 30 days to a JSON file
cja-audit-log-monitor cli export -F json -o audit_logs.json --days 30

# Show statistics for the last 7 days
cja-audit-log-monitor cli stats --days 7

# Watch for new events every 30 seconds
cja-audit-log-monitor cli monitor --interval 30

# Look for anomalies and send them to your notification channels
cja-audit-log-monitor cli anomalies --watch

# Write a report to a file
cja-audit-log-monitor cli report --days 30 -o report.json
```

## Options for the whole tool

These options go before `cli` or `tui`, e.g. `cja-audit-log-monitor -c ./config.yaml cli list`.

| Option | Meaning |
|---|---|
| `-v`, `--verbose` | Turn on debug logging. The log lines go to stderr. They never contain the client secret. This option affects the CLI only. The TUI has no log file and shows warnings as toasts. |
| `-c`, `--config PATH` | Read the config file at `PATH` instead of the default file. The file can be YAML or JSON. If it holds a credential, that credential is used. See [Configuration](configuration.md#where-the-config-file-lives). |
| `--profile NAME` | Use the credential in the profile `~/.cja/orgs/NAME/config.json`. The tool reads the file and never writes it. You cannot give `--profile` and `-c` together. See [Profiles](configuration.md#profiles). |
| `--version` | Print the version and exit. |
| `--help` | Print the help and exit. |

There are two commands at the top level:

- `cja-audit-log-monitor cli <command>` runs a CLI command.
- `cja-audit-log-monitor tui` opens the TUI. This is the same as running `cja-audit-log-monitor` with no command.

## How the CLI behaves

### JSON output

These commands accept `-F json` (long form `--output-format json`): `list`, `search`, `query`, `user`, `component`, `dashboard`, `find-action`, `top-users`, `stats`, `timeline`, `anomalies`, `config`, `verify` and `alerts list`. The default is `-F table`.

With `-F json`, the command writes one valid JSON document to stdout. Long values are not wrapped, and brackets in names are kept as they are. You can pipe the output straight into another tool, e.g. `cja-audit-log-monitor cli list -F json | jq '.entries[0]'`.

`anomalies --watch -F json` is different. It writes one compact JSON object on one line for each scan. Each object has two keys:

- `anomalies` is the list of new anomalies found in that scan.
- `count` is the number of new anomalies.

Some commands have their own output rules:

- `export` uses `-F` to choose between `json`, `csv` and `tsv`.
- `report` always writes JSON.
- `monitor` and `tail` have no JSON mode. They print their status lines to stdout.

### stdout and stderr

Data goes to stdout. Progress lines, warnings, errors and `-v` log lines go to stderr. This means you can redirect the data to a file and still see the messages on your screen. These cases are different:

- `verify` prints its result on stdout, including a failure such as `Connection failed` or `Authentication failed: ...`. It then exits 1. Errors that happen before the check starts, such as a config error or a missing credential, still go to stderr.
- `monitor` and `tail` print the entries and the status line on stdout. Their warnings about failed Slack or webhook delivery go to stderr.
- `anomalies` prints the anomalies it finds, and the line `No anomalies found in the last N hours.`, on stdout. Its delivery warnings go to stderr in every output format.

Names and other values from the API are shown exactly as they are. A component named `Q3 [/final] report` prints as `Q3 [/final] report`.

Output works with any stdout encoding. If the console cannot show a character, it prints as `?`. `export -o -` always writes UTF-8, so the exported data is never changed.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | The command worked. |
| `1` | The command failed. This covers config errors, login errors, API errors and file errors. It also covers a failed `verify`, a closed pipe (for example `| head`), a `show` that did not find the entry, and a `monitor` or `tail` run where no poll worked and you did not press Ctrl+C. |
| `2` | The command line was wrong, e.g. an unknown flag, a value below the minimum, or a start date after the end date. Nothing is sent to the API. |

Each error prints one line to stderr that starts with its kind, e.g. `Configuration error:` or `API error:`. The one exception is `verify`, which prints its failures on stdout as described above. Some messages say more:

- A 403 response adds a hint to check that the service account is in a product profile with CJA access in the Admin Console.
- When the tool cannot reach Adobe, to log in or to call the API, the line reads `Network error: could not reach <host>`.
- A login failure in `verify` reads `Authentication failed:` and the reason.
- An error the tool does not expect prints one line, `Unexpected error: <type>: <message>`. Add `-v` to see the full traceback. If you pipe the output into a command that stops reading early, e.g. `head -1`, the CLI exits 1 and prints no message.

### Dates and times

- `-s` / `--start-date` and `-e` / `--end-date` take a date as `YYYY-MM-DD`, e.g. `2026-11-01`, or as `YYYYMMDD`, e.g. `20261101`. They also take an ISO date and time such as `2026-11-01T09:30:00`. Any other form, e.g. `2026-1-5`, is a usage error and exits 2.
- A value with no time zone is read as UTC. A value with a time zone is changed to UTC.
- An end date with no time means the end of that day in UTC, so the whole day is included.
- You can give only one of the two dates. A missing end date means now. A missing start date means 2000-01-01.
- A start date after the end date is a usage error and exits 2.
- Times in CLI tables are in UTC.

### Defaults that come from the config file

When you leave `--days` off, a command uses `default_days` from the config file. It is 7 unless you change it. When you leave `--interval` off `monitor`, it uses `monitor_interval` from the config file. It is 60 unless you change it. The help says that these defaults come from the config file.

The `default_page_size` setting is used only by the TUI log browser. The CLI does not use it.

### Short flags

Most short flags mean the same thing on every command. `-i` is the one exception:

- On `monitor` and `tail`, `-i` is `--interval`, the number of seconds between polls.
- On `dashboard` and `component`, `-i` is the id of the dashboard or the component.

Other rules for flag values:

- Choice values ignore case, so `find-action -a export` and `find-action -a EXPORT` are the same.
- Action and component names given with `-a` and `-C` also ignore case.
- Where the help says "can be given more than once", you can repeat the flag, e.g. `-a DELETE -a EXPORT`.
- Number flags have limits, which the help shows, e.g. `x>=1` or `1<=x<=3650`. A value outside the limits exits 2. `--days` is at most 3,650 and `--lookback` is at most 87,600 hours.
- A blank id or filter, e.g. `-i ""` or `--user " "`, exits 2. This covers the id flags and the `--user`, `--component-id` and `--description` filters. Spaces at either end of a filter value are removed.

For valid action and component names, see the [Reference](reference.md), or run `cli actions` and `cli components`.

### Renamed short flags

Some short flags changed before version 0.1.0, so that each one means one thing. If you wrote scripts against an earlier build from source, update them.

| Command | Old flag | New flag |
|---|---|---|
| `tail` | `-c` for `--component-id` | `--component-id` (no short flag) |
| `monitor` | `-D` for `--duration` | `--duration` (no short flag) |
| `stats` | `-t` for `--top` | `-n` |
| `top-users` | `-t` for `--top` | `-n` |
| `export` | `-f` for `--format` | `-F` |
| `search` | no short flag for `--details` | `-D` |

`-c` now means only `--config`, and `-D` means only `--details`. Giving two `query` presets at once, e.g. `--today --yesterday`, is now a usage error.

## Query commands

### `list`

Lists the newest audit log entries.

| Flag | Default | Meaning |
|---|---|---|
| `-l`, `--limit` | 50 | The most entries to show. |
| `-C`, `--component` | all | Show only this component type. You can repeat it. |
| `-D`, `--details` | off | Add a Details column with the component name, the description and the IP address. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `search`

Searches the audit logs with filters. The API does the filtering.

| Flag | Default | Meaning |
|---|---|---|
| `-u`, `--user` | all | A user id or an email address. |
| `-a`, `--action` | all | An action type. You can repeat it. |
| `-s`, `--start-date` | none | The start date. See [Dates and times](#dates-and-times). |
| `-e`, `--end-date` | none | The end date. |
| `-C`, `--component` | all | A component type. You can repeat it. |
| `--component-id` | all | One component id. |
| `--description`, `--desc` | none | Text to look for in the entry description. |
| `-l`, `--limit` | 100 | The most entries to return. |
| `-D`, `--details` | off | Show the Details column, as in `list`. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `query`

Queries the logs for a preset date range. Pick at most one preset. With no preset, the command uses the last 7 days.

| Flag | Default | Meaning |
|---|---|---|
| `--today` | | From midnight UTC today until now. |
| `--yesterday` | | All of yesterday, in UTC. |
| `--last-week` | | The last 7 days. |
| `--last-month` | | The last 30 days. |
| `-u`, `--user` | all | A user id or an email address. |
| `-a`, `--action` | all | An action type. You can repeat it. |
| `-C`, `--component` | all | A component type. You can repeat it. |
| `-l`, `--limit` | 100 | The most entries to return. |
| `-F`, `--output-format` | `table` | `table` or `json`. |
| `-q`, `--quiet` | off | Print less, for scripts. |

### `user`

Shows the audit events of one user.

| Flag | Default | Meaning |
|---|---|---|
| `-u`, `--user-id` | required | A user id or an email address. |
| `-d`, `--days` | from config (7) | How many days to look back. |
| `-l`, `--limit` | 100 | The most entries to return. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `component`

Shows the audit events of one component.

| Flag | Default | Meaning |
|---|---|---|
| `-i`, `--id` | required | The component id. |
| `-t`, `--type` | any | The component type. |
| `-l`, `--limit` | 100 | The most entries to return. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `dashboard`

Shows the audit events of one Workspace project.

| Flag | Default | Meaning |
|---|---|---|
| `-i`, `--dashboard-id` | required | The project id. |
| `-l`, `--limit` | 100 | The most entries to return. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `find-action`

Finds every use of one action type.

| Flag | Default | Meaning |
|---|---|---|
| `-a`, `--action` | required | The action type. Case does not matter. |
| `-d`, `--days` | from config (7) | How many days to search. |
| `-l`, `--limit` | 50 | The most entries to show. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `top-users`

Shows the most active users.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--days` | from config (7) | How many days to look at. |
| `-n`, `--top` | 10 | How many users to show. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `show`

Shows every field of one entry.

```bash
cja-audit-log-monitor cli show ENTRY_ID
```

| Flag | Default | Meaning |
|---|---|---|
| `--max-entries` | 10000 | How many of the newest entries to search. |

The command reads the newest entries until it finds the id, and stops there. If it does not find the id, it prints how many entries it searched to stderr and exits 1.

## Analysis commands

### `stats`

Shows summary statistics.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--days` | from config (7) | How many days to look at. |
| `-n`, `--top` | 10 | How many top users to show. |
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `timeline`

Shows activity by day and by hour of the day, in UTC.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--days` | from config (7) | How many days to look at. |
| `-a`, `--action` | all | An action type. You can repeat it. |
| `-C`, `--component` | all | A component type. You can repeat it. |
| `-u`, `--user` | all | A user. |
| `-F`, `--output-format` | `table` | `table` or `json`. The JSON always has all 24 hours, even when they are 0. |

### `report`

Writes a full report as JSON. Without `-o`, the report goes to stdout.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--days` | from config (7) | How many days to look at. |
| `-o`, `--output` | stdout | The file to write. |
| `--pretty` / `--compact` | `--pretty` | Indent the JSON, or write it on one line. |
| `--max-entries` | 10000 | The most entries to read. |
| `--force` | off | Overwrite the file if it exists. |

The report says it is truncated only when there are more entries than `--max-entries`. With no entries, it still writes a JSON document. A file written with `-o` follows the same safety rules as [`export`](#export).

## Monitoring commands

### `monitor`

Polls the API for new events and prints each one. Press Ctrl+C to stop.

| Flag | Default | Meaning |
|---|---|---|
| `-i`, `--interval` | from config (60) | Seconds between polls. The minimum is 5. |
| `--duration` | no limit | Stop after this many seconds. |
| `--alerts` / `--no-alerts` | `--alerts` | Check each new event against the [alert rules](alert-rules.md). |

How each poll works:

- The first poll reads the last 5 minutes. It shows the newest 5 entries as context. It does not alert on them or count them as new.
- Each later poll reads from 5 minutes before the last good poll up to now. The tool skips entries it has already shown. This overlap catches events that the API indexed late.
- New events are handled oldest first.
- Each poll reads pages of 1,000 entries, so a normal poll is one request. One poll reads at most 50 pages, which is 50,000 events. After a long gap, e.g. a laptop asleep, the poll reads the whole gap up to that limit. Past it, the tool says how many older events were skipped.
- An event that the API indexes more than 5 minutes late is missed.
- Times on the entry lines and the status line are in UTC.
- A status line shows the time of the last poll and how many entries were new. For the first poll, it says `Baseline` and shows how many existing entries it found. After that it says how many entries are new.

How errors are handled:

- A 400, 401, 403 or 404 response, or a login error caused by bad or missing credentials, stops the monitor with exit code 1.
- A login that fails for a moment, e.g. a network error or an IMS answer of 429 or 5xx, is tried again at the next poll.
- Any other error is shown in the status line, and the monitor tries again at the next interval.
- If no poll worked during the whole run, the monitor exits 1.

Ctrl+C stops the monitor at once, even while a request or a webhook send is in progress. The entries of that poll are dropped. The command prints `Monitor stopped.` and exits 0.

When the config file has a `notifications:` block, each alert that fires is also sent to Slack or to your webhooks. See [Delivery channels](alert-rules.md#delivery-channels).

### `tail`

Works like `monitor`, but shows only the entries that match the filters. The filters apply before the alert rules, so events from other users or components never count toward a rule.

| Flag | Default | Meaning |
|---|---|---|
| `-i`, `--interval` | 5 | Seconds between polls. The minimum is 5. |
| `-u`, `--user` | all | A user id, email address or display name. Case does not matter, the same as for a rule's `users:` list. |
| `--component-id` | all | One component id. |
| `-a`, `--action` | all | An action type. You can repeat it. |
| `--alerts` / `--no-alerts` | `--alerts` | Check each new event against the alert rules. |

### `anomalies`

Looks for anomalies in recent logs and prints them. It can also send new anomalies to your notification channels. See [Anomaly checks](alert-rules.md#anomaly-checks) for what counts as an anomaly.

```bash
cja-audit-log-monitor cli anomalies                    # scan once
cja-audit-log-monitor cli anomalies --watch            # scan again and again
cja-audit-log-monitor cli anomalies --watch --interval 600 --lookback 48
```

| Flag | Default | Meaning |
|---|---|---|
| `--watch` | off | Keep scanning. Without it, the command scans once and exits. |
| `--interval` | 300 | Seconds between scans with `--watch`, 5 to 86,400. |
| `--lookback` | 24 | Hours of history to read in each scan. |
| `-F`, `--output-format` | `table` | `table` or `json`. See [JSON output](#json-output) for `--watch`. |

When a scan finds nothing, the command prints "No anomalies found in the last N hours."

With `--watch`, a failed scan is tried again at the next interval, the same as in `monitor`. A 400, 401, 403 or 404 response, or a login error caused by bad or missing credentials, stops the command with exit code 1, because trying again cannot fix it.

The command always prints what it finds. It sends anomalies to Slack or webhooks only when the config file has a `notifications:` block and `notify_on_anomalies: true`. The default for `notify_on_anomalies` is `false`. See [Anomaly delivery](alert-rules.md#anomaly-delivery) for how repeats are skipped and how failures are reported.

In every JSON output, a user count is an object with the keys `user` and `count`, e.g. `{"user": "someone@example.com", "count": 12}`. Hours of the day are the strings `"00"` to `"23"`.

## Export commands

### `export`

Exports audit logs to a file, or to stdout with `-o -`.

| Flag | Default | Meaning |
|---|---|---|
| `-F`, `--format` | from the file suffix | `json`, `csv` or `tsv`. Without `-F`, a `.csv` or `.tsv` file name chooses that format. Any other name gives JSON. |
| `-o`, `--output` | required | The file to write, or `-` for stdout. |
| `-s`, `--start-date` | none | The start date. When you give a date, `--days` is not used. |
| `-e`, `--end-date` | none | The end date. |
| `-d`, `--days` | from config (7) | How many days to export when you give no dates. |
| `-a`, `--action` | all | An action type. You can repeat it. |
| `-C`, `--component` | all | A component type. You can repeat it. |
| `--pretty` / `--compact` | `--pretty` | Indent the JSON, or write it on one line. |
| `--max-entries` | no limit | The most entries to export. If more entries matched, the tool says so on stderr. |
| `--force` | off | Overwrite the file if it exists. |

How the file is written:

- A `~` at the start of the path is read as your home folder.
- The tool checks the output path before it calls the API. It refuses a file that already exists unless you pass `--force`. It also refuses a folder that does not exist or that you cannot write to, a folder given as the file name, a path that ends with `/`, and a file name longer than 255 bytes. Each of these prints one line and exits 1.
- If a file appears at the path during the export, the tool stops with an error that names the file and `--force`.
- When no entries match, the tool still writes the file. A JSON file has no entries, and a CSV or TSV file has only the header row. So a scheduled export never leaves an older file in place.
- The file appears only when the export is complete. If the export stops early, e.g. by Ctrl+C, SIGTERM or SIGHUP, no file and no hidden temp file is left behind.
- The tool writes to a temporary file in the same folder and then moves it into place. If the export fails partway, no partial file is left, and an existing file stays as it was.
- A new file can be read only by you (mode 0600). It is written as UTF-8. JSON keeps text that is not ASCII as it is, and it ends with a newline.
- If the target is a symbolic link, the tool replaces the link with the file. It does not write to the file the link points to.
- In CSV and TSV files, a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a `'` in front. This stops a spreadsheet from running the cell as a formula. A value such as `-5` also gets the `'`.
- CSV and TSV files have these columns, in this order: `id`, `timestamp`, `user_id`, `user_email`, `user_name`, `action`, `component_type`, `component_id`, `component_name`, `description`, `org_id`, `ip_address` and `changes`.
- `changes` is a JSON object in a JSON file. In CSV and TSV it is one cell of compact JSON.
- TSV is plain. It uses no quotes, and a tab or a line break inside a cell becomes a space.
- `exported_at` and the timestamps in the JSON are in UTC.

With `-o -`, the data goes to stdout and every notice goes to stderr, e.g. `cja-audit-log-monitor cli export -F csv -o - > logs.csv`.

## Alert commands

### `alerts list`

Lists the alert rules that are loaded.

| Flag | Default | Meaning |
|---|---|---|
| `-F`, `--output-format` | `table` | `table` or `json`. |

### `alerts test`

Runs the alert rules and the anomaly checks against recent logs, and prints what would have fired. It does not send notifications.

| Flag | Default | Meaning |
|---|---|---|
| `-d`, `--days` | 1 | How many days of logs to test. |

See [Alert Rules](alert-rules.md) for how to write rules.

## Other commands

`config` and `verify` accept `-F json`. Apart from that, these commands have no flags other than `--help`.

| Command | What it does |
|---|---|
| `cli actions` | Lists the action types. |
| `cli components` | Lists the component types. |
| `cli config` | Shows the settings in use, the config file path and where the credential comes from. It makes no network call and never shows the secret. See [Check the credential](#check-the-credential). |
| `cli verify` | Signs in and fetches one audit log entry, and reports the two results separately. On failure it exits 1. See [Check the credential](#check-the-credential). |
| `cli init` | Creates the config file. It asks before it replaces a file that exists. See [Configuration](configuration.md#4-optional-create-a-config-file). |

### Check the credential

`cli config` shows how the tool finds the credential, without a call to Adobe. It prints the source that gave the credential, the organization ID, the client ID, whether the secret is set, and the scopes. The client ID shows its first 4 and last 4 characters, e.g. `aaaa****4444`. The secret shows as `****`. A source that holds a credential and was not used is listed as `Not used`.

`cli config -F json` writes the same facts as one JSON document. These are its keys:

- `schema` is `adobe-credentials/v1/config-check`.
- `tool`, `tool_version` and `product` name the tool. `product` is `cja`.
- `ok` is true when a credential was found and there is no problem.
- `profile` is the name of the profile in use, or null.
- `sources` lists every source that holds a credential field, highest first. Each one has `kind`, `name`, `path`, `used`, `fields` and `skipped`. `fields` holds the names of the fields and never their values. A source with only some of the fields has `skipped` set to `partial` and a `missing` list.
- `credential` holds `org_id`, the masked `client_id`, `secret_set` and `scopes`.
- `problems` lists what is wrong. Each one has a `code` and a `message`. The codes are `no_credential`, `partial_source`, `profile_not_found`, `invalid_profile_name` and `profile_and_config_both_given`.
- `notices` is always an empty list in this tool.

`cli config` exits 0 when it finds no credential, and `ok` is false. It exits 1 when the lookup fails, e.g. when a profile does not exist. With `-F json` it still writes the document on stdout before it exits 1.

`cli verify` tests the credential in two steps and reports each one:

- **Sign-in** asks Adobe's sign-in service for a token.
- **Log fetch** asks the audit log API for one entry with that token. It does not run when sign-in fails.

A failed step shows a code and what to do about it, e.g. `Sign-in: failed (bad_secret)`. These are the codes:

| Code | Step | Meaning |
|---|---|---|
| `bad_client_id` | Sign-in | Adobe does not know the client ID. |
| `bad_secret` | Sign-in | Adobe knows the client ID and rejected the secret. |
| `scopes_rejected` | Sign-in | Adobe rejected one or more scopes. |
| `sign_in_failed` | Sign-in | Sign-in failed for another reason. The message holds Adobe's own text, cut to 200 characters. |
| `no_product_access` | Log fetch | The audit log API answered 401 or 403. Add the Customer Journey Analytics API and the Adobe Experience Platform API to the credential, and add its technical account to a CJA product profile. |
| `unreachable` | Either | The tool could not reach Adobe, or the answer was not one it could read. |

`cli verify -F json` writes one JSON document with these keys:

- `schema` is `adobe-credentials/v1/live-test`.
- `tool`, `tool_version` and `product` name the tool.
- `ok` is true when both steps worked.
- `source` holds the `kind` and `name` of the source that gave the credential.
- `sign_in` and `product_access` each hold `ok`, `code` and `message`. `ok` is null when the step did not run. `code` is null when the step worked.
- `org_id` and `api_url` are the organization and the API address that were tested.
- `total_logs_available` is the number of logs, when the log fetch worked.
