# Architecture

## Request flow

### Client worker

1. Receives MCP `tools/call`.
2. Hides admin-only tools from `tools/list`.
3. Restores the active GA4 property context from in-memory session state.
4. Signs the request.
5. Sends it to the private backend with a fixed tenant id.

### Admin worker

1. Receives MCP `tools/call`.
2. Hides client-only tools from `tools/list`.
3. Derives a stable session key from OpenAI or MCP session headers.
4. Signs the request and forwards it.
5. Does not keep operational context in worker memory.

### Backend

1. Validates worker secret and HMAC.
2. Loads tenant policy or admin operational context.
3. For admin requests, restores context from `worker_session_contexts`.
4. Enforces tenant GA4 property allowlists.
5. Calls the Google Analytics Data API or Admin API with a refreshed OAuth access token.
6. Persists audit logs.

### Admin API

1. Authenticates with `ADMIN_API_SHARED_SECRET`.
2. Creates, updates, lists, shows and deletes tenants under `/api/v1`.
