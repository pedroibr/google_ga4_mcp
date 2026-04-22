# Google OAuth

Each source in the admin UI stores one Google OAuth credential set:

- OAuth client ID
- OAuth client secret
- refresh token

Use a Google user that can access the GA4 accounts/properties you want to expose. After saving the source, run sync in the UI to import the visible GA4 properties and streams.

Credentials are encrypted in the backend database and are never exposed through MCP responses.
