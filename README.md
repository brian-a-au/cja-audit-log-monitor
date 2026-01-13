# Adobe Customer Journey Analytics Audit Log Monitor

A command-line interface (CLI) tool for querying and analyzing Adobe Customer Journey Analytics (CJA) audit logs.

<img width="1439" height="1086" alt="Gemini_Generated_Image_djmarbdjmarbdjma" src="https://github.com/user-attachments/assets/0d8ba89d-41ff-465c-aad1-983123bd2428" />

## Features

- **List & Search**: Query audit logs with filters for user, action, component, and date range
- **Dashboard Tracking**: View all audit events for a specific dashboard/project
- **Export**: Export audit logs to JSON or CSV format
- **Statistics**: View summary statistics including top users, action distribution, and trends
- **Real-time Monitoring**: Watch for new audit events in real-time
- **Alert System**: Detect suspicious patterns like bulk deletions or unusual activity
- **Rich Output**: Colorized terminal output with formatted tables

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
cja-audit init
```

This creates `~/.cja-audit/config.yaml` with default settings.

## Usage

### List Recent Audit Logs

```bash
# List last 50 entries
cja-audit list

# List with limit and filter by component
cja-audit list --limit 100 --component PROJECT

# Show additional details
cja-audit list --details
```

### Search Audit Logs

```bash
# Search by user
cja-audit search --user user@example.com

# Search by action type
cja-audit search --action CREATE --action DELETE

# Search by date range
cja-audit search --start-date 2024-01-01 --end-date 2024-01-31

# Combine filters
cja-audit search --user user@example.com --action DELETE --component FILTER
```

### View Dashboard History

```bash
cja-audit dashboard --dashboard-id your-dashboard-id
```

### Export Audit Logs

```bash
# Export to JSON
cja-audit export --format json --output audit_logs.json

# Export to CSV
cja-audit export --format csv --output audit_logs.csv

# Export specific date range
cja-audit export --format json --output logs.json --start-date 2024-01-01 --end-date 2024-01-31

# Export last 30 days
cja-audit export --format json --output logs.json --days 30
```

### View Statistics

```bash
# Stats for last 7 days (default)
cja-audit stats

# Stats for last 30 days
cja-audit stats --days 30

# Show top 20 users
cja-audit stats --top 20
```

### Real-time Monitoring

```bash
# Monitor with default 60-second interval
cja-audit monitor

# Custom interval
cja-audit monitor --interval 30

# Monitor for specific duration (in seconds)
cja-audit monitor --duration 3600

# Disable alerts
cja-audit monitor --no-alerts
```

### Utility Commands

```bash
# List available action types
cja-audit actions

# List available component types
cja-audit components

# Show current configuration
cja-audit config

# Initialize config file
cja-audit init
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
