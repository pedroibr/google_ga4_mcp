from __future__ import annotations

import json

from app.api.internal_auth import InternalAuthService
from app.api.mcp_http import MCPAuthenticationMiddleware
from app.core.context import ExecutionProfile, WorkerRequestContext
from app.core.session_context_store import load_admin_context
from app.db.models import WorkerCredential, WorkerCredentialStatus, WorkerType


async def _dummy_app(scope, receive, send):
    return None


def test_select_client_context_persists_admin_session_context(session, session_factory, settings) -> None:
    auth_service = InternalAuthService(settings)
    session.add(
        WorkerCredential(
            worker_type=WorkerType.admin,
            tenant_id=None,
            key_id="admin-key-2",
            secret_hash=auth_service.hash_secret("admin-secret-2", settings.worker_shared_secret_salt),
            status=WorkerCredentialStatus.active,
        )
    )
    session.commit()

    middleware = MCPAuthenticationMiddleware(_dummy_app, session_factory, auth_service)
    context = WorkerRequestContext(
        worker_key_id="admin-key-2",
        worker_type="admin",
        execution_profile=ExecutionProfile.admin_multi_asset,
        tenant_id=None,
        worker_session_id="session-123",
        tool_name="select_client_context",
        raw_arguments={"query": "luis"},
        operational_context=None,
    )
    response_payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(
                        {
                            "resolved": True,
                            "query": "luis",
                            "context": {
                                "tenant_id": "tenant_luis",
                                "active_property_id": "123456789",
                                "resolved_from_query": "luis",
                                "resolved_from_property_id": "123456789",
                            },
                        }
                    ),
                }
            ],
            "isError": False,
        },
    }

    middleware._persist_context_from_response(
        session,
        context,
        f"event: message\ndata: {json.dumps(response_payload)}\n\n",
    )

    saved = load_admin_context(session, "admin-key-2", "session-123")
    assert saved is not None
    assert saved.tenant_id == "tenant_luis"
    assert saved.active_property_id == "123456789"
