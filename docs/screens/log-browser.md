# Log Browser

The Log Browser is the workhorse for triage and forensic lookups — a paginated, filterable table of every audit entry the API returns. Press `l` to open it.

![Log Browser](../screenshots/log-browser.svg)

## What you see

- **Filter bar** (one row) at the top: free-text search, user (email), action type, and component type pickers. Filters apply server-side where supported and client-side for free-text.
- **Log table**: time, user, action, component type, and component name. Times are in your local time zone, and the column header names the zone, e.g., `time (PST)`. Action cells are color-coded so DELETE/EXPORT stand out at a glance.
- **Detail side panel** (toggle with `Enter`): every field of the highlighted entry, including the user's name, IDs and the description that don't fit in the table.
- **A message above the table** when it is empty: the connection error, or a note that no entries match the filters.
- **Pagination controls**: `◀ prev` / `next ▶` buttons and a "page X of Y · N entries" counter, all on one row.

## What you can do

- **Filter** by user (an email address or an IMS user ID), action, component, or free text. Filters compose — set all four to narrow aggressively.
- **Search-as-you-go**: change a filter and the table reloads from the API; the page resets to 1 automatically.
- **Page through results** with `n` (next), `p` (prev), or the buttons. The next/prev buttons disable when you hit either edge.
- **Inspect a single entry** with `Enter` — the side panel slides in next to the table. Move the cursor and the panel updates live; press `Esc` or `Enter` again to close.
- **Reset filters** in one click via the filter bar's reset action.
- **Export** with `e` to JSON, CSV or TSV. You can export the page you see, or every entry that matches the filters, up to 10,000.

## Use cases & benefits

- **Forensics**: "who deleted this Workspace project last Tuesday?" Filter by component name, action=DELETE, narrow by date — the answer is 3 keystrokes away.
- **User audit**: filter by `user@company.com` to get every action taken by a specific account, paginated.
- **Compliance evidence**: filter to the relevant scope, hit `e`, and you have a CSV ready to attach to a ticket or audit response.
- **Side-panel pattern**: unlike a full-screen modal, the detail panel keeps the table cursor visible, so you can scroll through entries one-by-one without losing your place.
- **Server-side pagination** means the table is responsive even when the underlying result set spans hundreds of thousands of entries.
