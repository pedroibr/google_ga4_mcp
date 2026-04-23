# Architecture

## Components

### Backend

The FastAPI backend serves the admin UI and direct MCP endpoints. It owns all database access, credential encryption, Google token refresh, GA4 Admin API sync, GA4 Data API calls, and audit persistence.

### Sources

A source is a reusable Google OAuth credential set:

- Google OAuth client ID
- Google OAuth client secret
- Google refresh token

The UI stores these values encrypted. Syncing a source calls the GA4 Admin API, imports visible properties and streams, and records metadata in the asset directory.

### Clients

A client is an MCP-facing customer context. Clients can be linked to one or more synced GA4 assets. A client has:

- status
- default GA4 property
- bearer token hash
- optional public token hash

## MCP Request Flow

1. The caller sends MCP JSON-RPC to `/mcp/ga4/clients/{client_slug}` with a bearer token, or to `/mcp/ga4/public/{public_token}`.
2. The backend authenticates the token against the client.
3. The backend loads the client’s linked GA4 assets.
4. If the client has one asset, that property is the implicit active context.
5. If the client has multiple assets, session context can select a different active property.
6. The active property resolves to its source credentials.
7. The backend refreshes a Google access token and calls the GA4 APIs.

## Context Tools

All clients can call GA4 reporting tools and `get_active_context`.

The following tools are visible only when a client has more than one linked GA4 asset:

- `list_my_properties`
- `select_my_property`
- `clear_active_context`
