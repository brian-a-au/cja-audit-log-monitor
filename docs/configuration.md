# Configuration

The tool logs in to Adobe with an OAuth Server-to-Server credential. You create the credential once, in the Adobe Developer Console.

These steps assume you have installed the tool as the README describes in [Install](../README.md#install).

## Prerequisites

- [ ] An Adobe Experience Cloud account with CJA access.
- [ ] Access to the [Adobe Developer Console](https://developer.adobe.com/console/), with the System Administrator or Developer role.
- [ ] A service account that is assigned to the right CJA and AEP product profiles in the [Admin Console](https://adminconsole.adobe.com/).

## 1. Create the Developer Console project

1. Open the [Adobe Developer Console](https://developer.adobe.com/console/). Check that the right organization is selected in the menu at the top right.
2. Click **Create new project**. Give it a name you will recognize, e.g. `CJA Audit Log Monitor`.
3. Add the Customer Journey Analytics API:
   - Click **Add API**, search for **Customer Journey Analytics**, and click **Next**.
   - Select **OAuth Server-to-Server** and click **Next**.
   - Choose a product profile that can see your data views, and click **Save configured API**.
4. Add the Experience Platform API. You need it even if you use only CJA. Without it, CJA tokens do not work.
   - Click **Add API**, search for **Experience Platform API**, and click **Next**.
   - Select **OAuth Server-to-Server** and click **Next**.
   - Choose a product profile and click **Save configured API**.

The project now shows two APIs that share the same OAuth credential.

Copy the scopes only after you have added both APIs. The Developer Console combines the scopes of every API in the project, so a copy made earlier can be missing some.

## 2. Collect the credentials

You can find these values on the project's **OAuth Server-to-Server** credential page.

| Variable | Where to find it | Example |
|---|---|---|
| `ORG_ID` | The Organization ID on the project overview | `YOUR_ORG_ID@AdobeOrg` |
| `CLIENT_ID` | The Client ID on the credential page | `your_client_id` |
| `SECRET` | **Retrieve client secret** on the credential page | `your_client_secret` |
| `SCOPES` | The Scopes on the credential page | `openid,AdobeID,read_organizations,additional_info.projectedProductContext` |

Copy `SCOPES` exactly as the Developer Console shows it. If you add, remove or reorder scopes, Adobe returns an `invalid_scope` error. If you leave `SCOPES` out, the tool uses the example value above.

Keep these values private. Never commit them to version control.

## 3. Give the tool your credentials

You can set the four values as environment variables. You can also put them in a `.env` file in the folder where you run the tool:

```bash
ORG_ID=YOUR_ORG_ID@AdobeOrg
CLIENT_ID=your_client_id
SECRET=your_client_secret
SCOPES=openid,AdobeID,read_organizations,additional_info.projectedProductContext
```

If you work from a clone of the repository, copy `.env.example` to `.env` and fill it in. The repository's `.gitignore` already covers `.env`.

The variable names have no prefix, and case does not matter. `ORG_ID` must end with `@AdobeOrg`.

## 4. (Optional) Create a config file

The config file holds alert rules, notification channels and default values. Create it with this command:

```bash
cja-audit-log-monitor cli init
```

The command writes a config file with the default settings, the alert rules (commented out) and a commented example `notifications:` block for Slack and webhooks. If the file already exists, it asks before it replaces it.

See [Alert Rules](alert-rules.md) for the rule format and [Delivery channels](alert-rules.md#delivery-channels) for notifications. The default for `notify_on_anomalies` is `false`. Set it to `true` to let `cja-audit-log-monitor cli anomalies` send anomalies.

### Where the config file lives

The tool looks for the config file in this order:

1. The path you give with `-c` / `--config`, e.g. `cja-audit-log-monitor -c ./config.yaml cli list`. The option goes before `cli` or `tui`.
2. The path in the `CJA_CONFIG_PATH` environment variable.
3. `~/.cja-audit-log-monitor/config.yaml`.

`cli init` writes to the same path that the tool reads. `cli config` shows which path is in use.

### The file is private

`cli init` creates the folder so that only you can open it (mode 0700). It creates the file so that only you can read it (mode 0600). The file can hold webhook URLs and `Authorization` headers, so keep it that way.

If other users can read the file, the tool logs a warning each time it loads the file. The warning suggests `chmod 600` with the file's path.

### Which value wins

The tool reads each setting from these places, from highest priority to lowest:

1. Environment variables.
2. The `.env` file in the current folder.
3. The config file.
4. The built-in default.

So a value in an environment variable or in `.env` always beats the same value in the config file.

### Settings

| Key | Default | Allowed values | Used by |
| --- | --- | --- | --- |
| `api_base_url` | `https://cja.adobe.io` | An https URL | Every API call. You can also set it with the `API_BASE_URL` environment variable. |
| `ims_base_url` | `https://ims-na1.adobelogin.com` | An https URL | Login. You can also set it with the `IMS_BASE_URL` environment variable. |
| `default_page_size` | 100 | 1 to 1000 | Rows per page in the TUI log browser. The CLI does not use it. |
| `default_days` | 7 | 1 or more | The TUI dashboard and stats views. It is also the default for `--days` when you leave it off (`user`, `export`, `stats`, `report`, `timeline`, `find-action` and `top-users`). |
| `monitor_interval` | 60 | 5 or more | The starting value of the TUI monitor interval box. It is also the default for `cli monitor --interval`. |
| `alert_rules` | the built-in rules | A list of rules | See [Alert Rules](alert-rules.md). |
| `notifications` | none | A block of channels | See [Delivery channels](alert-rules.md#delivery-channels). |

The two URLs must use https. Plain http is allowed only for `localhost` and `127.0.0.1`, which is useful for tests. Any other http URL stops the settings from loading.

A value below its minimum, or a `default_page_size` above 1000, stops the config file from loading. The error names the key and does not show the value. An older file that still has `output_format:` keeps working. The tool ignores that key and logs a warning. It also logs a warning for any other key it does not know.

### When the config file has an error

The CLI prints one line that starts with `Configuration error:` and names the file and the problem. Then it exits 1.

The TUI still starts. It loads settings from the environment variables and `.env` only. The header shows a short warning about the file, so you can fix it and use **reload settings** on the config screen.

## 5. Verify

```bash
cja-audit-log-monitor cli verify
```

When it works, the command prints `Connection successful`, your organization ID, the API URL and the number of logs available. When it fails, it prints the error and exits 1. If it fails, see [Troubleshooting](troubleshooting.md).
