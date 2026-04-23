# GA4 MCP Server

FastAPI service that provides:

- `/admin` UI for sources, clients, asset links, and MCP tokens
- `/mcp/ga4/clients/{client_slug}` authenticated MCP endpoint
- `/mcp/ga4/public/{public_token}` optional public MCP endpoint
- encrypted source credentials for Google OAuth refresh-token access

Run tests with:

```bash
pytest
```
