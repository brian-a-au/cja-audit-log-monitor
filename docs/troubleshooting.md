# Troubleshooting

## OAuth errors

| Error | Likely cause | Fix |
|---|---|---|
| `invalid_client` | The client ID or secret is wrong or has expired. | Copy them again from the Developer Console. Check for extra spaces. |
| `invalid_scope` | `SCOPES` is not the same as the string in the Developer Console. | Copy the scopes again, exactly as the OAuth Server-to-Server credential page shows them. |
| `unauthorized_client` | The credential is not an OAuth Server-to-Server credential. | Check the credential type in the Developer Console. |
| `401 Unauthorized` | The token has expired, or someone made a new secret. | Retrieve the client secret again. |
| `403 Forbidden` | The project is missing the Experience Platform API, or the product profile is not assigned. | Add the Experience Platform API to the project. Check the product profile assignments in the Admin Console. |

After you change permissions in the Admin Console, wait 5 to 10 minutes before you try again.

## Messages in the CLI

Each CLI error prints one line to stderr and exits 1. The line starts with the kind of error:

- `Configuration error:` means the config file or a setting is wrong. The message names the file and the setting. It does not show the value, so it never shows a secret.
- `Authentication error:` means login failed. See [OAuth errors](#oauth-errors).
- `API error:` means Adobe returned an error. The message gives the status code.
- `File error:` means the tool could not write a file, e.g. the folder does not exist or the file already exists. For an existing file, add `--force` to replace it.

A usage error, e.g. an unknown flag or a value below the minimum, exits 2. See [Exit codes](cli.md#exit-codes).

`ORG_ID must end with @AdobeOrg` means the organization ID is incomplete. Copy the whole value from the Developer Console.

`must be an https:// URL` means `API_BASE_URL` or `IMS_BASE_URL` uses plain http. Use https. Plain http is allowed only for `localhost` and `127.0.0.1`.

If the tool keeps using old credentials after you edit `.env`, check your shell. An environment variable with the same name beats the value in `.env`, and the name can be in any case, e.g. `org_id`. Run `unset ORG_ID CLIENT_ID SECRET SCOPES` (and the lowercase names) to clear them.

The tool retries a 429 (rate limit) response and a 500, 502, 503 or 504 response a few times. It waits as long as the `Retry-After` header asks, but never more than 60 seconds. If the last try still fails, you see the error.

## Messages in the TUI

When a view can't load data, it shows one of these messages with the error from Adobe:

- **not connected** means that login failed, or the app could not reach Adobe. Check your credentials on the config screen (`c`), or run `cja-audit-log-monitor cli verify`.
- **access denied** means that Adobe returned 403. The API credential needs a CJA product profile and the right scopes.
- **request rejected** means that Adobe returned 400. Check the filters or the number of days, then press `r`.
- **could not load data** means any other error. Press `r` to try again.

The header shows `disconnected` after a login or network failure in any view. It shows `connected` again after the next successful load.

If the config file has an error, the TUI still starts. It uses only the environment variables and `.env`, and the header shows a short warning that names the file and the problem. Fix the file and press **reload settings** on the config screen.

## Setup checklist

- [ ] `ORG_ID` ends with `@AdobeOrg`.
- [ ] The project has both the **Customer Journey Analytics** API and the **Experience Platform API**.
- [ ] The credential is an OAuth Server-to-Server credential.
- [ ] `SCOPES` is copied exactly from the Developer Console.
- [ ] The service account is assigned to a CJA product profile that can read your data views.
- [ ] The service account is assigned to an AEP product profile. You need this even if you use only CJA.

## Security

- Never commit `.env` or any other file with credentials. The repository's `.gitignore` already covers `.env` and `.env.*`.
- Keep the config file private. `cli init` creates it with mode 0600. If other users can read it, the tool logs a warning that suggests `chmod 600`.
- Export files are also created with mode 0600. They can hold user emails and IP addresses, so take care where you share them.
- Change the client secret from time to time in the Developer Console.
- Give the service account only the product profile permissions it needs.

## Notification delivery

| What you see | Likely cause | Fix |
|---|---|---|
| A toast that starts with `Notification delivery failed (slack,` | The Slack webhook URL is wrong or expired, or Slack is limiting requests. | Create the incoming webhook again in Slack and update `notifications.slack_webhook_url`. |
| A toast such as `Notification delivery failed (https://example.com/…)` | The webhook returned a 4xx or 5xx error, or it did not reply in time. | Check the service that receives the webhook. The timeout is 30 seconds unless you set `webhooks[].timeout`. |
| The first alert arrives, later ones do not, and you see no warning | The tool shows only the first failure on each channel in a session. | Look in the log for repeated `Failed to send` lines. The warning comes back after a send to that channel works. |
| An alert fires in the TUI but nothing reaches Slack or the webhook | `notify_on_alerts` is `false`, or there is no `notifications:` block. | Set `notify_on_alerts: true`, and set `slack_webhook_url` or at least one entry in `webhooks`. |
| Polls are slow when Slack is slow | A webhook timeout of 30 seconds is longer than a short polling interval. | Use a longer polling interval, or a shorter `timeout` for the webhook. |

The failure messages and logs never show the full webhook or Slack URL. They show only `https://` and the host name, because the rest of the URL can hold a secret.

If `cja-audit-log-monitor cli anomalies` runs but nothing reaches Slack or the webhook, check that `notify_on_anomalies: true` is set in your `notifications:` block. The default is `false`.

Anomalies use the same failure warnings as alerts. A Slack URL that fails shows one warning in a session, whether the send came from `cli monitor` or from `cli anomalies`. Later failures on that channel show no warning until a send to it works again.

## Where to look first

If something is wrong and you don't know which screen to check, open the [config screen](screens/settings.md) in the TUI and click **verify connection**. The error it shows usually tells you more than an empty table on another screen.
