# Google GA4 MCP

Multi-tenant Google Analytics 4 MCP with:

- a private Python MCP server on Railway
- client-scoped Cloudflare Workers
- an admin Cloudflare Worker with persisted property context
- tenant policies over allowed GA4 property IDs

## Layout

- `apps/mcp_server/`: FastAPI + FastMCP backend
- `apps/workers/client/`: client-scoped worker
- `apps/workers/admin/`: admin worker with persisted property context
- `docs/`: setup and deployment notes
- `infra/`: deploy examples

## Quick start

### Backend

```bash
cd apps/mcp_server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

### Workers

```bash
cd apps/workers
npm install
npm run typecheck
```

### Deploy

```bash
cd apps/workers
npm run deploy:admin
npm run deploy:client
```

Both deploy scripts use `--keep-vars`, so Worker names, vars and secrets configured in the Cloudflare dashboard are preserved.

## Railway deploy

This repository includes a root `Dockerfile` for the backend, so Railway can deploy it directly from the repository root.

Recommended Railway service config:

- root directory: repository root
- builder: Dockerfile autodetect
- start command: none, use the Docker `CMD`

Required backend environment variables on Railway:

- `APP_ENV=production`
- `DATABASE_URL=<railway postgres url>`
- `GOOGLE_OAUTH_CLIENT_ID=<google oauth client id>`
- `GOOGLE_OAUTH_CLIENT_SECRET=<google oauth client secret>`
- `GOOGLE_OAUTH_REFRESH_TOKEN=<google oauth refresh token>`
- `WORKER_SHARED_SECRET_SALT=<random-long-secret>`
- `ADMIN_API_SHARED_SECRET=<shared-secret-for-/api/v1>`
- `REQUEST_TTL_SECONDS=300`

## Operations

- runbook: [docs/runbook.md](/Users/pedroivoborgesraimundo/dev/google_ga4_mcp/docs/runbook.md)
- deploy guide: [docs/deploy.md](/Users/pedroivoborgesraimundo/dev/google_ga4_mcp/docs/deploy.md)
- setup guide: [docs/setup.md](/Users/pedroivoborgesraimundo/dev/google_ga4_mcp/docs/setup.md)
- architecture: [docs/architecture.md](/Users/pedroivoborgesraimundo/dev/google_ga4_mcp/docs/architecture.md)
- Google OAuth: [docs/google-oauth.md](/Users/pedroivoborgesraimundo/dev/google_ga4_mcp/docs/google-oauth.md)

## Security model

- Google OAuth credentials live only in the backend.
- Workers authenticate to the backend with worker-specific secrets and HMAC signatures.
- Client workers never choose arbitrary tenant ids or property ids.
- Admin flows operate through an explicit property context resolved from synced properties.
