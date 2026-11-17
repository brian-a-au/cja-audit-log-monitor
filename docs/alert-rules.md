# Alert Rules

Alert rules detect suspicious patterns across audit activity and are evaluated by both the TUI's [Real-Time Monitor](screens/monitor.md) and the CLI's `cja-audit-log-monitor cli alerts test` / `cja-audit-log-monitor cli monitor` commands. The same engine powers both.

## Where rules live

Rules are defined in `~/.cja-audit-log-monitor/config.yaml`. Run `uv run cja-audit-log-monitor cli init` to create the file with sensible defaults, then edit it.

## Schema

```yaml
alert_rules:
  - name: bulk_delete
    description: Alert on multiple delete operations
    enabled: true
    actions:
      - DELETE
    threshold_count: 5
    threshold_window_minutes: 60

  - name: sensitive_export
    description: Alert on data exports
    enabled: true
    actions:
      - EXPORT
    threshold_count: 3
    threshold_window_minutes: 30

  - name: off_hours_activity
    description: Activity outside business hours
    enabled: true
    threshold_count: 10
    threshold_window_minutes: 60
```

## Field reference

| Field | Required | Purpose |
|---|---|---|
| `name` | yes | Stable identifier — used by `enable_rule` / `disable_rule` and shown on the Alerts screen |
| `description` | no | Human-readable summary shown on the rule card |
| `enabled` | no (defaults to `true`) | Initial state when the engine loads. Toggle at runtime from the [Alerts screen](screens/alerts.md) |
| `actions` | no | Action types the rule watches. Omit or leave empty for "all actions". See valid values in [Reference](reference.md) |
| `components` | no | Component types the rule watches. Same semantics as `actions` |
| `threshold_count` | yes | How many matching events trigger an alert |
| `threshold_window_minutes` | yes | The rolling window the count is evaluated against |

A rule fires when **`threshold_count` or more matching events** occur within **`threshold_window_minutes`**.

## Testing rules

```bash
uv run cja-audit-log-monitor cli alerts test --days 1
```

Or open the [Alerts screen](screens/alerts.md) in the TUI and click `test rules`. Either path runs every enabled rule against the last 24 hours of audit data and reports what would have fired.

## Tips

- **Toggle, don't delete** — the [Alerts screen](screens/alerts.md) lets you enable/disable rules per session without touching YAML, useful during planned change windows where one rule would otherwise be noisy.
- **Off-hours rules need timezone awareness** — by default, "off-hours" thresholds are evaluated against UTC timestamps; tune `threshold_count` accordingly if your org concentrates in a single business region.
- **Start with the bundled defaults** — they're tuned to surface real signal (bulk deletes, sensitive exports, anomalous volume) without flooding the alert summary.

## Delivery channels

Fired alerts can optionally be delivered to external channels via the `notifications:` block in `~/.cja-audit-log-monitor/config.yaml`.

```yaml
notifications:
  slack_webhook_url: https://hooks.slack.com/services/XXX/YYY/ZZZ
  notify_on_alerts: true
  notify_on_anomalies: true   # opt-in; fires from `cja-audit-log-monitor cli anomalies`
  webhooks:
    - url: https://example.com/webhook
      enabled: true
      method: POST
      headers:
        Authorization: Bearer your-token
      timeout: 30
      include_entry_details: true
```

| Field | Purpose |
|---|---|
| `slack_webhook_url` | Slack incoming webhook URL. One per org. |
| `notify_on_alerts` | Master toggle for rule-based alert delivery. Default `true`. |
| `notify_on_anomalies` | Enable anomaly delivery via `cja-audit-log-monitor cli anomalies [--watch]`. Default `false` (opt-in). |
| `webhooks[].url` | Webhook target. Multiple supported. |
| `webhooks[].enabled` | Per-webhook toggle. Default `true`. |
| `webhooks[].method` | HTTP method. Default `POST`. |
| `webhooks[].headers` | Custom headers (e.g. `Authorization`). |
| `webhooks[].timeout` | Request timeout in seconds. Default `30`. |
| `webhooks[].include_entry_details` | Include the audit entry in the payload. Default `true`. |

Both the [Real-Time Monitor screen](screens/monitor.md) and the CLI's `cja-audit-log-monitor cli monitor` / `tail` dispatch to all configured channels when a rule fires. The first delivery failure per channel per session surfaces a one-time warning; subsequent failures are suppressed until the channel recovers (logs always record every failure).

### Anomaly delivery

Anomalies (`high_activity_user`, `bulk_delete_single_user`, `off_hours_activity`) are
detected by `analyze_for_anomalies` and dispatched via `cja-audit-log-monitor cli anomalies`.

- **Opt-in.** Set `notify_on_anomalies: true` in your `notifications:` block. Default
  is `false`.
- **Dedup.** Per-session in-memory fingerprint over `(type, identifying fields,
  today's date)`. Recurring anomalies whose counts grew between cycles still
  dedupe within a session. Dedup state is lost on process exit.
- **Day-bucket boundary.** An anomaly observed at 23:59 fingerprints differently
  at 00:01 the next day, so a long-running `--watch` loop will re-dispatch
  recurring patterns under the new day. This is intended.
- **Failure warnings.** Anomaly delivery shares the alert failure-warning channel:
  one warning per channel per session, then silenced.
- **TUI Dashboard.** The Dashboard's Recent Anomalies block remains a passive
  review surface and does not dispatch.

See [CLI Reference → `anomalies`](cli.md#anomalies--detect-and-deliver-anomalies) for the command flags.
