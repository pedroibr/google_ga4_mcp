# Google OAuth

The backend authenticates to Google Analytics using a single OAuth refresh token stored in Railway environment variables.

Required variables:

- `GOOGLE_OAUTH_CLIENT_ID`
- `GOOGLE_OAUTH_CLIENT_SECRET`
- `GOOGLE_OAUTH_REFRESH_TOKEN`

The backend refreshes short-lived access tokens automatically and uses the authenticated Google account to list GA4 properties, read Admin API metadata, and execute Data API reports.

Recommended OAuth scopes for the connected Google account:

- Google Analytics read-only access to the GA4 properties you want to expose

Keep the OAuth credentials only in the backend. Cloudflare Workers should never receive Google OAuth secrets.
