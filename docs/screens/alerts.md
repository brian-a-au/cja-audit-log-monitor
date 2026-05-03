# Alert Rules

The Alert Rules screen lets you toggle, inspect, and test the rules that detect suspicious patterns in audit activity. Rules apply to the live Monitor, the Dashboard's anomaly list, and any CLI alert commands. Press `a` to open it.

![Alerts](../screenshots/alerts.svg)

## What you see

- **Title and helper text** explaining the screen's purpose.
- **Rule cards**: one card per configured rule, each with:
  - A checkbox to enable / disable the rule.
  - The rule's description.
  - The detection threshold (`N events in M minutes`).
  - The action types and component types the rule watches (`All` if unrestricted).
  - A subtle border colour indicating enabled vs disabled state.
- **Action buttons**: `Test Rules` and `Reset to Defaults`.
- **Test results panel** that fills in after a test run with a count of triggered alerts (or a `no alerts triggered` confirmation).

## What you can do

- **Toggle rules on/off** with the per-rule checkbox — changes take effect immediately for live Monitor sessions.
- **Test rules against the last 24 hours** by clicking `Test Rules`. The screen pulls up to 1,000 recent entries, runs every enabled rule against them, and reports whether they would have fired.
- **Reset to defaults** to wipe any in-session changes and reload the bundled defaults — useful after experimenting with thresholds.
- **Inspect rule structure** without leaving the TUI — every threshold and scoped action/component is visible on the card.

## Use cases & benefits

- **Tune before you trust**: before relying on the Monitor in production, run `Test Rules` against recent traffic to see what the rules would have caught (or missed) — adjust thresholds in `~/.cja-audit/config.yaml` accordingly.
- **Selective on/off for incident windows**: temporarily disable a noisy rule (e.g. bulk-edit during a planned migration) without editing config or restarting the TUI.
- **Confidence check**: a clean `no alerts triggered` over 24h of normal traffic is the signal that your thresholds aren't too aggressive.
- **Rules live in YAML**: enabling/disabling in the TUI is session-scoped; permanent changes belong in `~/.cja-audit/config.yaml` (see the README's *Alert Rules* section for the schema).
- **Same engine everywhere**: rules edited here are exactly what the CLI's `cja-audit cli alerts test` and `cja-audit cli monitor` use — no drift between interactive and scripted use.
