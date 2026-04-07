from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timezone

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.context import ExecutionProfile, OperationalContext, WorkerRequestContext
from app.core.session_context_store import load_admin_context, load_context
from app.db.models import WorkerCredential, WorkerCredentialStatus, WorkerType


class InternalAuthService:
    def __init__(self, settings: Settings):
        self._settings = settings

    def authenticate_request(
        self,
        session: Session,
        headers: dict[str, str],
        body: dict,
    ) -> WorkerRequestContext:
        bearer_secret = self._extract_bearer(headers)
        worker_type = headers.get("x-worker-type")
        timestamp = headers.get("x-request-timestamp")
        signature = headers.get("x-context-signature")
        if not worker_type or not timestamp or not signature:
            raise HTTPException(status_code=401, detail="Missing worker authentication headers")

        credential = self._find_worker_credential(session, worker_type, headers, bearer_secret)
        self._validate_timestamp(timestamp)

        request_name = self._extract_request_name(body)
        raw_arguments = self._extract_payload(body)
        tenant_id = headers.get("x-tenant-id")
        worker_session_id = headers.get("x-worker-session-id")
        explicit_operational_context = self._extract_explicit_operational_context(headers)
        expected = self._build_signature(
            secret=bearer_secret,
            request_name=request_name,
            payload=raw_arguments,
            tenant_id=tenant_id,
            timestamp=timestamp,
            operational_context=explicit_operational_context,
        )
        if not hmac.compare_digest(signature, expected):
            raise HTTPException(status_code=401, detail="Invalid worker signature")

        operational_context = explicit_operational_context
        if operational_context is None and worker_session_id:
            if credential.worker_type == WorkerType.admin:
                operational_context = load_admin_context(session, credential.key_id, worker_session_id)
            else:
                operational_context = load_context(credential.key_id, worker_session_id)

        profile = (
            ExecutionProfile.client_scoped
            if credential.worker_type == WorkerType.client
            else ExecutionProfile.admin_multi_asset
        )

        credential.last_used_at = datetime.now(timezone.utc)
        session.add(credential)
        session.commit()

        context = WorkerRequestContext(
            worker_key_id=credential.key_id,
            worker_type=credential.worker_type.value,
            execution_profile=profile,
            tenant_id=tenant_id or credential.tenant_id,
            worker_session_id=worker_session_id,
            tool_name=request_name,
            raw_arguments=raw_arguments,
            operational_context=operational_context,
        )
        print(f"[internal_auth] context={context.model_dump()}", flush=True)
        return context

    def _find_worker_credential(
        self,
        session: Session,
        worker_type: str,
        headers: dict[str, str],
        bearer_secret: str,
    ) -> WorkerCredential:
        key_id = headers.get("x-worker-key-id")
        if not key_id:
            raise HTTPException(status_code=401, detail="Missing X-Worker-Key-Id")

        credential = session.scalar(
            select(WorkerCredential).where(WorkerCredential.key_id == key_id)
        )
        if credential is None:
            raise HTTPException(status_code=401, detail="Unknown worker key")
        if credential.status != WorkerCredentialStatus.active:
            raise HTTPException(status_code=401, detail="Worker key is disabled")
        if credential.worker_type.value != worker_type:
            raise HTTPException(status_code=401, detail="Worker type mismatch")

        candidate_hash = self.hash_secret(bearer_secret, self._settings.worker_shared_secret_salt)
        if not hmac.compare_digest(candidate_hash, credential.secret_hash):
            raise HTTPException(status_code=401, detail="Invalid worker secret")
        return credential

    def _extract_bearer(self, headers: dict[str, str]) -> str:
        authorization = headers.get("authorization")
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="Missing bearer token")
        return authorization.split(" ", 1)[1]

    def _validate_timestamp(self, timestamp: str) -> None:
        try:
            request_time = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(status_code=401, detail="Invalid request timestamp") from exc
        now = datetime.now(timezone.utc)
        delta = abs((now - request_time.astimezone(timezone.utc)).total_seconds())
        if delta > self._settings.request_ttl_seconds:
            raise HTTPException(status_code=401, detail="Request timestamp expired")

    def _extract_request_name(self, body: dict) -> str:
        method = body.get("method")
        if not method:
            raise HTTPException(status_code=400, detail="Missing MCP method")
        if method == "tools/call":
            params = body.get("params", {})
            tool_name = params.get("name")
            if not tool_name:
                raise HTTPException(status_code=400, detail="Expected MCP tool name")
            return str(tool_name)
        return str(method)

    def _extract_payload(self, body: dict) -> dict:
        method = body.get("method")
        params = body.get("params", {})
        payload = params.get("arguments", {}) if method == "tools/call" else params
        if payload is None:
            return {}
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="MCP request payload must be an object")
        return payload

    def _extract_explicit_operational_context(self, headers: dict[str, str]) -> OperationalContext | None:
        raw = headers.get("x-resolved-context")
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=401, detail="Invalid resolved context header") from exc
        return OperationalContext.model_validate(payload)

    def _build_signature(
        self,
        *,
        secret: str,
        request_name: str,
        payload: dict,
        tenant_id: str | None,
        timestamp: str,
        operational_context: OperationalContext | None,
    ) -> str:
        message = canonical_worker_message(
            request_name=request_name,
            payload=payload,
            tenant_id=tenant_id,
            timestamp=timestamp,
            operational_context=operational_context.model_dump() if operational_context else None,
        )
        return hmac.new(secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    @staticmethod
    def hash_secret(secret: str, salt: str) -> str:
        return hashlib.sha256(f"{salt}:{secret}".encode("utf-8")).hexdigest()


def canonical_worker_message(
    *,
    request_name: str,
    payload: dict,
    tenant_id: str | None,
    timestamp: str,
    operational_context: dict | None,
) -> str:
    return json.dumps(
        {
            "request_name": request_name,
            "payload": payload,
            "tenant_id": tenant_id,
            "timestamp": timestamp,
            "operational_context": operational_context,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
