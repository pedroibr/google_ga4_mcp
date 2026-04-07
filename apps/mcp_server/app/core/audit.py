from __future__ import annotations

import json

from sqlalchemy.orm import Session

from app.core.context import OperationalContext, WorkerRequestContext
from app.db.models import AuditLog


class AuditService:
    def record(
        self,
        session: Session,
        request_context: WorkerRequestContext,
        tool_name: str,
        result_summary: dict | str,
        status: str = "success",
        resolved_context: OperationalContext | None = None,
    ) -> None:
        context = resolved_context or request_context.operational_context
        summary = json.dumps(
            {
                "tool": tool_name,
                "status": status,
                "context": {
                    "tenant_id": context.tenant_id if context else request_context.tenant_id,
                    "active_property_id": context.active_property_id if context else None,
                },
                "count_returned": _extract_count(result_summary),
                "payload": result_summary,
            }
        )
        record = AuditLog(
            execution_profile=request_context.execution_profile.value,
            worker_key_id=request_context.worker_key_id,
            tenant_id=request_context.tenant_id or (context.tenant_id if context else None),
            resolved_context_json=context.model_dump() if context else {},
            tool_name=tool_name,
            request_summary=json.dumps(request_context.raw_arguments),
            result_summary=summary,
            status=status,
        )
        session.add(record)
        session.commit()


def _extract_count(result_summary: dict | str) -> int | None:
    if not isinstance(result_summary, dict):
        return None
    data = result_summary.get("data")
    if isinstance(data, list):
        return len(data)
    return None
