# Alert Rules

Alert rules detect suspicious patterns across audit activity and are evaluated by both the TUI's [Real-Time Monitor](screens/monitor.md) and the CLI's `cja-audit-log-monitor cli alerts test` / `cja-audit-log-monitor cli monitor` commands. The same engine powers both.

## Where rules live

Rules are defined in `~/.cja-audit-log-monitor/config.yaml`. Run `uv run cja-audit-log-monitor cli init` to create the file. The rules in it are commented out, so edit the file and remove the `#` marks to use them.

If the file defines no `alert_rules`, the tool uses four built-in rules. If the file defines any `alert_rules`, those rules replace the built-in ones completely. The built-in rules are not merged in.

| Built-in rule | What it watches | Fires at | Counted per user |
|---|---|---|---|
| `bulk_delete` | `DELETE` actions | 5 in 60 minutes | yes |
| `bulk_export` | `EXPORT` actions | 3 in 30 minutes | yes |
| `sensitive_component_delete` | `DELETE` of a data view, connection, filter, or calculated metric | 1 in 1 minute | no |
| `bulk_share` | `SHARE` actions | 10 in 60 minutes | yes |

## Schema

```yaml
alert_rules:
  - name: bulk_delete
    description: Multiple delete operations in short timeframe
    enabled: true
    actions:
      - DELETE
    threshold_count: 5
    threshold_window_minutes: 60
    per_user: true

  - name: sensitive_component_delete
    description: Deletion of sensitive components
    actions:
      - DELETE
    components:
      - DATA_VIEW
      - CONNECTION
    threshold_count: 1
    threshold_window_minutes: 1

  - name: contractor_exports
    description: Any export by a named account
    actions:
      - EXPORT
    users:
      - someone@example.com
    threshold_count: 1
    threshold_window_minutes: 1440
```

## Field reference

| Field | Required | Default | Purpose |
|---|---|---|---|
| `name` | yes | none | The rule's name. It is shown on the Alerts screen and in alert messages. |
| `description` | no | none | A short summary shown on the rule card and at the start of the alert message. |
| `enabled` | no | `true` | Whether the rule is on when the engine loads. |
| `actions` | no | none (all actions) | Action types the rule watches. Names are not case sensitive, so `delete` and `DELETE` are the same. A name that is not in the [reference](reference.md) is kept, but it writes a warning to the log. |
| `components` | no | none (all components) | Component types the rule watches. It works the same way as `actions`. |
| `threshold_count` | no | `1` | How many matching events fire the alert. It must be 1 or more. |
| `threshold_window_minutes` | no | `60` | The length of the time window, in minutes. It must be 1 or more. |
| `users` | no | none (all users) | Limits the rule to these people. Each entry can be an Adobe user id, an email address, or a display name. An event matches if any of its three values is in the list. |
| `per_user` | no | `false` | When `true`, each account is counted on its own, so five people deleting once each does not fire a rule that needs five deletes. Accounts are told apart by their id, not by their display name. |

A rule fires when **`threshold_count` or more matching events** happen within **`threshold_window_minutes`**. The window is measured by the time of the events themselves, not by the time you run the tool. After a rule fires, its count starts again from zero.

## Anomaly checks

Anomalies are separate from rules. They are checks that run over a batch of entries, and you cannot configure them in `alert_rules`. There are three:

- **`off_hours_activity`**: a burst of activity between midnight and 5am (00:00 up to, but not including, 05:00). The hour needs at least 5 actions and more than twice the average per hour. The CLI judges the hours in UTC. The TUI judges them in your local time zone.
- **`high_activity_user`**: one user with at least 20 actions, and more than three times the average of all the other users. It needs at least two users in the data.
- **`bulk_delete_single_user`**: one user with 11 or more deletes. Each user is checked on their own.

## Testing rules

```bash
uv run cja-audit-log-monitor cli alerts test --days 1
```

Or open the [Alerts screen](screens/alerts.md) in the TUI and click `test rules`. Either path runs every enabled rule against the last 24 hours of audit data and reports what would have fired.

## Tips

- **Toggles last until you quit.** The [Alerts screen](screens/alerts.md) lets you turn rules on and off without touching the YAML, which helps during a planned change window. These changes are kept only while the app is running. When you quit, the rules come back from the config file. The `reset rules` button rebuilds the rules from the config file (or the built-in rules if the file has none) right away.
- **Off-hours activity depends on the time zone.** The CLI judges the hours between midnight and 5am in UTC. The TUI dashboard judges them in your local time zone, the same zone its charts use. Each anomaly's description names the zone, for example "Unusual activity at 02:00 PST".
- **Use `per_user` for volume rules.** Without it, a rule counts events from everyone together, so a few people doing normal work can add up to an alert.

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
