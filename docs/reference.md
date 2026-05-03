# Reference

## Action types

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

These are the values accepted by `--action` flags in the [CLI](cli.md) and the action filter on the [Log Browser](screens/log-browser.md) and [Alert Rules](alert-rules.md).

## Component types

| Component | Description |
|-----------|-------------|
| `PROJECT` | Workspace projects/dashboards |
| `FILTER` | Segments/filters |
| `CALCULATED_METRIC` | Calculated metrics |
| `DATA_VIEW` | Data views |
| `CONNECTION` | Data connections |
| `ANNOTATION` | Annotations |
| `AUDIENCE` | Audiences |

These are the values accepted by `--component` flags in the [CLI](cli.md) and the component filter on the [Log Browser](screens/log-browser.md) and [Alert Rules](alert-rules.md).

## Upstream API

This tool is a thin client over the [Adobe CJA Audit Logs API](https://developer.adobe.com/cja-apis/docs/endpoints/auditlogs/). Refer to the upstream docs for endpoint details, response schemas, and rate limits.
