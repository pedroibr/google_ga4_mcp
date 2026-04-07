# MCP Server

Private backend that:

- validates worker authentication and HMAC signatures
- resolves tenant policy and operational context
- persists admin operational context by `worker_key_id + worker_session_id`
- calls the Google Analytics Data API and Admin API with OAuth refresh tokens
- exposes MCP tools over streamable HTTP
- exposes an admin HTTP API under `/api/v1`
