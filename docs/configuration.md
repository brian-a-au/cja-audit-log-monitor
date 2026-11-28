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
| `SCOPES` | The Scopes on the credential page | `your_scopes_from_developer_console` |

Copy `SCOPES` exactly as the Developer Console shows it. If you add, remove or reorder scopes, Adobe returns an `invalid_scope` error. The tool has no built-in scopes, so you must set `SCOPES`. A credential without scopes is an error that names `scopes` as missing.

Keep these values private. Never commit them to version control.

## 3. Give the tool your credentials

You can set the four values as environment variables. You can also put them in a `.env` file in the folder where you run the tool:

```bash
ORG_ID=YOUR_ORG_ID@AdobeOrg
CLIENT_ID=your_client_id
SECRET=your_client_secret
SCOPES=your_scopes_from_developer_console
```

If you work from a clone of the repository, copy `.env.example` to `.env` and fill it in. The repository's `.gitignore` already covers `.env`.

The variable names have no prefix, and case does not matter. `ORG_ID` must end with `@AdobeOrg`.

The tool reads `.env` only from the folder you run it in. It does not look in parent folders, and it does not copy the values into the environment.

### Profiles

A profile is a folder that holds one credential. The Customer Journey Analytics tools share the folder `~/.cja/orgs/`, so one profile works in each of them. Profile `prod` is the file `~/.cja/orgs/prod/config.json`:

```json
{
  "org_id": "YOUR_ORG_ID@AdobeOrg",
  "client_id": "your_client_id",
  "secret": "your_client_secret",
  "scopes": "your_scopes_from_developer_console"
}
```

Use a profile with `--profile`, e.g. `cja-audit-log-monitor --profile prod cli verify`. The option goes before `cli` or `tui`. You can also set the `CJA_PROFILE` environment variable to the name.

- The tool reads a profile and never writes one. Create the folder and the file yourself, and keep the file private with `chmod 600`.
- A profile name holds letters, digits, dots, underscores and hyphens. It starts with a letter or a digit, and it has 64 characters or fewer.
- The keys are lower case. A key in upper case, e.g. `ORG_ID`, is not read, and the tool gives a warning. The tool accepts a `sandbox` key and does not use it. It ignores any other key.
- A profile that does not exist is an error. The tool does not go on to another source.

### Where the credential comes from

The tool looks for the credential in these places, in this order. It uses the first place that holds any of the four fields.

1. The profile you give with `--profile`, or the config file you give with `-c` / `--config` when that file holds credential fields. You cannot give both.
2. The profile named in the `CJA_PROFILE` environment variable.
3. The environment variables `ORG_ID`, `CLIENT_ID`, `SECRET` and `SCOPES`.
4. The `.env` file in the current folder.
5. The default config file.

One place gives all four fields. The tool never takes some fields from one place and the rest from another. If the first place that holds a field does not hold all four, the tool stops with an error that names the missing fields. For example, if `ORG_ID`, `CLIENT_ID` and `SECRET` are set as environment variables and `SCOPES` is not, the error names `SCOPES`, even when `.env` holds a full credential.

A field with an empty value, e.g. `SECRET=`, counts as not set in each of these places.

Run `cja-audit-log-monitor cli config` to see which place the tool uses. See [Check the credential](cli.md#check-the-credential).

## 4. (Optional) Create a config file

The config file holds alert rules, notification channels and default values. Create it with this command:

```bash
cja-audit-log-monitor cli init
```

The command writes a config file with the default settings, the four built-in alert rules (commented out) and a commented example `notifications:` block for Slack and webhooks. If the file already exists, it asks before it replaces it.

See [Alert Rules](alert-rules.md) for the rule format and [Delivery channels](alert-rules.md#delivery-channels) for notifications. The default for `notify_on_anomalies` is `false`. Set it to `true` to let `cja-audit-log-monitor cli anomalies` send anomalies.

### Where the config file lives

The tool looks for the config file in this order:

1. The path you give with `-c` / `--config`, e.g. `cja-audit-log-monitor -c ./config.yaml cli list`. The option goes before `cli` or `tui`. The file can be YAML or JSON, because the tool reads JSON as YAML.
2. The path in the `CJA_CONFIG_PATH` environment variable. A `~` at the start is read as your home folder.
3. `~/.cja-audit-log-monitor/config.yaml`.

`cli init` writes to the same path that the tool reads. `cli config` shows which path is in use, and adds "(not found)" when the file does not exist. A path that you name must exist. If the file you give with `-c` or with `CJA_CONFIG_PATH` does not exist, or is a folder, the tool stops with a `Configuration error:` line that names the path, and exits 1. It does not go on to another place. Only the default file, `~/.cja-audit-log-monitor/config.yaml`, can be absent. `cli init` is the exception, because it creates the file.

### The file is private

When `cli init` creates the folder, it makes it so that only you can open it (mode 0700). It does not change a folder that already exists. It refuses to write through a symbolic link. It creates the file so that only you can read it (mode 0600). The file can hold webhook URLs and `Authorization` headers, so keep it that way.

If other users can read the file, the tool gives a warning each time it loads the file. The warning suggests `chmod 600` with the file's path. The tool gives the same warning for a profile, and for a `.env` file that holds a credential field.

### Which value wins

This order is for every setting except the four credential fields. For the credential, see [Where the credential comes from](#where-the-credential-comes-from).

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
| `default_days` | 7 | 1 to 3,650 | The TUI dashboard and stats views. It is also the default for `--days` when you leave it off (`user`, `export`, `stats`, `report`, `timeline`, `find-action` and `top-users`). |
| `monitor_interval` | 60 | 5 to 86,400 | The starting value of the TUI monitor interval box. It is also the default for `cli monitor --interval`. |
| `alert_rules` | the built-in rules | A list of rules | See [Alert Rules](alert-rules.md). Leave the key out to use the built-in rules. `alert_rules: []` means no rules. |
| `notifications` | none | A block of channels | See [Delivery channels](alert-rules.md#delivery-channels). |

The config file can also hold the credential, with the keys `org_id`, `client_id`, `secret` and `scopes`. It must hold all four or none of them. A credential in the file you give with `-c` wins over the environment variables and `.env`. A credential in the default config file is used only when no other place holds one.

The two URLs must use https. Plain http is allowed only for `localhost` and `127.0.0.1`, which is useful for tests. Any other http URL stops the settings from loading. So does a URL that holds a user name or a password.

A value outside its allowed range stops the config file from loading. The error names the key and does not show the value. An older file that still has `output_format:` keeps working. The tool ignores that key and gives a warning. It also gives a warning for any other key it does not know. This includes keys inside a rule, inside the `notifications:` block and inside a webhook. The warning names where the key is, e.g. `alert_rules[0]: ignoring unknown setting 'treshold_count'`.

The CLI prints these warnings on stderr. The TUI shows them as toasts. The TUI has no log file.

### When the config file has an error

The CLI prints one line that starts with `Configuration error:` and names the problem. When the bad value came from the config file, the line names the file. When it came from an environment variable or `.env`, the line says `environment or .env`. Then it exits 1.

The TUI does the same. It prints the line and does not open, so it never runs with settings from another place. If the file breaks while the TUI is open and you use **reload settings** in the config view, the TUI keeps the settings it has and says why.

An error in the credential lookup is reported the same way, e.g. a profile that does not exist or a source that holds only some of the four fields.

## 5. Verify

```bash
cja-audit-log-monitor cli verify
```

The command signs in and then fetches one audit log entry. It reports the two steps separately. When both work, it prints `Connection successful`, your organization ID, the API URL and the number of logs available. When one fails, it prints the error with a code and what to do, and exits 1. See [Check the credential](cli.md#check-the-credential) for the codes and [Troubleshooting](troubleshooting.md) for more help.

To see where the tool finds the credential without a call to Adobe, run `cja-audit-log-monitor cli config`.
