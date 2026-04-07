# Setup

## Backend

```bash
cd apps/mcp_server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Create `.env` with at least:

```env
APP_ENV=development
DATABASE_URL=sqlite+pysqlite:///./local.db
GOOGLE_OAUTH_CLIENT_ID=...
GOOGLE_OAUTH_CLIENT_SECRET=...
GOOGLE_OAUTH_REFRESH_TOKEN=...
WORKER_SHARED_SECRET_SALT=change-me
ADMIN_API_SHARED_SECRET=change-me
REQUEST_TTL_SECONDS=300
```

Run locally:

```bash
uvicorn app.main:app --reload
```

## Workers

```bash
cd apps/workers
npm install
npm run typecheck
```

Use the `.dev.vars.example` files in `apps/workers/admin` and `apps/workers/client` as the starting point for local Wrangler secrets.
