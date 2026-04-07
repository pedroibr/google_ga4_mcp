# Admin API

Base path:

- `/api/v1`

## Authentication

Accepted headers:

- `Authorization: Bearer <ADMIN_API_SHARED_SECRET>`
- `X-Admin-Api-Key: <ADMIN_API_SHARED_SECRET>`

## Endpoints

### `POST /api/v1/client-tenants/upsert`

Required fields:

- `tenant_id`
- `tenant_slug`
- `tenant_name`
- `worker_key_id`
- `worker_secret`
- `allowed_properties`

Optional fields:

- `default_property_id`

Each item inside `allowed_properties` supports:

- `property_id`
- `display_name`
- `measurement_ids`
- `account_id`
- `default_uri`

### `GET /api/v1/tenants`

List tenants.

### `GET /api/v1/tenants/{tenant_id}`

Show tenant details.

### `DELETE /api/v1/tenants/{tenant_id}`

Delete tenant, policies, worker credentials and audit rows.
