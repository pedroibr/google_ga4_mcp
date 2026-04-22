# Deploy

## 1. Railway Backend

Create one Railway project with:

- one service pointing to the repository root
- one Postgres database

This repo includes a root `Dockerfile`, so Railway can use Docker autodetect directly.

Required variables:

- `APP_ENV=production`
- `DATABASE_URL=${{Postgres.DATABASE_URL}}`
- `APP_BASE_URL=https://<your-service>.up.railway.app`
- `ADMIN_UI_PASSWORD=<admin login password>`
- `ADMIN_SESSION_SECRET=<random-long-secret>`
- `CLIENT_TOKEN_SALT=<random-long-secret>`
- `CREDENTIALS_ENCRYPTION_KEY=<random-long-secret>`

The backend normalizes Railway Postgres URLs automatically to use the `psycopg` SQLAlchemy driver.

## 2. Admin UI Setup

Open:

```text
https://<your-service>.up.railway.app/admin
```

Then:

1. Create a source with Google OAuth client ID, client secret, and refresh token.
2. Sync the source to import visible GA4 properties.
3. Create a client.
4. Link one or more GA4 assets to that client.
5. Rotate the client bearer token.

## 3. MCP Usage

Authenticated endpoint:

```text
https://<your-service>.up.railway.app/mcp/ga4/clients/<client-slug>
```

Use:

```text
Authorization: Bearer <client-token>
```

Optional public endpoint, if enabled in the UI:

```text
https://<your-service>.up.railway.app/mcp/ga4/public/<public-token>
```

## 4. Smoke Test

Call `tools/list` on the client MCP URL.

Expected behavior:

- client with one linked GA4 asset: GA4 reporting tools are visible
- client with multiple linked GA4 assets: property context tools are also visible
