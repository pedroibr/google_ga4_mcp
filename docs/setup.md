# Setup

## Backend

```bash
cd apps/mcp_server
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Create `.env`:

```bash
APP_ENV=development
DATABASE_URL=sqlite+pysqlite:///./local.db
APP_BASE_URL=http://localhost:8000
ADMIN_UI_PASSWORD=change-me
ADMIN_SESSION_SECRET=change-me-long-random
CLIENT_TOKEN_SALT=change-me-long-random
CREDENTIALS_ENCRYPTION_KEY=change-me-long-random
```

Run:

```bash
uvicorn app.main:app --reload
```

Open:

```text
http://localhost:8000/admin
```

## Google Source Credentials

For each source, paste the Google OAuth client ID, client secret, and refresh token into the UI. The backend encrypts these values and uses them to sync GA4 assets and refresh Google access tokens.
