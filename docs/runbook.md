# Runbook

## Key admin tools

- `search_properties`
- `list_tenant_contexts`
- `select_client_context`
- `select_property_context`
- `sync_account_properties`
- `get_active_context`

## Key analytics tools

- `get_property_details`
- `get_reporting_metadata`
- `run_report`
- `run_realtime_report`
- `get_traffic_overview`
- `get_page_performance`
- `compare_date_ranges`

## Common operational checks

- If admin queries fail before a context is selected, call `select_client_context` or `select_property_context` first.
- If a new property is visible in Google but not in the MCP, run `sync_account_properties`.
- If a client worker returns permission errors, confirm the property is in the tenant allowlist.
- If Google API requests fail, verify the Railway OAuth env vars and the Google account permissions on the target property.
- If conversion reports return zero rows but event reports show activity, verify whether the event is marked as a GA4 key event.
- If `sessionDefaultChannelGroup = Unassigned`, inspect `sessionSourceMedium`. If it is `(not set)`, the event is arriving without attributable session source/medium.
