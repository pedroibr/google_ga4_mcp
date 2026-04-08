# Deploy

## 1. GitHub

1. Create a new GitHub repository.
2. Push the project root.
3. Keep `apps/mcp_server` and `apps/workers` in the same repository.

## 2. Railway backend

Create one Railway project with:

- one service pointing to the repository root
- one Postgres database

This repo includes a root `Dockerfile`, so Railway can use Docker autodetect directly.

Variables:

- `APP_ENV=production`
- `DATABASE_URL=${{Postgres.DATABASE_URL}}`
- `GOOGLE_OAUTH_CLIENT_ID=<google oauth client id>`
- `GOOGLE_OAUTH_CLIENT_SECRET=<google oauth client secret>`
- `GOOGLE_OAUTH_REFRESH_TOKEN=<google oauth refresh token>`
- `WORKER_SHARED_SECRET_SALT=<random-long-secret>`
- `ADMIN_API_SHARED_SECRET=<shared-secret-for-/api/v1>`
- `REQUEST_TTL_SECONDS=300`

The backend normalizes Railway Postgres URLs automatically to use the `psycopg` SQLAlchemy driver, so you can keep the raw Railway `DATABASE_URL` reference.

## 3. Bootstrap tenant and worker credentials

After the backend is up, run commands inside the deployed Railway service with:

```bash
railway ssh -s google-ga4-mcp -- <command>
```

Example client bootstrap:

```bash
railway ssh -s google-ga4-mcp -- python -m app.bootstrap \
  --tenant-id tenant_luis \
  --tenant-slug luis \
  --tenant-name "Luis Analytics" \
  --default-property-id 123456789 \
  --allowed-properties '[{"property_id":"123456789","display_name":"Luis Main","measurement_ids":["G-AAAA1111"],"default_uri":"https://www.luis.com"},{"property_id":"987654321","display_name":"Luis Blog","measurement_ids":["G-BBBB2222"],"default_uri":"https://blog.luis.com"}]' \
  --worker-type client \
  --worker-key-id worker-client-luis \
  --worker-secret <random-secret>
```

For the admin worker:

```bash
railway ssh -s google-ga4-mcp -- python -m app.bootstrap \
  --worker-type admin \
  --worker-key-id worker-admin-main \
  --worker-secret <random-secret>
```

## 4. Cloudflare workers

Deploy one client worker per tenant and one admin worker.

Install dependencies once:

```bash
cd apps/workers
npm install
cp admin/wrangler.toml.template admin/wrangler.toml
cp client/wrangler.toml.template client/wrangler.toml
```

Verify Cloudflare auth:

```bash
npx wrangler whoami
```

The repository keeps only:

- `apps/workers/admin/wrangler.toml.template`
- `apps/workers/client/wrangler.toml.template`

Create local `wrangler.toml` files from those templates before deploying.

### Client worker variables

- `BACKEND_URL=https://<your-railway-service>.up.railway.app`
- `TENANT_ID=tenant_luis`
- `WORKER_KEY_ID=worker-client-luis`
- `WORKER_SECRET=<same secret used in bootstrap>`
- optional `INBOUND_AUTH_TOKEN=<token required from callers of this worker>`

Deploy:

```bash
cd apps/workers
npm run deploy:client
```

### Admin worker variables

- `BACKEND_URL=https://<your-railway-service>.up.railway.app`
- `WORKER_KEY_ID=worker-admin-main`
- `WORKER_SECRET=<same secret used in bootstrap>`
- optional `INBOUND_AUTH_TOKEN=<token required from callers of this worker>`

Session behavior:

- OpenAI/MCP callers are keyed primarily by `x-openai-session`, with fallback to `x-openai-subject`
- other MCP clients fall back to `mcp-session-id`
- the selected admin context is persisted in the backend database per `worker_key_id + worker_session_id`

Deploy:

```bash
cd apps/workers
npm run deploy:admin
```

## 5. Smoke test

First verify the backend with:

```text
/
```

or:

```text
/health
```

Call the client worker with MCP `tools/list`, then `tools/call` for `get_traffic_overview`.

Call the admin worker with:

1. `search_properties`
2. `select_client_context` or `select_property_context`
3. `get_active_context`
4. `get_traffic_overview`

## 6. Production state documented on April 7, 2026

See [docs/validation.md](/Users/pedroivoborgesraimundo/dev/google_ga4_mcp/docs/validation.md) for the live validation log covering:

- Railway health checks
- tenant onboarding
- Cloudflare Worker deployment
- live analytics checks for `Luis-Alves`
- live analytics checks for `Okudus-Crislei-Leonel`
- investigation notes for `Unassigned` `generate_lead` traffic

## 7. Admin API

The backend also exposes a separate admin API under `/api/v1`.

Typical checks:

```bash
curl -sS https://<backend>/api/v1/tenants \
  -H "Authorization: Bearer <ADMIN_API_SHARED_SECRET>"
```

```bash
curl -sS https://<backend>/api/v1/tenants/tenant_luis \
  -H "Authorization: Bearer <ADMIN_API_SHARED_SECRET>"
```
