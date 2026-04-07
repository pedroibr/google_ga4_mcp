# Cloudflare Workers

Deploy:

- one worker per tenant using `apps/workers/client/src/index.ts`
- one admin worker using `apps/workers/admin/src/index.ts`

Each worker must have its own `WORKER_KEY_ID` and `WORKER_SECRET`.
