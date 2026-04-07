from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import OperationalContext
from app.db.models import WorkerSessionContext


_context_store: dict[tuple[str, str], OperationalContext] = {}


def load_context(worker_key_id: str, worker_session_id: str) -> OperationalContext | None:
    key = (worker_key_id, worker_session_id)
    context = _context_store.get(key)
    print(
        f"[session_context_store] load key={key} hit={context is not None} keys={list(_context_store.keys())}",
        flush=True,
    )
    return context


def save_context(worker_key_id: str, worker_session_id: str, context: OperationalContext) -> None:
    key = (worker_key_id, worker_session_id)
    _context_store[key] = context
    print(f"[session_context_store] save key={key} context={context.model_dump()}", flush=True)


def clear_context(worker_key_id: str, worker_session_id: str) -> None:
    key = (worker_key_id, worker_session_id)
    _context_store.pop(key, None)
    print(f"[session_context_store] clear key={key}", flush=True)


def load_admin_context(
    session: Session,
    worker_key_id: str,
    worker_session_id: str,
) -> OperationalContext | None:
    row = session.scalar(
        select(WorkerSessionContext).where(
            WorkerSessionContext.worker_key_id == worker_key_id,
            WorkerSessionContext.worker_session_id == worker_session_id,
        )
    )
    if row is None:
        return None
    return OperationalContext.model_validate(row.context_json)


def save_admin_context(
    session: Session,
    worker_key_id: str,
    worker_session_id: str,
    context: OperationalContext,
) -> None:
    row = session.scalar(
        select(WorkerSessionContext).where(
            WorkerSessionContext.worker_key_id == worker_key_id,
            WorkerSessionContext.worker_session_id == worker_session_id,
        )
    )
    if row is None:
        row = WorkerSessionContext(
            worker_key_id=worker_key_id,
            worker_session_id=worker_session_id,
            context_json=context.model_dump(),
        )
        session.add(row)
    else:
        row.context_json = context.model_dump()
    session.commit()


def clear_admin_context(session: Session, worker_key_id: str, worker_session_id: str) -> None:
    row = session.scalar(
        select(WorkerSessionContext).where(
            WorkerSessionContext.worker_key_id == worker_key_id,
            WorkerSessionContext.worker_session_id == worker_session_id,
        )
    )
    if row is None:
        return
    session.delete(row)
    session.commit()
