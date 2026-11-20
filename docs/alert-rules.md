# Alert Rules

Alert rules look for suspicious patterns in audit activity. The TUI [Real-Time Monitor](screens/monitor.md) checks them, and so do the CLI commands `monitor`, `tail` and `alerts test`. All of them use the same rule code, so a rule behaves the same way everywhere.

## Where rules live

Rules are defined in the config file, which is `~/.cja-audit-log-monitor/config.yaml` unless you choose another path (see [Where the config file lives](configuration.md#where-the-config-file-lives)). Run `cja-audit-log-monitor cli init` to create the file. It holds the four built-in rules, commented out. Remove the `#` marks to use them and change them.

If the file has no `alert_rules` key, the tool uses the four built-in rules. If the file defines any `alert_rules`, those rules replace the built-in ones completely. The built-in rules are not merged in. `alert_rules: []` means no rules at all.

Two rules with the same name are a config error. A key inside a rule that the tool does not know, e.g. a typo such as `treshold_count`, gives a warning that names the rule, e.g. `alert_rules[0]: ignoring unknown setting 'treshold_count'`.

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
| `name` | yes | none | The rule's name. It is shown in the alerts view and in alert messages. Each rule needs its own name. |
| `description` | no | none | A short summary shown on the rule card and at the start of the alert message. |
| `enabled` | no | `true` | Whether the rule is on when the engine loads. |
| `actions` | no | none (all actions) | Action types the rule watches. Names are not case sensitive, so `delete` and `DELETE` are the same. A name that is not in the [reference](reference.md) is kept, but it gives a warning. An empty list is an error. Leave the key out to watch all actions. |
| `components` | no | none (all components) | Component types the rule watches. It works the same way as `actions`, and an empty list is also an error. |
| `threshold_count` | no | `1` | How many matching events fire the alert. It must be 1 or more. |
| `threshold_window_minutes` | no | `60` | The length of the time window, in minutes. It must be 1 to 525,600 (one year). |
| `users` | no | none (all users) | Limits the rule to these people. Each entry can be an Adobe user id, an email address, or a display name. An event matches if any of its three values is in the list. The match ignores case and spaces at either end. An empty list is an error. Leave the key out to match all users. |
| `per_user` | no | `false` | When `true`, each account is counted on its own, so five people deleting once each does not fire a rule that needs five deletes. The tool tells accounts apart by their account id, not by their display name, so two people with the same name are counted apart. |

A rule fires when **`threshold_count` or more matching events** happen within **`threshold_window_minutes`**. The window is measured by the time of the events themselves, not by the time you run the tool. After a rule fires, its count starts again from zero. An event with a time more than 5 minutes ahead of your computer's clock counts as happening now.

## Anomaly checks

Anomalies are separate from rules. They are checks that run over a batch of entries, and you cannot configure them in `alert_rules`. There are three checks:

- **`off_hours_activity`** finds a burst of activity between midnight and 5am (from 00:00 up to, but not including, 05:00). The hour needs at least 5 actions and more than twice the average per hour. The CLI judges the hours in UTC. The TUI judges them in your local time zone.
- **`high_activity_user`** finds one user with at least 20 actions, and more than three times the average of all the other users. It needs at least two users in the data.
- **`bulk_delete_single_user`** finds each user with 11 or more deletes. Each user is checked on their own.

## Testing rules

```bash
cja-audit-log-monitor cli alerts test --days 1
```

This command runs every enabled rule against the last day of audit data and reports what would have fired. `--days` sets how many days to test. The command also runs the anomaly checks. It does not send notifications.

You can also open the [alerts view](screens/alerts.md) in the TUI and click `test rules`. The view tests up to 1,000 entries from the last 24 hours. The test uses a separate copy of the rules, so it does not change the counts of a running monitor and does not send notifications.

## Tips

- **Toggles last until you quit.** In the [alerts view](screens/alerts.md) you can turn rules on and off without editing the config file, e.g. during a planned change. The tool keeps these changes only while the app runs. A rule you turned off stays off after **reload settings**. When you quit, the rules come back from the config file. The `reset rules` button rebuilds the rules from the config file right away. If the file has no rules, it rebuilds the built-in rules.
- **Off-hours activity depends on the time zone.** The CLI judges the hours between midnight and 5am in UTC. The TUI dashboard judges them in your local time zone, the same zone its charts use. Each anomaly's description names the zone, for example "Unusual activity at 02:00 PST". When the hour holds times from both sides of a daylight saving change, it names both, for example "Unusual activity at 01:00 EDT/EST".
- **Use `per_user` for volume rules.** Without it, a rule counts events from everyone together, so a few people doing normal work can add up to an alert.

## Delivery channels

The tool can send alerts that fire to Slack and to webhooks. You set this up in the `notifications:` block of the config file.

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
| `slack_webhook_url` | The URL of a Slack incoming webhook. You can set one. |
| `notify_on_alerts` | Whether to send alerts from rules. The default is `true`. |
| `notify_on_anomalies` | Whether `cja-audit-log-monitor cli anomalies` sends anomalies. The default is `false`. |
| `webhooks[].url` | The URL to send to. You can list more than one webhook. |
| `webhooks[].enabled` | Whether this webhook is used. The default is `true`. |
| `webhooks[].method` | The HTTP method. The default is `POST`. |
| `webhooks[].headers` | Extra headers to send, e.g. `Authorization`. |
| `webhooks[].timeout` | How many seconds to wait for a reply, from 1 to 300. The default is `30`. |
| `webhooks[].include_entry_details` | Whether to include the audit entry in the message. The default is `true`. |

When a rule fires, the TUI [monitor view](screens/monitor.md) and the CLI commands `monitor` and `tail` send it to every channel you set up.

A key in the `notifications:` block or in a webhook that the tool does not know gives a warning that names where it is, e.g. `notifications.webhooks[0]: ignoring unknown setting 'methd'`.

When a send to a channel fails, you see one warning for that channel. Each failing channel gets its own warning, labelled with its name, e.g. `slack (https://hooks.slack.com/…)` or `webhook 2 (https://example.com/…)`. Webhooks are counted from 1 in the order of the config file. The warning reads `Notification delivery failed (<label>). This warning shows again if the channel fails after it works again.` Later failures on that channel show no warning until a send to it works again. Each failed send also prints a short line that starts with `Failed to send`. The CLI prints it on stderr, and the TUI shows it as a toast.

The tool keeps your channels private and safe:

- Webhook and Slack URLs are hidden in logs and in failure messages.
- User names and other text from the API are escaped in Slack messages. A name such as `<!channel>` shows as text and does not notify the channel.

### Anomaly delivery

The anomaly checks are `high_activity_user`, `bulk_delete_single_user` and `off_hours_activity`. Only `cja-audit-log-monitor cli anomalies` sends anomalies to your channels.

- **You must turn it on.** Set `notify_on_anomalies: true` in your `notifications:` block. The default is `false`.
- **Each anomaly reaches each channel once.** While the command runs, it remembers which channels have accepted each anomaly, by its type and the user or other details. A channel that accepted an anomaly does not get it again, even if its count grows. A channel that failed gets it again on the next scan. The command forgets this when it exits.
- **A new day does not send again.** An anomaly that continues past midnight is not sent again.
- **An anomaly that comes back is sent again.** When a scan no longer finds an anomaly, the command forgets it. If a later scan finds it again, it is sent again.
- **Failure warnings work the same way as for alerts.** You see one warning for each failing channel.
- **The TUI does not send anomalies.** The dashboard's recent anomalies list is only for you to look at.

See [CLI Reference, `anomalies`](cli.md#anomalies) for the command flags.
