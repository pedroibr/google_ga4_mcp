from __future__ import annotations

import json

from fastapi import Request
from starlette.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.internal_auth import InternalAuthService
from app.core.context import OperationalContext
from app.core.context import reset_request_context, set_request_context
from app.core.session_context_store import (
    clear_admin_context,
    clear_context,
    save_admin_context,
    save_context,
)


class MCPAuthenticationMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, session_factory, auth_service: InternalAuthService):
        super().__init__(app)
        self._session_factory = session_factory
        self._auth_service = auth_service

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/mcp"):
            return await call_next(request)

        body_bytes = await request.body()
        try:
            body = json.loads(body_bytes.decode("utf-8") or "{}")
        except json.JSONDecodeError:
            body = {}

        headers = {key.lower(): value for key, value in request.headers.items()}
        session = self._session_factory()
        token = None
        try:
            context = self._auth_service.authenticate_request(session, headers, body)
            token = set_request_context(context)
            request.state.worker_request_context = context

            async def receive():
                return {"type": "http.request", "body": body_bytes, "more_body": False}

            request = Request(request.scope, receive)
            request.state.worker_request_context = context
            response = await call_next(request)
            return await self._finalize_response(response, context)
        finally:
            if token is not None:
                reset_request_context(token)
            session.close()

    async def _finalize_response(self, response: Response, context) -> Response:
        if context.worker_session_id is None:
            return response

        body_chunks = [chunk async for chunk in response.body_iterator]
        body = b"".join(body_chunks)
        session = self._session_factory()
        try:
            self._persist_context_from_response(session, context, body.decode("utf-8", errors="ignore"))
        finally:
            session.close()

        return Response(
            content=body,
            status_code=response.status_code,
            headers=dict(response.headers),
            media_type=response.media_type,
        )

    def _persist_context_from_response(self, session: Session, context, response_text: str) -> None:
        tool_name = context.tool_name
        if tool_name not in {
            "select_client_context",
            "select_property_context",
            "select_my_property",
            "clear_active_context",
        }:
            return

        if tool_name == "clear_active_context":
            if context.worker_type == "admin":
                clear_admin_context(session, context.worker_key_id, context.worker_session_id)
            else:
                clear_context(context.worker_key_id, context.worker_session_id)
            return

        payload = _parse_sse_payload(response_text)
        text = payload.get("result", {}).get("content", [{}])[0].get("text") if payload else None
        if not text:
            return

        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return

        if tool_name == "select_property_context":
            if context.worker_type == "admin":
                save_admin_context(
                    session,
                    context.worker_key_id,
                    context.worker_session_id,
                    OperationalContext.model_validate(parsed),
                )
            else:
                save_context(
                    context.worker_key_id,
                    context.worker_session_id,
                    OperationalContext.model_validate(parsed),
                )
            return

        if parsed.get("resolved") and parsed.get("context"):
            if context.worker_type == "admin":
                save_admin_context(
                    session,
                    context.worker_key_id,
                    context.worker_session_id,
                    OperationalContext.model_validate(parsed["context"]),
                )
            else:
                save_context(
                    context.worker_key_id,
                    context.worker_session_id,
                    OperationalContext.model_validate(parsed["context"]),
                )


def _parse_sse_payload(response_text: str) -> dict | None:
    for line in response_text.splitlines():
        if line.startswith("data: "):
            try:
                return json.loads(line[6:])
            except json.JSONDecodeError:
                return None
    return None
