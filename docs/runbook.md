# Runbook

## Health

Check:

```text
/health
/healthz
```

Both should return `status: ok`.

## Source Sync Fails

1. Open `/admin/sources`.
2. Check the source status and last sync error.
3. Re-enter the Google OAuth client ID, client secret, and refresh token if the token was revoked or rotated.
4. Run sync again.

## Client Cannot Access GA4 Data

1. Confirm the client is active.
2. Confirm at least one GA4 asset is linked to the client.
3. Confirm the linked asset still has a source.
4. Confirm the source is active and syncs successfully.
5. Rotate the bearer token and update the MCP client configuration.

## Context Tools Missing

This is expected when a client has only one linked GA4 asset. Context-switching tools are visible only when the client has two or more linked assets.
