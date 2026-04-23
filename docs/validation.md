# Validation

Current validation should focus on the backend-only flow:

1. Backend health checks pass.
2. Admin UI login works.
3. A Google source can be created and synced.
4. Synced GA4 assets appear in the UI.
5. A client can be created and linked to one or more assets.
6. A client bearer token can call `tools/list`.
7. A single-asset client sees GA4 reporting tools without context-switching tools.
8. A multi-asset client sees `list_my_properties`, `select_my_property`, and `clear_active_context`.
