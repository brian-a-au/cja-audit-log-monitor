# Real-Time Monitor

The Monitor screen polls the audit API on a configurable interval and streams new events into a live table while running configured alert rules against the incoming batch. Press `m` to open it.

![Monitor](../screenshots/monitor.svg)

## What you see

- **Controls bar**: `▶ Start` / `⏹ Stop` buttons and an `Interval` input (seconds, minimum 5).
- **Status row**: a `running` / `stopped` indicator that flips color with state, plus a stats line — *Last check · New entries · Alerts triggered* — updated after every poll.
- **Live log stream**: a log table that prepends new entries as they arrive, with the same color-coded action column as the Log Browser. Cleared each time you start a new session.
- **Alerts panel**: a compact summary of any alerts triggered during the active session.
- **Notifications**: alerts and warnings (e.g. "high event volume detected") raise toast notifications on top of the screen.
- **Delivery-failure warning** (only if it happens): if a Slack/webhook delivery fails, you'll see a single warning toast naming the channel. Subsequent failures during the same session are suppressed; logs always record every attempt.

## What you can do

- **Start / stop** monitoring with the buttons or the `Space` key.
- **Tune the polling interval** before starting — short intervals for incident watch, longer intervals for a passive feed.
- **Watch alerts trigger live** — every poll runs the active alert rules over the new batch and increments the session counters. The toast shows the actual rule name and message (e.g. `bulk_delete: Multiple delete operations: 5 events in 60 minutes`). When a `notifications:` block is configured (Slack/webhooks), each fired rule is also delivered externally. See [Delivery channels](../alert-rules.md#delivery-channels).
- **Manual poll** — pressing `r` while monitoring is running fires an extra poll without disrupting the interval timer; the screen guards against overlapping polls.
- **Stop cleanly** — the worker is cancelled, button states reset, and the in-memory dedup set is preserved so a restart picks up where you left off.

## Use cases & benefits

- **Incident watch**: during a suspected breach or anomaly, leave the monitor running with a short interval (5–15 s) to catch DELETE/EXPORT activity in real time.
- **Change windows**: during a planned migration or admin push, watch the stream to confirm the right components are being touched and nothing unexpected happens alongside it.
- **On-call companion**: pair the live alerts panel with your alert rules of choice (bulk deletes, off-hours activity) for a lightweight SOC-style view that runs entirely from your terminal.
- **Burst-safe polling**: each poll fetches up to 20 pages of recent entries and dedupes against a rolling set of seen IDs, so high-volume bursts won't drop events. If the page cap is hit, you're warned via toast.
- **No infrastructure required**: no webhooks, no event bus, no separate agent — just the CLI talking to the same API the rest of the tool uses.
