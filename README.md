# Adobe Customer Journey Analytics Audit Log Monitor

A powerful TUI (Text User Interface) application for monitoring and analyzing Adobe Customer Journey Analytics (CJA) audit logs in real-time.

## Features

- **Interactive Navigation**: Keyboard-driven interface for fast navigation
- **Real-Time Updates**: Monitor audit logs as they happen with configurable polling
- **Smart Filtering**: Search by user, action type, component, and text
- **Visual Analytics**: Bar charts for action distribution and activity patterns
- **Alert Detection**: Configurable rules for bulk deletes, exports, and suspicious patterns
- **Export Options**: Save filtered logs to JSON, CSV, or TSV
- **Connection Status**: Live API connection monitoring

## Quick Start

> Prefix commands with `uv run` (e.g. `uv run cja-audit`), or activate the venv first (`source .venv/bin/activate`) and run them directly.

```bash
# 1. Clone
git clone https://github.com/brian-a-au/cja_audit_log_monitor
cd cja_audit_log_monitor

# 2. Install uv (skip if you already have it)
curl -LsSf https://astral.sh/uv/install.sh | sh

# 3. Sync the project (creates .venv/ and installs all dependencies)
uv sync --all-extras

# 4. Configure credentials
cp .env.example .env
# Edit .env with your Adobe credentials

# 5. Launch the TUI
uv run cja-audit
```

That's it! The interactive TUI will launch with a dashboard showing your audit log activity.

## The TUI Experience

The application provides a full-featured terminal interface built with [Textual](https://textual.textualize.io/). Navigate between screens using keyboard shortcuts for a seamless experience.

### [Dashboard](docs/screens/dashboard.md) (Press `d`)

Your home base showing at-a-glance metrics including total entries, date range, action distribution charts, top active users, and recent anomalies. [Read more →](docs/screens/dashboard.md)

![Dashboard](docs/screenshots/dashboard.svg)

### [Log Browser](docs/screens/log-browser.md) (Press `l`)

Browse, search, and filter audit logs with a powerful data table. Filter by user, action type, component, or search text. Press `Enter` on any row to view full entry details. [Read more →](docs/screens/log-browser.md)

![Log Browser](docs/screenshots/log-browser.svg)

### [Real-Time Monitor](docs/screens/monitor.md) (Press `m`)

Watch audit events stream in as they happen. Configure polling intervals, see live statistics, and get instant alert notifications for suspicious activity. [Read more →](docs/screens/monitor.md)

![Monitor](docs/screenshots/monitor.svg)

### [Statistics](docs/screens/statistics.md) (Press `s`)

Detailed analytics with visual charts showing action distribution, hourly/daily activity patterns, and user rankings. [Read more →](docs/screens/statistics.md)

![Statistics](docs/screenshots/statistics.svg)

### [Alert Rules](docs/screens/alerts.md) (Press `a`)

Configure and manage suspicious activity detection rules. Enable/disable rules, adjust thresholds, and test against recent data. [Read more →](docs/screens/alerts.md)

![Alerts](docs/screenshots/alerts.svg)

### [Settings](docs/screens/settings.md) (Press `c`)

View connection status, API configuration, and application settings. [Read more →](docs/screens/settings.md)

![Settings](docs/screenshots/settings.svg)

## Keyboard Shortcuts

| Key | Action |
|-----|--------|
| `d` | Go to Dashboard |
| `l` | Go to Log Browser |
| `m` | Go to Monitor |
| `s` | Go to Statistics |
| `a` | Go to Alerts |
| `c` | Go to Config/Settings |
| `/` | Focus search/filter bar |
| `r` | Refresh current view |
| `e` | Open export dialog |
| `Enter` | View entry details (in Log Browser) |
| `?` | Show help overlay |
| `Esc` | Close modal/dialog |
| `q` | Quit application |

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/brian-a-au/cja_audit_log_monitor
cd cja_audit_log_monitor
```

### 2. Install uv

[`uv`](https://docs.astral.sh/uv/) is the project's package and environment manager. Pick whichever path is convenient:

```bash
# macOS / Linux (recommended)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Or via pip on any platform
pip install uv
```

### 3. Sync the project

```bash
# Runtime only
uv sync

# Or include dev tools (pytest, ruff)
uv sync --all-extras
```

This creates `.venv/` and installs all locked dependencies from `uv.lock`. Run commands with `uv run cja-audit ...` or activate the venv (`source .venv/bin/activate`) and call `cja-audit` directly.

## Configuration

Authentication uses **OAuth Server-to-Server** (Adobe's current standard). Setup is a one-time process in the Adobe Developer Console.

### Prerequisites

- [ ] Adobe Experience Cloud account with CJA access
- [ ] [Adobe Developer Console](https://developer.adobe.com/console/) access (System Administrator or Developer role)
- [ ] Service account assigned to appropriate CJA and AEP product profiles in [Admin Console](https://adminconsole.adobe.com/)

### 1. Create the Developer Console project

1. Open [Adobe Developer Console](https://developer.adobe.com/console/) and confirm the correct organization is selected (top-right dropdown).
2. Click **Create new project** and name it descriptively (e.g. `CJA Audit Log Monitor`).
3. **Add the Customer Journey Analytics API:**
   - Click **Add API** → search for **Customer Journey Analytics** → **Next**
   - Select **OAuth Server-to-Server** authentication → **Next**
   - Choose a product profile with access to your Data Views → **Save configured API**
4. **Add the Experience Platform API** (required even if you only use CJA — without it, CJA tokens won't authenticate):
   - Click **Add API** → search for **Experience Platform API** → **Next**
   - Select **OAuth Server-to-Server** → **Next**
   - Choose a product profile → **Save configured API**

Your project should now show **two APIs** sharing the same OAuth credentials.

> **Tip:** Copy your scopes *after* adding both the CJA and AEP APIs. The Developer Console aggregates scopes from all APIs in your project, so copying before both are added may give you an incomplete set.

### 2. Collect credentials

From the project's **OAuth Server-to-Server** credentials page:

| Variable | Where to find it | Example |
|---|---|---|
| `ORG_ID` | Project Overview → Organization ID | `ABC123DEF456@AdobeOrg` |
| `CLIENT_ID` | Credentials → Client ID | `1234567890abcdef…` |
| `SECRET` | Credentials → **Retrieve client secret** | `p8e-XXX…` |
| `SCOPES` | Credentials → Scopes (copy as shown) | `openid,AdobeID,read_organizations,additional_info.projectedProductContext` |

> **Copy `SCOPES` exactly as Developer Console displays them.** Adding, removing, or reordering scopes causes `invalid_scope` errors.

> **Important:** Keep these credentials secure. Never commit them to version control.

### 3. Configure the tool

```bash
cp .env.example .env
# Edit .env with the four values above
```

`.env` is gitignored. Never commit credentials.

### 4. (Optional) Create a config file for alert rules

```bash
cja-audit cli init
```

Writes `~/.cja-audit/config.yaml` with default alert rules and preferences. Environment variables always take precedence over the config file.

### 5. Verify

```bash
cja-audit cli verify
```

Expected: `Connected` with your organization ID. If it fails, see Troubleshooting below.

## Troubleshooting

### OAuth errors

| Error | Likely cause | Fix |
|---|---|---|
| `invalid_client` | Client ID or Secret wrong/expired | Re-retrieve from Developer Console; check for whitespace |
| `invalid_scope` | `SCOPES` differs from the Developer Console string | Re-copy verbatim from OAuth Server-to-Server → Scopes |
| `unauthorized_client` | OAuth Server-to-Server not enabled for the credential | Confirm the credential type in Developer Console |
| `401 Unauthorized` | Token expired or credentials regenerated | Re-retrieve the client secret |
| `403 Forbidden` | Missing AEP API association, or product profile not assigned | Add Experience Platform API to the project; verify Admin Console product-profile assignments |

After permission changes in Admin Console, allow **5–10 minutes** for propagation before retrying.

### Setup checklist

- [ ] `ORG_ID` ends with `@AdobeOrg`
- [ ] Both **Customer Journey Analytics** and **Experience Platform API** added to the project
- [ ] OAuth Server-to-Server credential created
- [ ] `SCOPES` copied verbatim from the Developer Console
- [ ] Service account assigned to CJA product profile with Data View read access
- [ ] Service account assigned to an AEP product profile (required even for CJA-only use)

### Security

- Never commit `.env`, `config.json`, or any credential file. The repo's `.gitignore` already covers these.
- Rotate the client secret periodically via Developer Console.
- Use the minimum product-profile permissions required.

## CLI Mode

For scripting and automation, a traditional CLI is available under the `cli` subcommand:

```bash
# List recent logs
cja-audit cli list --limit 100

# Search with filters
cja-audit cli search --user user@example.com --action DELETE

# Export to file
cja-audit cli export --format json --output audit_logs.json --days 30

# View statistics
cja-audit cli stats --days 7

# Real-time monitoring
cja-audit cli monitor --interval 30

# Generate report
cja-audit cli report --days 30 --output report.json
```

<details>
<summary>View all CLI commands</summary>

### Query Commands
```bash
cja-audit cli list [--limit N] [--component TYPE] [--details]
cja-audit cli search [--user EMAIL] [--action TYPE] [--start-date DATE] [--end-date DATE]
cja-audit cli query [--today|--yesterday|--last-week|--last-month]
cja-audit cli user --user-id EMAIL [--days N]
cja-audit cli component --id ID [--type TYPE]
cja-audit cli dashboard --dashboard-id ID
cja-audit cli find-action --action TYPE [--days N]
cja-audit cli top-users [--days N] [--top N]
```

### Analysis Commands
```bash
cja-audit cli stats [--days N] [--top N] [--output-format json|table]
cja-audit cli timeline [--days N] [--action TYPE] [--user EMAIL]
cja-audit cli report [--days N] [--output FILE]
```

### Monitoring Commands
```bash
cja-audit cli monitor [--interval N] [--duration N] [--no-alerts]
cja-audit cli tail [--user EMAIL] [--action TYPE] [--interval N]
```

### Export Commands
```bash
cja-audit cli export --output FILE [--format json|csv|tsv] [--days N]
```

### Alert Commands
```bash
cja-audit cli alerts list [--output-format json|table]
cja-audit cli alerts test [--days N]
```

### Utility Commands
```bash
cja-audit cli actions      # List action types
cja-audit cli components   # List component types
cja-audit cli config       # Show configuration
cja-audit cli verify       # Test API connection
cja-audit cli init         # Create config file
```

</details>

## Alert Rules

Configure alert rules in `~/.cja-audit/config.yaml`:

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

## Reference

### Action Types

| Action | Description |
|--------|-------------|
| `CREATE` | Component created |
| `EDIT` | Component modified |
| `DELETE` | Component deleted |
| `SHARE` | Component shared |
| `UNSHARE` | Sharing removed |
| `APPROVE` | Component approved |
| `UNAPPROVE` | Approval removed |
| `EXPORT` | Data exported |
| `TRANSFER` | Ownership transferred |

### Component Types

| Component | Description |
|-----------|-------------|
| `PROJECT` | Workspace projects/dashboards |
| `FILTER` | Segments/filters |
| `CALCULATED_METRIC` | Calculated metrics |
| `DATA_VIEW` | Data views |
| `CONNECTION` | Data connections |
| `ANNOTATION` | Annotations |
| `AUDIENCE` | Audiences |

## Development

```bash
# Install with dev dependencies
uv sync --all-extras

# Run tests
uv run pytest

# Run linting
uv run ruff check src tests
```

## API Reference

This tool uses the [Adobe CJA Audit Logs API](https://developer.adobe.com/cja-apis/docs/endpoints/auditlogs/).

## License

MIT
