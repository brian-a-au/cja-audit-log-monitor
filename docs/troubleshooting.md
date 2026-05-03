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

## Where to look first

If something is off and you don't know which screen to suspect, open the [Settings screen](screens/settings.md) inside the TUI and click **Verify Connection** — a red status with an error string is almost always more actionable than a silent empty result elsewhere.
