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
| `API_REQUEST` | A report or other API request was run |
| `FAVORITE` / `UNFAVORITE` | Component marked or unmarked as a favorite |
| `PIN` | Component pinned |
| `LABEL` | Label added to a component |

The tool also accepts `EMBARGO`, `ORG_CHANGE` and `REFRESH`.

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
| `REPORT` | Reports run in Workspace or through the API |
| `IMAGE` | Images, e.g., project thumbnails |
| `USER` | Users |
| `DATE_RANGE` | Date ranges |
| `CONTAINER` | Containers |
| `FULL_TABLE_EXPORT` | Full table exports |

The tool also accepts `DATA_GROUP`, `DATASET_STITCHING`, `FEATURE_ACCESS`, `IMS_ORG`, `MOBILE`, `SCHEDULED_PROJECT` and `USER_GROUP`.

These are the values accepted by `--component` flags in the [CLI](cli.md) and the component filter on the [Log Browser](screens/log-browser.md) and [Alert Rules](alert-rules.md).

## Upstream API

This tool is a thin client over the [Adobe CJA Audit Logs API](https://developer.adobe.com/cja-apis/docs/endpoints/auditlogs/). Refer to the upstream docs for endpoint details, response schemas, and rate limits.
