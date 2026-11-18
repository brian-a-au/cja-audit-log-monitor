# CLI Reference

For scripting and automation, a traditional CLI is available under the `cli` subcommand. The TUI is the default — running `cja-audit-log-monitor` with no arguments launches it. Everything documented here lives under `cja-audit-log-monitor cli ...`.

> Prefix commands with `uv run` (e.g. `uv run cja-audit-log-monitor cli list`) or activate the venv first (`source .venv/bin/activate`).

## Common operations

```bash
# List recent logs
cja-audit-log-monitor cli list --limit 100

# Search with filters
cja-audit-log-monitor cli search --user user@example.com --action DELETE

# Export to file
cja-audit-log-monitor cli export --format json --output audit_logs.json --days 30

# View statistics
cja-audit-log-monitor cli stats --days 7

# Real-time monitoring
cja-audit-log-monitor cli monitor --interval 30

# Detect and deliver anomalies
cja-audit-log-monitor cli anomalies --watch

# Generate report
cja-audit-log-monitor cli report --days 30 --output report.json
```

## Query commands

```bash
cja-audit-log-monitor cli list [--limit N] [--component TYPE] [--details]
cja-audit-log-monitor cli search [--user EMAIL] [--action TYPE] [--start-date DATE] [--end-date DATE]
cja-audit-log-monitor cli query [--today|--yesterday|--last-week|--last-month]
cja-audit-log-monitor cli user --user-id EMAIL [--days N]
cja-audit-log-monitor cli component --id ID [--type TYPE]
cja-audit-log-monitor cli dashboard --dashboard-id ID
cja-audit-log-monitor cli find-action --action TYPE [--days N]
cja-audit-log-monitor cli top-users [--days N] [--top N]
```

## Analysis commands

```bash
cja-audit-log-monitor cli stats [--days N] [--top N] [--output-format json|table]
cja-audit-log-monitor cli timeline [--days N] [--action TYPE] [--user EMAIL]
cja-audit-log-monitor cli report [--days N] [--output FILE]
```

When `--days` is left off, commands use `default_days` from the config file (7 unless changed). `cli monitor` does the same with `monitor_interval` for `--interval` (60 unless changed).

## Monitoring commands

```bash
cja-audit-log-monitor cli monitor [--interval N] [--duration N] [--no-alerts]
cja-audit-log-monitor cli tail [--user EMAIL] [--action TYPE] [--interval N]
cja-audit-log-monitor cli anomalies [--watch] [--interval N] [--lookback N]
```

> When `~/.cja-audit-log-monitor/config.yaml` defines a `notifications:` block (Slack and/or webhooks), each fired alert is also delivered to those channels. See [Alert Rules → Delivery channels](alert-rules.md#delivery-channels).

### `anomalies` — Detect and deliver anomalies

Run anomaly detection over recent audit logs and dispatch new findings to
configured notification channels.

```bash
cja-audit-log-monitor cli anomalies                    # one-shot scan
cja-audit-log-monitor cli anomalies --watch            # continuous loop
cja-audit-log-monitor cli anomalies --watch --interval 600 --lookback 48
```

**Flags:**

| Flag | Default | Description |
|---|---|---|
| `--watch` | off | Loop continuously; otherwise scan once and exit. |
| `--interval` | 300 | Positive number of seconds between `--watch` cycles. |
| `--lookback` | 24 | Positive number of hours of history to scan per cycle. |

The command runs detection and prints anomalies to the console regardless of
notification configuration. External delivery requires `notifications:` to be
configured **and** `notify_on_anomalies: true` (opt-in; default `false`). See
[Alert Rules → Anomaly delivery](alert-rules.md#anomaly-delivery) for dedup and
failure-warning behavior.

## Export commands

```bash
cja-audit-log-monitor cli export --output FILE [--format json|csv|tsv] [--days N]
```

## Alert commands

```bash
cja-audit-log-monitor cli alerts list [--output-format json|table]
cja-audit-log-monitor cli alerts test [--days N]
```

See [Alert Rules](alert-rules.md) for how rules are configured.

## Utility commands

```bash
cja-audit-log-monitor cli actions      # List action types
cja-audit-log-monitor cli components   # List component types
cja-audit-log-monitor cli config       # Show configuration
cja-audit-log-monitor cli verify       # Test API connection
cja-audit-log-monitor cli init         # Create config file
```

For valid `--action` and `--component` values, see the [Reference](reference.md).
