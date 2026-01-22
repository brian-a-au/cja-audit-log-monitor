# Adobe Customer Journey Analytics Audit Log Monitor

A full-featured TUI (Text User Interface) and CLI tool for querying and analyzing Adobe Customer Journey Analytics (CJA) audit logs.

<img width="1439" height="1086" alt="Gemini_Generated_Image_djmarbdjmarbdjma" src="https://github.com/user-attachments/assets/0d8ba89d-41ff-465c-aad1-983123bd2428" />

## Features

- **Interactive TUI**: Full-featured terminal interface with keyboard navigation
- **Dashboard View**: Summary statistics, action distribution, and recent alerts
- **Log Browser**: Browse and filter audit logs with real-time search
- **Real-time Monitoring**: Watch for new audit events as they happen
- **Statistics & Analytics**: Visualize activity patterns with charts
- **Alert System**: Configure and manage rules for suspicious activity detection
- **Export**: Export audit logs to JSON, CSV, or TSV format
- **CLI Mode**: Traditional command-line interface for scripting and automation

## Installation

### Using uv (Recommended)

```bash
# Clone or navigate to the project directory
cd cja_audit_log_monitor

# Install in development mode
uv pip install -e .

# Or run directly without installing
uv run cja-audit --help
```

### Using pip

```bash
pip install -e .
```

## Configuration

### 1. Set up Adobe Developer Console

1. Go to [Adobe Developer Console](https://developer.adobe.com/console)
2. Create a new project or use an existing one
3. Add the **Customer Journey Analytics API** to your project
4. Create OAuth Server-to-Server credentials
5. Note your Client ID, Client Secret, and Organization ID

### 2. Configure Environment Variables

Copy the example environment file and fill in your credentials:

```bash
cp .env.example .env
```

Edit `.env` with your credentials:

```bash
CJA_CLIENT_ID=your_client_id
CJA_CLIENT_SECRET=your_client_secret
CJA_ORG_ID=your_org_id@AdobeOrg
```

### 3. (Optional) Create Config File

Initialize the configuration file for additional settings:

```bash
cja-audit cli init
```

This creates `~/.cja-audit/config.yaml` with default settings.

## Usage

### TUI Mode (Default)

Simply run `cja-audit` without arguments to launch the interactive TUI:

```bash
cja-audit
```

Or explicitly:

```bash
cja-audit tui
```

#### TUI Keyboard Navigation

| Key | Action |
|-----|--------|
| `d` | Dashboard - Summary view |
| `l` | Logs - Browse audit log entries |
| `m` | Monitor - Real-time log monitoring |
| `s` | Stats - Statistics and analytics |
| `a` | Alerts - Manage alert rules |
| `c` | Config - View settings |
| `/` | Focus search/filter |
| `r` | Refresh data |
| `e` | Export current data |
| `Enter` | View entry details |
| `?` | Show help |
| `Esc` | Close modal/dialog |
| `q` | Quit application |

#### TUI Screens

1. **Dashboard**: Overview with summary stats, action distribution chart, top users, and recent anomalies
2. **Log Browser**: DataTable with filtering by user, action, component, and search text. Click/Enter to view entry details
3. **Monitor**: Real-time polling with configurable intervals, live log stream, and alert notifications
4. **Statistics**: Detailed analytics with action distribution, hourly/daily charts, and user rankings
5. **Alerts**: Manage alert rules, enable/disable rules, and test against recent data
6. **Settings**: View API connection info and configuration

### CLI Mode

For scripting and automation, use the `cli` subcommand:

```bash
cja-audit cli <command>
```

#### List Recent Audit Logs

```bash
# List last 50 entries
cja-audit cli list

# List with limit and filter by component
cja-audit cli list --limit 100 --component PROJECT

# Show additional details
cja-audit cli list --details

# Output as JSON
cja-audit cli list --output-format json
```

#### Search Audit Logs

```bash
# Search by user
cja-audit cli search --user user@example.com

# Search by action type
cja-audit cli search --action CREATE --action DELETE

# Search by date range
cja-audit cli search --start-date 2024-01-01 --end-date 2024-01-31

# Combine filters
cja-audit cli search --user user@example.com --action DELETE --component FILTER
```

#### Query with Date Presets

```bash
# Query today's logs
cja-audit cli query --today

# Query yesterday's logs
cja-audit cli query --yesterday

# Query last 7 days
cja-audit cli query --last-week

# Query last 30 days
cja-audit cli query --last-month
```

#### View Dashboard History

```bash
cja-audit cli dashboard --dashboard-id your-dashboard-id
```

#### View User Activity

```bash
cja-audit cli user --user-id user@example.com --days 7
```

#### View Component History

```bash
cja-audit cli component --id component-id --type FILTER
```

#### Export Audit Logs

```bash
# Export to JSON
cja-audit cli export --format json --output audit_logs.json

# Export to CSV
cja-audit cli export --format csv --output audit_logs.csv

# Export to TSV
cja-audit cli export --format tsv --output audit_logs.tsv

# Export specific date range
cja-audit cli export --format json --output logs.json --start-date 2024-01-01 --end-date 2024-01-31

# Export last 30 days
cja-audit cli export --format json --output logs.json --days 30
```

#### View Statistics

```bash
# Stats for last 7 days (default)
cja-audit cli stats

# Stats for last 30 days
cja-audit cli stats --days 30

# Show top 20 users
cja-audit cli stats --top 20

# Output as JSON
cja-audit cli stats --output-format json
```

#### Activity Timeline

```bash
# Show daily and hourly activity visualization
cja-audit cli timeline --days 7

# Filter by action or user
cja-audit cli timeline --action DELETE --user user@example.com
```

#### Real-time Monitoring (CLI)

```bash
# Monitor with default 60-second interval
cja-audit cli monitor

# Custom interval
cja-audit cli monitor --interval 30

# Monitor for specific duration (in seconds)
cja-audit cli monitor --duration 3600

# Disable alerts
cja-audit cli monitor --no-alerts
```

#### Tail Mode (like tail -f)

```bash
# Follow logs in real-time
cja-audit cli tail

# With filters
cja-audit cli tail --user user@example.com --action DELETE
```

#### Find Specific Actions

```bash
# Find all DELETE actions
cja-audit cli find-action --action DELETE --days 7
```

#### Top Users

```bash
# Show most active users
cja-audit cli top-users --days 7 --top 10
```

#### Generate Report

```bash
# Generate comprehensive report to stdout
cja-audit cli report --days 7

# Save report to file
cja-audit cli report --days 30 --output report.json
```

#### Alert Management

```bash
# List all alert rules
cja-audit cli alerts list

# List as JSON
cja-audit cli alerts list --output-format json

# Test rules against recent logs
cja-audit cli alerts test --days 1
```

#### Utility Commands

```bash
# List available action types
cja-audit cli actions

# List available component types
cja-audit cli components

# Show current configuration
cja-audit cli config

# Verify API connection
cja-audit cli verify

# Initialize config file
cja-audit cli init
```

## Action Types

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
| `EMBARGO` | Access restricted |
| `REFRESH` | Data refreshed |
| `ORG_CHANGE` | Organization modified |
| `API_REQUEST` | API request made |

## Component Types

| Component | Description |
|-----------|-------------|
| `PROJECT` | Workspace projects/dashboards |
| `FILTER` | Segments/filters |
| `CALCULATED_METRIC` | Calculated metrics |
| `DATA_VIEW` | Data views |
| `CONNECTION` | Data connections |
| `ANNOTATION` | Annotations |
| `AUDIENCE` | Audiences |
| `DATE_RANGE` | Date ranges |
| `SCHEDULED_PROJECT` | Scheduled reports |
| `USER` | User accounts |
| `USER_GROUP` | User groups |

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
```

## Development

### Install Development Dependencies

```bash
uv pip install -e ".[dev]"
```

### Run Tests

```bash
pytest
```

### Run Linting

```bash
ruff check src tests
```

## API Reference

This tool uses the [Adobe CJA Audit Logs API](https://developer.adobe.com/cja-apis/docs/endpoints/auditlogs/).

## License

MIT
