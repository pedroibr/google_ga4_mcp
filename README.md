# Google GA4 MCP

Multi-client Google Analytics 4 MCP gateway with:

- one FastAPI backend
- an admin UI for clients, Google sources, and GA4 asset links
- per-client MCP bearer/public URLs
- encrypted Google OAuth credentials per source

## Layout

- `apps/mcp_server/`: FastAPI backend, admin UI, direct MCP endpoints, GA4 tools
- `docs/`: setup, deployment, and architecture notes
- `infra/railway/`: Railway deployment notes

## Quick Start

```bash
cd apps/mcp_server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Run locally:

```bash
uvicorn app.main:app --reload
```

Open `/admin`, create a source with Google OAuth credentials, sync GA4 assets, create a client, link one or more assets, then rotate the client bearer token.

## Required Environment

- `APP_ENV=production`
- `DATABASE_URL=<postgres url>`
- `APP_BASE_URL=<public backend url>`
- `ADMIN_UI_PASSWORD=<admin login password>`
- `ADMIN_SESSION_SECRET=<random-long-secret>`
- `CLIENT_TOKEN_SALT=<random-long-secret>`
- `CREDENTIALS_ENCRYPTION_KEY=<random-long-secret>`

`ADMIN_API_SHARED_SECRET` is still accepted for the legacy tenant API, but it is not part of the primary UI-based flow.

## MCP URLs

Authenticated client URL:

```text
https://<backend>/mcp/ga4/clients/<client-slug>
```

Use:

```text
Authorization: Bearer <client-token>
```

Optional public URL:

```text
https://<backend>/mcp/ga4/public/<public-token>
```

## Security Model

- Google OAuth credentials are stored only in the backend and encrypted at rest.
- Each source represents one Google user/account credential set.
- Clients receive only the GA4 assets explicitly linked in the UI.
- Context-switching tools are shown only when a client has more than one linked GA4 asset.
