# Troubleshooting

## OAuth errors

| Error | Likely cause | Fix |
|---|---|---|
| `invalid_client` | The client ID or secret is wrong or has expired. | Copy them again from the Developer Console. Check for extra spaces. |
| `invalid_scope` | `SCOPES` is not the same as the string in the Developer Console. | Copy the scopes again, exactly as the OAuth Server-to-Server credential page shows them. |
| `unauthorized_client` | The credential is not an OAuth Server-to-Server credential. | Check the credential type in the Developer Console. |
| `401 Unauthorized` | The token has expired, or someone made a new secret. | Retrieve the client secret again. |
| `403 Forbidden` | The project is missing the Experience Platform API, or the service account is not in a product profile with CJA access. The CLI message says to check the product profile. | Add the Experience Platform API to the project. Check the product profile assignments in the Admin Console. |

After you change permissions in the Admin Console, wait 5 to 10 minutes before you try again.

## Messages in the CLI

Each CLI error prints one line to stderr and exits 1. The line starts with the kind of error:

- `Configuration error:` means the config file or a setting is wrong. The message names the setting, and the file or `environment or .env`, depending on where the bad value came from. It does not show the value, so it never shows a secret.
- `Authentication error:` means login failed. See [OAuth errors](#oauth-errors).
- `Network error: could not reach <host>` means the tool could not reach that Adobe host, to log in or to call the API. Check your network connection.
- `API error:` means Adobe returned an error. The message gives the status code. For a 403, it also says to check the product profile.
- `Unexpected error:` means something the tool did not expect. Run the command again with `-v` to see the full traceback, and include it in a bug report.
- `File error:` means the tool could not write a file, e.g. the folder does not exist or the file already exists. For an existing file, add `--force` to replace it.

The `verify` command is the exception. It prints failures such as `Connection failed` or `Authentication failed: ...` on stdout, and then exits 1.

A usage error, e.g. an unknown flag or a value below the minimum, exits 2. See [Exit codes](cli.md#exit-codes).

`ORG_ID must end with @AdobeOrg` means the organization ID is incomplete. Copy the whole value from the Developer Console.

`must be an https:// URL` means `API_BASE_URL` or `IMS_BASE_URL` uses plain http. Use https. Plain http is allowed only for `localhost` and `127.0.0.1`.

If the tool keeps using old credentials after you edit `.env`, check your shell. The environment variables beat `.env`, and the names can be in any case, e.g. `org_id`. A profile named in `CJA_PROFILE` beats both. Run `cja-audit-log-monitor cli config` to see which place the tool uses. Run `unset CJA_PROFILE ORG_ID CLIENT_ID SECRET SCOPES` (and the lowercase names) to clear the variables.

If the error says that only some of the four credential fields are set, one place holds only part of a credential. The message names the place and the missing fields. Add the missing fields there, or remove the fields that are set there so that the tool goes on to the next place. The tool has no built-in scopes, so `SCOPES` is one of the four.

The tool retries a 429 (rate limit) response and a 500, 502, 503 or 504 response a few times. It waits as long as the `Retry-After` header asks, but never more than 60 seconds. If the last try still fails, you see the error.

## Messages in the TUI

When a view can't load data, it shows one of these messages with the error from Adobe:

- **not connected** means that login failed, or the app could not reach Adobe. Check your credentials in the config view (`c`), or run `cja-audit-log-monitor cli verify`.
- **access denied** means that Adobe returned 403. The API credential needs a CJA product profile and the right scopes.
- **request rejected** means that Adobe returned 400. Check the filters or the number of days, then press `r`.
- **could not load data** means any other error. Press `r` to try again.

The header shows `disconnected` after a login or network failure in any view. It shows `connected` again after the next successful load.

If the config file has an error, or a path you gave with `-c` or `CJA_CONFIG_PATH` does not exist, the TUI does not open. It prints one line that starts with `Configuration error:` and names the file and the problem. Fix the file and start the TUI again. If the file breaks while the TUI is open, **reload settings** in the config view keeps the settings it has and says why.

The TUI has no log file, and `-v` does not change what it shows. Warnings that the CLI prints on stderr, e.g. about unknown settings, file permissions or failed deliveries, appear as toasts in the TUI.

## Setup checklist

- [ ] `ORG_ID` ends with `@AdobeOrg`.
- [ ] The project has both the **Customer Journey Analytics** API and the **Experience Platform API**.
- [ ] The credential is an OAuth Server-to-Server credential.
- [ ] `SCOPES` is copied exactly from the Developer Console.
- [ ] The service account is assigned to a CJA product profile that can read your data views.
- [ ] The service account is assigned to an AEP product profile. You need this even if you use only CJA.

## Security

- Never commit `.env` or any other file with credentials. The repository's `.gitignore` already covers `.env` and `.env.*`.
- Keep the config file private. `cli init` creates it with mode 0600. If other users can read it, the tool gives a warning that suggests `chmod 600`.
- Export files are also created with mode 0600. They can hold user emails and IP addresses, so take care where you share them.
- Change the client secret from time to time in the Developer Console.
- Give the service account only the product profile permissions it needs.

## Notification delivery

| What you see | Likely cause | Fix |
|---|---|---|
| A warning that starts with `Notification delivery failed (slack (https://hooks.slack.com/…))` | The Slack webhook URL is wrong or expired, or Slack is limiting requests. | Create the incoming webhook again in Slack and update `notifications.slack_webhook_url`. |
| A warning such as `Notification delivery failed (webhook 2 (https://example.com/…))` | The webhook returned a redirect (3xx) or an error (4xx or 5xx), or it did not reply in time. Redirects are not followed. | Check the service that receives the webhook. The timeout is 30 seconds unless you set `webhooks[].timeout`. |
| The first alert arrives, later ones do not, and the `Notification delivery failed` warning does not show again | The tool shows that warning once for each failing channel. It shows it again only if the channel fails after it works again. | Look for the `Failed to send` lines, which show for every failed send. The CLI prints them on stderr, and the TUI shows them as toasts. |
| An alert fires in the TUI but nothing reaches Slack or the webhook | `notify_on_alerts` is `false`, or there is no `notifications:` block. | Set `notify_on_alerts: true`, and set `slack_webhook_url` or at least one entry in `webhooks`. |
| Polls are slow when Slack is slow | A webhook timeout of 30 seconds is longer than a short polling interval. | Use a longer polling interval, or a shorter `timeout` for the webhook. |

The failure messages and logs never show the full webhook or Slack URL. They show only `https://` and the host name, e.g. `https://example.com/…`, because the rest of the URL can hold a secret.

If `cja-audit-log-monitor cli anomalies` runs but nothing reaches Slack or the webhook, check that `notify_on_anomalies: true` is set in your `notifications:` block. The default is `false`.

Anomalies use the same failure warnings as alerts. Each failing channel shows one warning. Later failures on that channel show no warning until a send to it works again. A channel that failed gets the anomaly again on the next scan.

## Where to look first

If something is wrong and you don't know which view to check, open the [config view](screens/settings.md) in the TUI and click **verify connection**. The error it shows usually tells you more than an empty table in another view.
