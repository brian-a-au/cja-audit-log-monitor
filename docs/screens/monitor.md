# Real-Time Monitor

The monitor asks the audit API for new events at a set interval. It adds each new event to a live table and checks it against your alert rules. Press `m` to open it.

![Monitor](../screenshots/monitor.svg)

## What you see

- **The controls**, which are the `▶ start` and `■ stop` buttons and an `interval` box in seconds. The interval box is turned off while the monitor runs.
- **The status row**, which shows `running`, `stopped` or `error`. After a failed poll, it shows the error text and says that the monitor retries each interval. A 400, 401, 403 or 404 response, or bad or missing credentials, stops the monitor instead, as in the CLI, because trying again cannot fix it. A toast gives the reason. Its color and its left border change with the state. It also shows the time of the last check, the number of new events and the number of alerts. It updates after every poll.
- **The live log stream**, a table with the same colored action column as the log browser.
  - The newest event is at the bottom.
  - When the cursor is on the last row, the view follows new rows as they arrive. When you move the cursor up, the view stays where you put it.
  - The table keeps the newest 1,000 rows and drops older ones.
  - The table is cleared each time you start the monitor.
- **The alerts panel**, a short summary of the alerts that fired since you started. Each alert has one line, e.g. `bulk_delete: 5 events in 60 minutes by someone@example.com`. The panel is cleared each time you start the monitor.
- **Toasts** for alerts, errors and warnings. The TUI has no log file, so warnings that the CLI prints on stderr show here as toasts.
- **A delivery warning** if a send to Slack or a webhook fails. You see one warning for each failing channel, e.g. `Notification delivery failed (webhook 2 (https://example.com/…)). This warning shows again if the channel fails after it works again.` Later failures on that channel show no warning until a send works again. Each failed send also shows a short `Failed to send` toast.

## How polling works

- The interval box starts at `monitor_interval` from the config file, which is 60 seconds unless you change it.
- The first poll after you press start reads the last 5 minutes. It shows up to 100 of those entries so you have some context. It does not alert on them or count them as new.
- Each later poll reads from 5 minutes before the last good poll up to now. The monitor skips entries it has already shown. This overlap catches events that the API indexed late.
- Each poll reads pages of 1,000 entries, so a normal poll is one request. One poll reads at most 50 pages, which is 50,000 events. After a long gap, e.g. a laptop asleep, the poll reads the whole gap up to that limit. Past it, a toast says how many older events were skipped.
- An event that the API indexes more than 5 minutes late is missed.
- After a good poll, the header shows `connected` again.
- When a poll fails, the status row shows the error. Each new error text also shows a toast, and the same error again shows none. A 403 marks the header `disconnected`. The monitor keeps trying at each interval, so you can fix your settings and carry on. The CLI `monitor` command is different, because it stops on a login or permission error.

## What you can do

- **Start and stop** with the buttons or with `Space`. `Space` works even when the interval box has focus.
- **Change the interval.** While the monitor is stopped, type a number of seconds in the box. Press `Enter` or start to use it. The value must be 5 to 86,400. If it is outside that range, the box is marked as invalid and the old value stays.
- **Watch alerts fire.** Each poll checks the new events against the alert rules that are on. The toast shows one line with the rule name, the count and the user, e.g. `bulk_delete: 5 events in 60 minutes by someone@example.com`. A rule that counts all users together names the latest user, e.g. `any_delete: 3 events in 60 minutes, latest by someone@example.com`. A rule with a threshold of 1 shows its description instead of a count. Rules with `per_user: true` count each account on its own. When the config file has a `notifications:` block, each alert is also sent to Slack or your webhooks. See [Delivery channels](../alert-rules.md#delivery-channels).
- **Poll now.** Press `r` while the monitor runs to poll at once. The interval timer does not change, and two polls never run at the same time.
- **Stop.** The poll in progress is dropped, so it cannot add rows after you stop. Starting again begins a new session with a new first poll.

## When to use it

- **During an incident.** Run the monitor with a short interval, e.g. 5 to 15 seconds, to see `DELETE` and `EXPORT` events as they happen.
- **During a planned change.** Watch the stream to check that the right components change and nothing else does.
- **While on call.** Turn on the rules you care about, e.g. bulk deletes, and keep the view open in your terminal.
- **No extra setup.** The monitor uses the same API and credentials as the rest of the tool.
