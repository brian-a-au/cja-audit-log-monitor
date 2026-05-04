# Troubleshooting

## OAuth errors

| Error | Likely cause | Fix |
|---|---|---|
| `invalid_client` | Client ID or Secret wrong/expired | Re-retrieve from Developer Console; check for whitespace |
| `invalid_scope` | `SCOPES` differs from the Developer Console string | Re-copy verbatim from OAuth Server-to-Server → Scopes |
| `unauthorized_client` | OAuth Server-to-Server not enabled for the credential | Confirm the credential type in Developer Console |
| `401 Unauthorized` | Token expired or credentials regenerated | Re-retrieve the client secret |
| `403 Forbidden` | Missing AEP API association, or product profile not assigned | Add Experience Platform API to the project; verify Admin Console product-profile assignments |

After permission changes in Admin Console, allow **5–10 minutes** for propagation before retrying.

## Setup checklist

- [ ] `ORG_ID` ends with `@AdobeOrg`
- [ ] Both **Customer Journey Analytics** and **Experience Platform API** added to the project
- [ ] OAuth Server-to-Server credential created
- [ ] `SCOPES` copied verbatim from the Developer Console
- [ ] Service account assigned to CJA product profile with Data View read access
- [ ] Service account assigned to an AEP product profile (required even for CJA-only use)

## Security

- Never commit `.env`, `config.json`, or any credential file. The repo's `.gitignore` already covers these.
- Rotate the client secret periodically via Developer Console.
- Use the minimum product-profile permissions required.

## Notification delivery

| Symptom | Likely cause | Fix |
|---|---|---|
| `Notification delivery failed (slack)` toast | Slack webhook URL invalid, expired, or rate-limited | Recreate the incoming webhook in Slack admin and update `notifications.slack_webhook_url` |
| `Notification delivery failed (https://...)` toast | Custom webhook returned 4xx/5xx or timed out | Check the receiving service; per-webhook timeout default is 30 s, override via `webhooks[].timeout` |
| First alert delivers but later ones don't, no warning | Per-session failure suppression engaged on a flapping channel | Check the application log for repeated `Failed to send ...` entries; warnings suppress after the first per channel until a successful send |
| Alert fires in TUI but nothing reaches Slack/webhook | `notify_on_alerts: false` set, or `notifications:` block missing | Set `notify_on_alerts: true` and confirm at least one of `slack_webhook_url` / `webhooks[]` is populated |
| Slow polling cycles when Slack is slow | Default 30 s webhook timeout > 5 s polling interval | Either raise the polling interval or lower per-webhook `timeout` |

**Anomaly delivery silently disabled.** If `cja-audit cli anomalies` runs but
nothing reaches Slack/webhook, check that `notify_on_anomalies: true` is set
in your `notifications:` block. The default is `false`.

**Anomaly delivery shares the alert failure-warning channel.** A failing Slack
URL surfaces one warning per session — whether triggered from `cli monitor` or
`cli anomalies`. Subsequent failures on the same channel are suppressed until
the next successful send to that channel.

## Where to look first

If something is off and you don't know which screen to suspect, open the [Settings screen](screens/settings.md) inside the TUI and click **Verify Connection** — a red status with an error string is almost always more actionable than a silent empty result elsewhere.
