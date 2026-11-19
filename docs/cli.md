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
| `-v`, `--verbose` | Turn on debug logging. The log lines go to stderr. They never contain the client secret. |
| `-c`, `--config PATH` | Read the config file at `PATH` instead of the default file. See [Configuration](configuration.md#where-the-config-file-lives). |
| `--version` | Print the version and exit. |
| `--help` | Print the help and exit. |

There are two commands at the top level:

- `cja-audit-log-monitor cli <command>` runs a CLI command.
- `cja-audit-log-monitor tui` opens the TUI. This is the same as running `cja-audit-log-monitor` with no command.

## How the CLI behaves

### JSON output

These commands accept `-F json` (long form `--output-format json`): `list`, `search`, `query`, `user`, `component`, `dashboard`, `find-action`, `top-users`, `stats`, `timeline`, `anomalies`, `verify` and `alerts list`. The default is `-F table`.

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

- `verify` prints its result on stdout, including a failure such as `Connection failed` or `Authentication failed: ...`. It then exits 1. Errors that happen before the check starts, such as a config error, still go to stderr.
- `monitor` and `tail` print the entries and the status line on stdout. Their warnings about failed Slack or webhook delivery go to stderr.
- `anomalies` prints the anomalies it finds, and the line `No anomalies found in the last N hours.`, on stdout. Its delivery warnings go to stderr in every output format.

Names and other values from the API are shown exactly as they are. A component named `Q3 [/final] report` prints as `Q3 [/final] report`.

### Exit codes

| Code | Meaning |
|---|---|
| `0` | The command worked. |
| `1` | The command failed. This covers config errors, login errors, API errors and file errors. It also covers a failed `verify`, a closed pipe (for example `| head`), a `show` that did not find the entry, and a `monitor` or `tail` run where no poll worked. |
| `2` | The command line was wrong, e.g. an unknown flag, a value below the minimum, or a start date after the end date. Nothing is sent to the API. |

Each error prints one line to stderr that starts with its kind, e.g. `Configuration error:` or `API error:`. The one exception is `verify`, which prints its failures on stdout as described above. If you pipe the output into a command that stops reading early, e.g. `head -1`, the CLI exits 1 and prints no message.

### Dates and times

- `-s` / `--start-date` and `-e` / `--end-date` take a date such as `2026-11-01`. They also take a date and time such as `2026-11-01T09:30:00`.
- A value with no time zone is read as UTC.
- An end date with no time means the end of that day in UTC, so the whole day is included.
- You can give only one of the two dates. A missing end date means now. A missing start date means 2000-01-01.
- A start date after the end date is a usage error and exits 2.
- Times in CLI tables are in UTC.

### Defaults that come from the config file

When you leave `--days` off, a command uses `default_days` from the config file. It is 7 unless you change it. When you leave `--interval` off `monitor`, it uses `monitor_interval` from the config file. It is 60 unless you change it. The help shows these defaults as "from config".

The `default_page_size` setting is used only by the TUI log browser. The CLI does not use it.

### Short flags

Most short flags mean the same thing on every command. `-i` is the one exception:

- On `monitor` and `tail`, `-i` is `--interval`, the number of seconds between polls.
- On `dashboard` and `component`, `-i` is the id of the dashboard or the component.

Other rules for flag values:

- Choice values ignore case, so `find-action -a export` and `find-action -a EXPORT` are the same.
- Action and component names given with `-a` and `-C` also ignore case.
- Where the help says "can specify multiple", you can repeat the flag, e.g. `-a DELETE -a EXPORT`. The `-a` and `-C` flags of `search`, `export`, `query` and `timeline` can be repeated as well.
- Number flags have a minimum, which the help shows as `x>=1` or `x>=5`. A smaller value exits 2.
- A blank id, e.g. `-i ""`, exits 2.

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
| `-a`, `--action` | all | An action type. |
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
| `-a`, `--action` | all | An action type. |
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
- One poll reads at most 20 pages. If it reaches that limit, the tool logs a warning.
- A status line shows the time of the last poll and how many entries were new. After the first poll, it says `Baseline` and shows how many existing entries it found, because those are not counted as new.

How errors are handled:

- A 400, 401, 403 or 404 response, or a login error, stops the monitor with exit code 1.
- Any other error is shown in the status line, and the monitor tries again at the next interval.
- If no poll worked during the whole run, the monitor exits 1.

When the config file has a `notifications:` block, each alert that fires is also sent to Slack or to your webhooks. See [Delivery channels](alert-rules.md#delivery-channels).

### `tail`

Works like `monitor`, but shows only the entries that match the filters.

| Flag | Default | Meaning |
|---|---|---|
| `-i`, `--interval` | 5 | Seconds between polls. The minimum is 5. |
| `-u`, `--user` | all | A user id or an email address. |
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
| `--interval` | 300 | Seconds between scans with `--watch`. The minimum is 5. |
| `--lookback` | 24 | Hours of history to read in each scan. |
| `-F`, `--output-format` | `table` | `table` or `json`. See [JSON output](#json-output) for `--watch`. |

When a scan finds nothing, the command prints "No anomalies found in the last N hours."

The command always prints what it finds. It sends anomalies to Slack or webhooks only when the config file has a `notifications:` block and `notify_on_anomalies: true`. The default for `notify_on_anomalies` is `false`. See [Anomaly delivery](alert-rules.md#anomaly-delivery) for how repeats are skipped and how failures are reported.

## Export commands

### `export`

Exports audit logs to a file, or to stdout with `-o -`.

| Flag | Default | Meaning |
|---|---|---|
| `-F`, `--format` | `json` | `json`, `csv` or `tsv`. |
| `-o`, `--output` | required | The file to write, or `-` for stdout. |
| `-s`, `--start-date` | none | The start date. When you give a date, `--days` is not used. |
| `-e`, `--end-date` | none | The end date. |
| `-d`, `--days` | from config (7) | How many days to export when you give no dates. |
| `-a`, `--action` | all | An action type. You can repeat it. |
| `-C`, `--component` | all | A component type. You can repeat it. |
| `--pretty` / `--compact` | `--pretty` | Indent the JSON, or write it on one line. |
| `--max-entries` | no limit | The most entries to export. |
| `--force` | off | Overwrite the file if it exists. |

How the file is written:

- The tool checks the output path before it calls the API. It refuses a file that already exists unless you pass `--force`. It also refuses a folder that does not exist, and a folder given as the file name. Each of these prints one line and exits 1.
- The tool writes to a temporary file in the same folder and then moves it into place. If the export fails partway, no partial file is left, and an existing file stays as it was.
- A new file can be read only by you (mode 0600). It is written as UTF-8.
- If the target is a symbolic link, the tool replaces the link with the file. It does not write to the file the link points to.
- In CSV and TSV files, a cell that starts with `=`, `+`, `-`, `@`, a tab or a carriage return gets a `'` in front. This stops a spreadsheet from running the cell as a formula. A value such as `-5` also gets the `'`.
- `exported_at` in the JSON is in UTC.

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

Apart from `verify`, these commands have no flags other than `--help`.

| Command | What it does |
|---|---|
| `cli actions` | Lists the action types. |
| `cli components` | Lists the component types. |
| `cli config` | Shows the settings in use and the config file path. It never shows the secret. |
| `cli verify` | Logs in and makes one API call. On success it prints `Connection successful`, the organization, the API URL and the number of logs. On failure it exits 1. It also accepts `-F json`. |
| `cli init` | Creates the config file. It asks before it replaces a file that exists. See [Configuration](configuration.md#4-optional-create-a-config-file). |
