from __future__ import annotations

import contextvars
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class ExecutionProfile(str, Enum):
    client_scoped = "client_scoped"
    admin_multi_asset = "admin_multi_asset"


class OperationalContext(BaseModel):
    tenant_id: str | None = None
    active_property_id: str | None = None
    resolved_from_query: str | None = None
    resolved_from_property_id: str | None = None


class WorkerRequestContext(BaseModel):
    worker_key_id: str
    worker_type: str
    execution_profile: ExecutionProfile
    tenant_id: str | None = None
    worker_session_id: str | None = None
    tool_name: str | None = None
    raw_arguments: dict = Field(default_factory=dict)
    operational_context: OperationalContext | None = None


_request_context: contextvars.ContextVar[WorkerRequestContext | None] = contextvars.ContextVar(
    "request_context",
    default=None,
)


def set_request_context(context: WorkerRequestContext) -> contextvars.Token:
    return _request_context.set(context)


def reset_request_context(token: contextvars.Token) -> None:
    _request_context.reset(token)


def get_request_context(fastmcp: Any | None = None) -> WorkerRequestContext:
    if fastmcp is not None:
        try:
            mcp_context = fastmcp.get_context()
            request = mcp_context.request_context.request
            state_context = getattr(request.state, "worker_request_context", None)
            if state_context is not None:
                return state_context
        except Exception:
            pass

    context = _request_context.get()
    if context is None:
        raise RuntimeError("No worker request context is active")
    return context
