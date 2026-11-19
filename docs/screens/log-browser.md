# Log Browser

The log browser shows audit entries in a table that you can filter and page through. Press `l` to open it.

![Log Browser](../screenshots/log-browser.svg)

## What you see

- **The filter bar** at the top. It has a search box, a user box, an action list and a component list, and a `reset` button. Below 100 columns, the filter bar uses two rows.
- **The log table** with the time, user, action, component type and component name of each entry. Times are in your local time zone, and the column header names the zone, e.g. `time (PST)`. Each action has its own color, so `DELETE` and `EXPORT` are easy to see. When the table is too narrow, it hides the component name first and then the component type. Long text is cut and ends with `…`.
- **The detail panel**, which you open with `Enter`. It shows every field of the selected entry, including the user's name, the ids and the description. At 160 columns or wider, the panel opens beside the table. Below 160 columns, it opens over the table.
- **A message above the table** when the table is empty. It gives the connection error, or says that no entries match the filters.
- **Page controls**, which are the `◀ prev` and `next ▶` buttons and a "page X of Y · N entries" counter. The buttons are disabled before the first load and after an error.

Each page has `default_page_size` rows, which is 100 unless you change it in the config file. Only the log browser uses this setting.

## What you can do

- **Filter** by user, action, component or text. You can use all four at once.
  - In the user box, type an email address or an Adobe user id.
  - The search box looks for text in the entry description. The API does this search, so it covers every entry, not only the page you see.
  - The search and user boxes apply when you press `Enter`. The action and component lists apply as soon as you pick a value.
  - Each change loads the table again from the API and goes back to page 1.
  - Press `Esc` to leave the search or user box. What you typed stays in the box.
  - Press `/` to jump to the search box.
- **Reset the filters** with the `reset` button.
- **Page through the results** with `n` and `p`, or with the buttons.
- **Look at one entry** with `Enter`. When you move the cursor, the panel shows the new entry. Press `Esc` or `Enter` again to close it. Press `Tab` to move into the panel, and then scroll it with the arrow keys.
- **Export** with `e` to JSON, CSV or TSV. You can export the page you see, or every entry that matches the filters, up to 10,000 entries.

## Export

The export dialog asks for a format and a file path.

- If the file already exists, the dialog asks you to press export a second time to replace it.
- Press `Enter` in the path box to export.
- The file is written the same safe way as the CLI `export` command. The tool writes a temporary file first and then moves it into place, so a failed export leaves no partial file. Only you can read the new file (mode 0600). In CSV and TSV, cells that a spreadsheet could run as a formula get a `'` in front. See [`export`](../cli.md#export) for the details.
- When it is done, the dialog shows the full path. When the 10,000 limit applies, it says so, e.g. "exported 10,000 of 12,345 (limit reached)".
- Before the log browser has loaded, or after a failed load, the "this page" choice is turned off.

## When to use it

- **Find a change.** To find who deleted a project last Tuesday, choose `DELETE` and `PROJECT`, then search for the project name.
- **Check one user.** Type `user@example.com` in the user box to see every action of that account.
- **Collect evidence.** Filter the entries, press `e`, and save a CSV file to attach to a ticket.
- **Read entries one by one.** The detail panel keeps your place in the table, so you can move through the entries and read each one.
- **Large results.** The API sends one page at a time, so the table stays fast even when many entries match.
