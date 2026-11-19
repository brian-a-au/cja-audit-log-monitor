# Statistics

The statistics view shows charts and a user ranking for the number of days you choose. It reads up to 5,000 entries for each window. Press `s` to open it.

![Statistics](../screenshots/statistics.svg)

## What you see

- **The window control**, which is a `days` box and an `update` button. The box starts at `default_days` from the config file, which is 7 unless you change it. The control stays on screen even when the window has no activity, so you can make the window longer.
- **Stat cards** with the total number of entries in the window, the number of active users, and the dates of the window. When the window has more than 5,000 entries, a note says that the charts use the newest 5,000.
- **An action chart** and an **hourly activity chart**, side by side. Hours and days are in your local time zone. The busiest hour is highlighted.
- **A daily activity chart** with one bar for each of the last 14 days in the window, and a **user ranking** of the top 10 users by action count.
- **A loading message** in each chart while the data loads.

## What you can do

- **Change the window.** Type a number of days and press `Enter` or click `update`. The box then shows the number that was used. A value below 1 becomes 1, and a value above 3,650 becomes 3,650. Press `Esc` to leave the box.
- **Load again.** Press `r` to load the current window again.
- **Compare periods.** Try 30, 60 or 90 days. The daily chart always shows the last 14 days of the window.
- **Find busy hours** in the hourly chart, e.g. work at night or batch jobs.
- **Find the most active users** in the ranking. It shows 10 users, while the dashboard shows fewer.
- **Look closer.** When a user, action or hour stands out, press `l` for the log browser and filter by it.

## When to use it

- **Usage reports.** To see how many edits happened last quarter, set the window to 90 days.
- **Night activity.** A tall bar at 02:00 in the hourly chart is worth a look, even when the dashboard shows no anomaly. Night activity is an anomaly check, not an alert rule.
- **Normal levels.** The ranking shows what normal activity looks like for your users. This helps you judge the dashboard's anomalies.
- **Remote use.** The charts use plain terminal characters, so the view works over SSH.
- **A fixed limit.** The view reads at most 5,000 entries, so it stays fast. For a longer window with many entries, the charts use the newest 5,000.
