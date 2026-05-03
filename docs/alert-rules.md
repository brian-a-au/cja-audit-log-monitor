# Alert Rules

Alert rules detect suspicious patterns across audit activity and are evaluated by both the TUI's [Real-Time Monitor](screens/monitor.md) and the CLI's `cja-audit cli alerts test` / `cja-audit cli monitor` commands. The same engine powers both.

## Where rules live

Rules are defined in `~/.cja-audit/config.yaml`. Run `uv run cja-audit cli init` to create the file with sensible defaults, then edit it.

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
uv run cja-audit cli alerts test --days 1
```

Or open the [Alerts screen](screens/alerts.md) in the TUI and click `Test Rules`. Either path runs every enabled rule against the last 24 hours of audit data and reports what would have fired.

## Tips

- **Toggle, don't delete** — the [Alerts screen](screens/alerts.md) lets you enable/disable rules per session without touching YAML, useful during planned change windows where one rule would otherwise be noisy.
- **Off-hours rules need timezone awareness** — by default, "off-hours" thresholds are evaluated against UTC timestamps; tune `threshold_count` accordingly if your org concentrates in a single business region.
- **Start with the bundled defaults** — they're tuned to surface real signal (bulk deletes, sensitive exports, anomalous volume) without flooding the alert summary.
