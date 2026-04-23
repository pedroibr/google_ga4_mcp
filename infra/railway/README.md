# Railway

Deploy the repository root as one Docker-backed service plus one Postgres database.

Required variables:

- `APP_ENV=production`
- `DATABASE_URL=${{Postgres.DATABASE_URL}}`
- `APP_BASE_URL=https://<your-service>.up.railway.app`
- `ADMIN_UI_PASSWORD=<admin login password>`
- `ADMIN_SESSION_SECRET=<random-long-secret>`
- `CLIENT_TOKEN_SALT=<random-long-secret>`
- `CREDENTIALS_ENCRYPTION_KEY=<random-long-secret>`
