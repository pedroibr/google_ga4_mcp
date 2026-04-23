from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker
from starlette.responses import JSONResponse, Response

from app.config import Settings
from app.core.asset_resolver import AssetResolver
from app.core.ga4_client import GA4Client
from app.core.context import OperationalContext
from app.db.models import AssetDirectory, ClientSessionContext, Source, SourceStatus, Tenant
from app.services.platform_service import PlatformService
from app.tools import ga4_tools
from app.tools.services import ToolServices
from app.core.audit import AuditService
from app.core.policy import PolicyService


PROTOCOL_VERSION = "2024-11-05"


def create_direct_mcp_router(settings: Settings, session_factory: sessionmaker[Session]) -> APIRouter:
    router = APIRouter(prefix="/mcp/ga4")
    platform = PlatformService(settings)
    resolver = AssetResolver()

    @router.post("/clients/{client_slug}")
    async def client_mcp(
        request: Request,
        client_slug: str,
        authorization: str | None = Header(default=None),
    ) -> Response:
        token = extract_bearer(authorization)
        if not token:
            return JSONResponse({"detail": "Missing bearer token"}, status_code=401)
        with session_factory() as session:
            try:
                client = platform.authenticate_bearer(session, client_slug, token)
                body = await request.json()
                payload = await handle_mcp_body(
                    request,
                    body,
                    session,
                    settings,
                    session_factory,
                    platform,
                    resolver,
                    client,
                    auth_mode="bearer",
                )
                return mcp_response(request, payload)
            except PermissionError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=401)
            except Exception as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)

    @router.post("/public/{public_token}")
    async def public_mcp(request: Request, public_token: str) -> Response:
        with session_factory() as session:
            try:
                client = platform.authenticate_public(session, public_token)
                body = await request.json()
                payload = await handle_mcp_body(
                    request,
                    body,
                    session,
                    settings,
                    session_factory,
                    platform,
                    resolver,
                    client,
                    auth_mode="public",
                )
                return mcp_response(request, payload)
            except PermissionError as exc:
                return JSONResponse({"detail": str(exc)}, status_code=401)
            except Exception as exc:
                return JSONResponse({"detail": str(exc)}, status_code=400)

    @router.get("/clients/{client_slug}")
    async def client_get() -> Response:
        return Response("Method Not Allowed", status_code=405, headers={"Allow": "POST"})

    @router.get("/public/{public_token}")
    async def public_get() -> Response:
        return Response("Method Not Allowed", status_code=405, headers={"Allow": "POST"})

    return router


async def handle_mcp_body(
    request: Request,
    body: dict[str, Any],
    session: Session,
    settings: Settings,
    session_factory: sessionmaker[Session],
    platform: PlatformService,
    resolver: AssetResolver,
    client: Tenant,
    auth_mode: str,
) -> dict[str, Any]:
    request_id = body.get("id")
    method = body.get("method")
    if method == "initialize":
        return result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "ga4-mcp", "version": "0.2.0"},
                "instructions": "Use the GA4 tools exposed for this client.",
            },
        )
    if method == "tools/list":
        properties = platform.list_client_properties(session, client.id)
        return result(request_id, {"tools": visible_tools(len(properties) > 1)})
    if method == "tools/call":
        params = body.get("params") or {}
        if not isinstance(params, dict):
            return error(request_id, -32602, "params must be an object")
        tool_name = str(params.get("name") or "")
        arguments = params.get("arguments") or {}
        if not isinstance(arguments, dict):
            return error(request_id, -32602, "arguments must be an object")
        session_key_value = extract_session_key(request, body, arguments, auth_mode, client.slug)
        try:
            value = await execute_tool(
                request,
                session,
                settings,
                session_factory,
                platform,
                resolver,
                client,
                tool_name,
                arguments,
                session_key_value,
            )
            return result(request_id, text_tool_result(value))
        except Exception as exc:
            return error(request_id, -32000, str(exc))
    return error(request_id, -32601, f"Method not found: {method}")


async def execute_tool(
    request: Request,
    session: Session,
    settings: Settings,
    session_factory: sessionmaker[Session],
    platform: PlatformService,
    resolver: AssetResolver,
    client: Tenant,
    tool_name: str,
    args: dict[str, Any],
    session_key_value: str,
) -> dict[str, Any]:
    properties = platform.list_client_properties(session, client.id)
    multi_property = len(properties) > 1

    if tool_name == "get_active_context":
        context = resolve_active_context(session, platform, client, session_key_value)
        return context.model_dump()

    if tool_name in {"list_my_properties", "select_my_property", "clear_active_context"} and not multi_property:
        raise PermissionError("Context switching tools are available only when this client has more than one GA4 asset")

    if tool_name == "list_my_properties":
        return {
            "client_slug": client.slug,
            "properties": [
                {
                    "property_id": item.property_id,
                    "display_name": item.display_name,
                    "account_id": item.account_id,
                    "source_id": item.source_id,
                    "measurement_ids": list(item.measurement_ids or []),
                    "default_uri": item.default_uri,
                    "is_default": item.property_id == client.default_property_id,
                }
                for item in properties
            ],
        }

    if tool_name == "select_my_property":
        query = str(args.get("query") or "").strip()
        if not query:
            raise ValueError("query is required")
        resolved = resolver.select_context_from_query(session, query=query, tenant_id=client.id)
        if resolved.get("resolved") and resolved.get("context"):
            context = OperationalContext.model_validate(resolved["context"])
            context.source_id = source_id_for_property(session, client.id, context.active_property_id)
            save_client_context(session, client.id, session_key_value, context)
            resolved["context"] = context.model_dump()
        return resolved

    if tool_name == "clear_active_context":
        clear_client_context(session, client.id, session_key_value)
        return {"cleared": True}

    context = resolve_active_context(session, platform, client, session_key_value)
    services = build_services_for_context(settings, session_factory, session, context)

    if tool_name == "get_property_details":
        return await ga4_tools._get_property_details(services, context.active_property_id or "")
    if tool_name == "get_reporting_metadata":
        return await ga4_tools._get_reporting_metadata(services, context.active_property_id or "")
    if tool_name == "run_report":
        return await ga4_tools._run_report(
            services,
            context.active_property_id or "",
            start_date=str(args.get("start_date") or "28daysAgo"),
            end_date=str(args.get("end_date") or "today"),
            metrics=list(args.get("metrics") or ["sessions"]),
            dimensions=list(args.get("dimensions") or []),
            row_limit=int(args.get("row_limit") or 100),
            offset=int(args.get("offset") or 0),
            filters=list(args.get("filters") or []),
            order_bys=list(args.get("order_bys") or []),
            keep_empty_rows=bool(args.get("keep_empty_rows") or False),
        )
    if tool_name == "run_realtime_report":
        minutes_ago = args.get("minutes_ago")
        return await ga4_tools._run_realtime_report(
            services,
            context.active_property_id or "",
            metrics=list(args.get("metrics") or ["activeUsers"]),
            dimensions=list(args.get("dimensions") or []),
            row_limit=int(args.get("row_limit") or 100),
            minutes_ago=int(minutes_ago) if minutes_ago is not None else None,
        )
    if tool_name == "get_traffic_overview":
        return await ga4_tools._get_traffic_overview(services, context.active_property_id or "", days=int(args.get("days") or 28))
    if tool_name == "get_page_performance":
        page_path = args.get("page_path")
        return await ga4_tools._get_page_performance(
            services,
            context.active_property_id or "",
            page_path=str(page_path) if page_path else None,
            days=int(args.get("days") or 28),
            row_limit=int(args.get("row_limit") or 25),
        )
    if tool_name == "compare_date_ranges":
        return await ga4_tools._compare_date_ranges(
            services,
            context.active_property_id or "",
            period1_start=str(args["period1_start"]),
            period1_end=str(args["period1_end"]),
            period2_start=str(args["period2_start"]),
            period2_end=str(args["period2_end"]),
            metrics=list(args.get("metrics") or ["sessions"]),
            dimensions=list(args.get("dimensions") or []),
            row_limit=int(args.get("row_limit") or 100),
        )
    raise ValueError(f"Unknown tool: {tool_name}")


def build_services_for_context(
    settings: Settings,
    session_factory: sessionmaker[Session],
    session: Session,
    context: OperationalContext,
) -> ToolServices:
    if context.source_id is None:
        raise PermissionError("Active property has no source configured")
    source = session.get(Source, context.source_id)
    if source is None:
        raise PermissionError("Active source no longer exists")
    if source.status != SourceStatus.active:
        raise PermissionError("Active source is disabled")
    platform = PlatformService(settings)
    return ToolServices(
        session_factory=session_factory,
        policy_service=PolicyService(),
        asset_resolver=AssetResolver(),
        ga4_client=GA4Client(settings, platform.source_credentials(source)),
        audit_service=AuditService(),
    )


def resolve_active_context(
    session: Session,
    platform: PlatformService,
    client: Tenant,
    session_key_value: str,
) -> OperationalContext:
    properties = platform.list_client_properties(session, client.id)
    if not properties:
        raise PermissionError("No GA4 assets are linked to this client")
    allowed_ids = {item.property_id for item in properties}
    stored = load_client_context(session, client.id, session_key_value) if len(properties) > 1 else None
    active_property_id = stored.active_property_id if stored and stored.active_property_id in allowed_ids else None
    if not active_property_id:
        active_property_id = client.default_property_id if client.default_property_id in allowed_ids else properties[0].property_id
    return OperationalContext(
        tenant_id=client.id,
        active_property_id=active_property_id,
        source_id=source_id_for_property(session, client.id, active_property_id),
        resolved_from_property_id=active_property_id,
    )


def source_id_for_property(session: Session, tenant_id: str, property_id: str | None) -> int | None:
    if not property_id:
        return None
    asset = session.scalar(
        select(AssetDirectory).where(
            AssetDirectory.tenant_id == tenant_id,
            AssetDirectory.property_id == property_id,
        )
    )
    return asset.source_id if asset is not None else None


def load_client_context(session: Session, tenant_id: str, session_key_value: str) -> OperationalContext | None:
    row = session.scalar(
        select(ClientSessionContext).where(
            ClientSessionContext.tenant_id == tenant_id,
            ClientSessionContext.session_key == session_key_value,
        )
    )
    if row is None:
        return None
    return OperationalContext.model_validate(row.context_json)


def save_client_context(session: Session, tenant_id: str, session_key_value: str, context: OperationalContext) -> None:
    row = session.scalar(
        select(ClientSessionContext).where(
            ClientSessionContext.tenant_id == tenant_id,
            ClientSessionContext.session_key == session_key_value,
        )
    )
    if row is None:
        row = ClientSessionContext(tenant_id=tenant_id, session_key=session_key_value, context_json=context.model_dump())
        session.add(row)
    else:
        row.context_json = context.model_dump()
    session.commit()


def clear_client_context(session: Session, tenant_id: str, session_key_value: str) -> None:
    row = session.scalar(
        select(ClientSessionContext).where(
            ClientSessionContext.tenant_id == tenant_id,
            ClientSessionContext.session_key == session_key_value,
        )
    )
    if row is not None:
        session.delete(row)
        session.commit()


def visible_tools(include_context_switching: bool) -> list[dict[str, Any]]:
    tools = [
        tool("get_active_context", "Return the active GA4 property context for this MCP session.", {}),
        tool("get_property_details", "Return GA4 property details and stream metadata for the active property.", {}),
        tool("get_reporting_metadata", "Return GA4 reporting metadata for the active property.", {}),
        tool(
            "run_report",
            "Run a GA4 report for the active property.",
            {
                "start_date": {"type": "string"},
                "end_date": {"type": "string"},
                "metrics": {"type": "array", "items": {"type": "string"}},
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "row_limit": {"type": "number"},
                "offset": {"type": "number"},
                "filters": {"type": "array", "items": {"type": "object"}},
                "order_bys": {"type": "array", "items": {"type": "object"}},
                "keep_empty_rows": {"type": "boolean"},
            },
        ),
        tool(
            "run_realtime_report",
            "Run a GA4 realtime report for the active property.",
            {
                "metrics": {"type": "array", "items": {"type": "string"}},
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "row_limit": {"type": "number"},
                "minutes_ago": {"type": "number"},
            },
        ),
        tool("get_traffic_overview", "Return a high-level GA4 traffic overview.", {"days": {"type": "number"}}),
        tool(
            "get_page_performance",
            "Return GA4 page performance for the active property.",
            {"page_path": {"type": "string"}, "days": {"type": "number"}, "row_limit": {"type": "number"}},
        ),
        tool(
            "compare_date_ranges",
            "Compare two GA4 date ranges in a single Data API call.",
            {
                "period1_start": {"type": "string"},
                "period1_end": {"type": "string"},
                "period2_start": {"type": "string"},
                "period2_end": {"type": "string"},
                "metrics": {"type": "array", "items": {"type": "string"}},
                "dimensions": {"type": "array", "items": {"type": "string"}},
                "row_limit": {"type": "number"},
            },
            required=["period1_start", "period1_end", "period2_start", "period2_end"],
        ),
    ]
    if include_context_switching:
        return [
            tool("list_my_properties", "List the GA4 properties linked to this client.", {}),
            tool(
                "select_my_property",
                "Resolve and activate one of this client's GA4 properties from a short query.",
                {"query": {"type": "string"}, "session_id": {"type": "string"}},
                required=["query"],
            ),
            tool("clear_active_context", "Reset active property context back to this client's default.", {}),
            *tools,
        ]
    return tools


def tool(name: str, description: str, properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {
        "name": name,
        "description": description,
        "inputSchema": {
            "type": "object",
            "properties": properties,
            "required": required or [],
            "additionalProperties": False,
        },
        "annotations": {
            "readOnlyHint": name not in {"select_my_property", "clear_active_context"},
            "destructiveHint": False,
            "idempotentHint": name in {"get_active_context", "list_my_properties", "clear_active_context"},
            "openWorldHint": False,
        },
    }


def text_tool_result(value: Any) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": json.dumps(value, default=str)}], "isError": False}


def result(request_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": value}


def error(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def mcp_response(request: Request, payload: dict[str, Any]) -> Response:
    accept = request.headers.get("accept", "")
    if "text/event-stream" in accept:
        return Response(
            f"event: message\ndata: {json.dumps(payload, default=str)}\n\n",
            media_type="text/event-stream",
        )
    return JSONResponse(payload)


def extract_bearer(authorization: str | None) -> str | None:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return authorization.split(" ", 1)[1].strip() or None


def extract_session_key(
    request: Request,
    body: dict[str, Any],
    args: dict[str, Any],
    auth_mode: str,
    client_slug: str,
) -> str:
    params = body.get("params") if isinstance(body.get("params"), dict) else {}
    assert isinstance(params, dict)
    meta = params.get("_meta") if isinstance(params.get("_meta"), dict) else {}
    assert isinstance(meta, dict)
    arg_meta = args.get("_meta") if isinstance(args.get("_meta"), dict) else {}
    assert isinstance(arg_meta, dict)

    from_header = (
        request.headers.get("mcp-session-id")
        or request.headers.get("x-session-id")
        or request.headers.get("x-openai-session")
        or request.headers.get("x-openai-subject")
    )
    from_body = (
        _string(params.get("session_id"))
        or _string(params.get("sessionId"))
        or _string(meta.get("session_id"))
        or _string(meta.get("sessionId"))
        or _string(args.get("session_id"))
        or _string(args.get("sessionId"))
        or _string(arg_meta.get("session_id"))
        or _string(arg_meta.get("sessionId"))
    )
    return from_header or from_body or f"implicit:{auth_mode}:{client_slug}:ga4"


def _string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
