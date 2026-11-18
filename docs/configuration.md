# Configuration

Authentication uses **OAuth Server-to-Server** (Adobe's current standard). Setup is a one-time process in the Adobe Developer Console.

> Commands below assume you've already run through the README's [Quick Start](../README.md#quick-start). Prefix CLI commands with `uv run` (e.g. `uv run cja-audit-log-monitor cli verify`) or activate the venv first.

## Prerequisites

- [ ] Adobe Experience Cloud account with CJA access
- [ ] [Adobe Developer Console](https://developer.adobe.com/console/) access (System Administrator or Developer role)
- [ ] Service account assigned to appropriate CJA and AEP product profiles in [Admin Console](https://adminconsole.adobe.com/)

## 1. Create the Developer Console project

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

## 2. Collect credentials

From the project's **OAuth Server-to-Server** credentials page:

| Variable | Where to find it | Example |
|---|---|---|
| `ORG_ID` | Project Overview → Organization ID | `ABC123DEF456@AdobeOrg` |
| `CLIENT_ID` | Credentials → Client ID | `1234567890abcdef…` |
| `SECRET` | Credentials → **Retrieve client secret** | `p8e-XXX…` |
| `SCOPES` | Credentials → Scopes (copy as shown) | `openid,AdobeID,read_organizations,additional_info.projectedProductContext` |

> **Copy `SCOPES` exactly as Developer Console displays them.** Adding, removing, or reordering scopes causes `invalid_scope` errors.

> **Important:** Keep these credentials secure. Never commit them to version control.

## 3. Configure the tool

```bash
cp .env.example .env
# Edit .env with the four values above
```

`.env` is gitignored. Never commit credentials.

## 4. (Optional) Create a config file for alert rules and notification channels

```bash
uv run cja-audit-log-monitor cli init
```

Writes `~/.cja-audit-log-monitor/config.yaml` with default alert rules and a commented `notifications:` example block (Slack + webhooks). Environment variables always take precedence over the config file. See [Alert Rules](alert-rules.md) for rule schema and [Delivery channels](alert-rules.md#delivery-channels) for notification config.

> The default for `notify_on_anomalies` is `false` (opt-in). Set to `true` to
> enable delivery via `cja-audit-log-monitor cli anomalies`.

### Defaults in the config file

| Key | Default | Range | Used by |
| --- | --- | --- | --- |
| `default_page_size` | 100 | 1 to 1000 | Rows per page in the TUI log browser. The CLI does not use it. |
| `default_days` | 7 | 1 or more | The TUI dashboard and stats views, and `--days` when you leave it off (`user`, `export`, `stats`, `report`, `timeline`, `find-action`, `top-users`). |
| `monitor_interval` | 60 | 5 or more | The TUI monitor interval box (which accepts 5 or more when you edit it), and `cli monitor --interval` when you leave it off. |

A value outside its range stops the config file from loading, and the error names the key. An older file that still has `output_format:` keeps working: the key is ignored with a warning.

## 5. Verify

```bash
uv run cja-audit-log-monitor cli verify
```

Expected: `Connected` with your organization ID. If it fails, see [Troubleshooting](troubleshooting.md).
