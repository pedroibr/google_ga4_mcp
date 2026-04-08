# Validation Log

This document records the live setup and validation work completed for this project on April 7, 2026.

## Production endpoints

- Railway backend: `https://googlega4mcp-production.up.railway.app`
- Admin Worker: `https://google-ga4-mcp-admin.pedro-aa4.workers.dev`
- Client Worker `Luis-Alves`: `https://google-ga4-mcp-client-luis-alves.pedro-aa4.workers.dev`
- Client Worker `Okudus-Crislei-Leonel`: `https://google-ga4-mcp-client-okudus-crislei-leonel.pedro-aa4.workers.dev`

## Railway validation

- Railway project deployed successfully from the repository root using the root `Dockerfile`.
- `GET /` returned `200 OK`.
- `GET /health` returned `200 OK`.
- Backend service and Postgres service were both healthy in Railway production.

## Bootstrapped workers and tenants

### Admin worker

- Worker key id: `worker-admin-main`
- Worker type: `admin`

### Tenant `Luis-Alves`

- `tenant_id`: `tenant_luis_alves`
- `tenant_slug`: `luis-alves`
- `default_property_id`: `346065983`
- Client worker key id: `worker-client-luis-alves`

### Tenant `Okudus-Crislei-Leonel`

- `tenant_id`: `tenant_okudus_crislei_leonel`
- `tenant_slug`: `okudus-crislei-leonel`
- `default_property_id`: `390435153`
- Client worker key id: `worker-client-okudus-crislei-leonel`

Worker secrets are intentionally not stored in this document.

## Live MCP checks

### Admin worker

- MCP `initialize` succeeded.
- `tools/list` succeeded.
- `select_client_context` succeeded for `Luis-Alves`.
- `get_property_details` succeeded for property `346065983`.

The GA4 property metadata returned:

- property display name: `Website Novo`
- account: `accounts/47968213`
- time zone: `Europe/Lisbon`
- currency: `EUR`
- measurement ID present for a web stream: `G-X15PPT3P3F`
- default URI present: `https://luisalvesoficial.com`

### Traffic overview: `Luis-Alves`

`get_traffic_overview` for the last 28 days returned:

- sessions: `6340`
- total users: `3573`
- new users: `2913`
- engaged sessions: `3510`
- engagement rate: `55.36%`
- screen/page views: `18623`

Top channels included:

- `Paid Search`: `1422` sessions
- `Email`: `1295` sessions
- `Direct`: `1142` sessions
- `Paid Social`: `985` sessions
- `Organic Search`: `730` sessions

### Top pages: `Luis-Alves`

The top page report for the last 28 days returned, among others:

- `/funil/tfco/tfco-med-cadastro/`
- `/fco-biblioteca/`
- `/login/`
- `/funil/fco/fco-inscricao/`
- `/funil/tfco/tfco-apresentacao/`

### Top pages: `Okudus-Crislei-Leonel`

The client worker for `Okudus-Crislei-Leonel` also worked end to end.
The top page report for the last 28 days returned, among others:

- `/funil/adi/adi-inscricao/`
- `/`
- `/cursos/`
- `/tutors-hub/`
- `/tutor/the-bridge-to-alignment-a1/`

## Event validation

### Event counts: `Luis-Alves`

The GA4 event report for the last 28 days confirmed that events are arriving for property `346065983`.
Notable event counts:

- `generate_lead`: `1789`
- `mql`: `1233`
- `form_submit`: `231`
- `begin_checkout`: `457`
- `purchase`: `40`

This confirmed that the property had event activity even when a key-event based conversion report returned no rows in a different property.

### Generate lead by channel: `Luis-Alves`

`generate_lead` broken down by `sessionDefaultChannelGroup` for the last 28 days returned:

- `Unassigned`: `1017`
- `Paid Social`: `370`
- `Paid Search`: `273`
- `Email`: `67`
- `Organic Social`: `29`
- `Direct`: `19`
- `Organic Search`: `10`
- `Organic Video`: `4`

## Unassigned investigation

The `Unassigned` `generate_lead` traffic for `Luis-Alves` was investigated further.

Findings:

- `sessionSourceMedium` for the `Unassigned` leads was entirely `(not set)`.
- The largest concentration was on `/funil/tfco/tfco-med-cadastro/`.
- Several affected rows also had `pageTitle` as `(not set)` or empty.

Interpretation:

- the `generate_lead` event is arriving
- but a large share of those events is not carrying attributable session source/medium
- this suggests an instrumentation or attribution issue rather than a reporting issue

Probable causes to review:

- server-side or Measurement Protocol events sent without the correct `client_id` or `session_id`
- redirects or cross-domain flows breaking session continuity before the lead event
- custom `generate_lead` dispatches firing without the expected GA4/GTM context
- lead events emitted after the original page/session context is lost
