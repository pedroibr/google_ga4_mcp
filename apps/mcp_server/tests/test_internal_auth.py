from __future__ import annotations

from datetime import datetime, timezone
import json

from app.api.internal_auth import InternalAuthService, canonical_worker_message
from app.core.context import OperationalContext


def test_canonical_worker_message_includes_active_property() -> None:
    message = canonical_worker_message(
        request_name="run_report",
        payload={"metrics": ["sessions"]},
        tenant_id="tenant_luis",
        timestamp="2026-04-07T15:00:00Z",
        operational_context={"tenant_id": "tenant_luis", "active_property_id": "123456789"},
    )
    assert '"active_property_id":"123456789"' in message


def test_authenticate_request_with_explicit_context(seeded_db, settings) -> None:
    auth_service = InternalAuthService(settings)
    timestamp = datetime.now(timezone.utc).isoformat()
    payload = {"metrics": ["sessions"]}
    operational_context = OperationalContext(tenant_id="tenant_luis", active_property_id="123456789")
    signature = auth_service._build_signature(
        secret="client-secret",
        request_name="run_report",
        payload=payload,
        tenant_id="tenant_luis",
        timestamp=timestamp,
        operational_context=operational_context,
    )

    context = auth_service.authenticate_request(
        seeded_db,
        {
            "authorization": "Bearer client-secret",
            "x-worker-type": "client",
            "x-worker-key-id": "client-key-1",
            "x-tenant-id": "tenant_luis",
            "x-request-timestamp": timestamp,
            "x-context-signature": signature,
            "x-resolved-context": json.dumps({"tenant_id": "tenant_luis", "active_property_id": "123456789"}),
        },
        {
            "method": "tools/call",
            "params": {"name": "run_report", "arguments": payload},
        },
    )

    assert context.tenant_id == "tenant_luis"
    assert context.operational_context is not None
    assert context.operational_context.active_property_id == "123456789"
