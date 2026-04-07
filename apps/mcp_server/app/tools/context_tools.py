from __future__ import annotations

from typing import Annotated

from pydantic import Field
from sqlalchemy import select

from app.core.asset_resolver import (
    display_name_for_property,
    hostname_for_uri,
    normalize_query,
    property_type_for_property_id,
)
from app.core.context import ExecutionProfile, OperationalContext, get_request_context
from app.core.session_context_store import (
    clear_admin_context,
    clear_context as clear_stored_context,
    save_admin_context,
    save_context,
)
from app.db.models import AssetDirectory
from app.tools.error_handling import build_failure_summary
from app.tools.services import ToolServices


def register_context_tools(mcp, services: ToolServices) -> None:
    @mcp.tool(description="Client-only. List the GA4 properties already assigned to the current tenant.")
    def list_my_properties(
        limit: Annotated[int, Field(description="Maximum number of tenant-mapped properties to return.", ge=1, le=500)] = 50
    ) -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.client_scoped:
            raise PermissionError("list_my_properties is available only to client workers")
        session = services.session_factory()
        try:
            results = services.asset_resolver.list_properties_for_tenant(
                session,
                tenant_id=request_context.tenant_id or "",
                limit=limit,
            )
            return {
                "tenant_id": request_context.tenant_id,
                "properties": [result.model_dump() for result in results],
            }
        finally:
            session.close()

    @mcp.tool(
        description="Client-only. Resolve and activate one of the current tenant's allowed GA4 properties from a short query."
    )
    def select_my_property(
        query: Annotated[str, Field(description="Short property lookup string, such as property ID, measurement ID, hostname, or part of the display name.")],
        limit: Annotated[int, Field(description="Maximum number of candidates to consider during resolution.", ge=1, le=100)] = 10,
    ) -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.client_scoped:
            raise PermissionError("select_my_property is available only to client workers")
        session = services.session_factory()
        try:
            result = services.asset_resolver.select_context_from_query(
                session,
                query=query,
                tenant_id=request_context.tenant_id or "",
                limit=limit,
            )
            if result.get("resolved"):
                context = OperationalContext.model_validate(result["context"])
                _save_request_context(session, request_context, context)
                services.audit_service.record(
                    session,
                    request_context,
                    "select_my_property",
                    result,
                    resolved_context=context,
                )
            return result
        except Exception as exc:
            services.audit_service.record(
                session,
                request_context,
                "select_my_property",
                build_failure_summary(exc, step="select_my_property"),
                status="error",
            )
            raise
        finally:
            session.close()

    @mcp.tool(
        name="search_properties",
        description="Admin-only. Search published tenant GA4 properties already mapped inside this MCP."
    )
    def search_properties(
        query: Annotated[str, Field(description="Short lookup string for an existing client or mapped property.")],
        limit: Annotated[int, Field(description="Maximum number of candidates to return.", ge=1, le=100)] = 10,
    ) -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.admin_multi_asset:
            raise PermissionError("search_properties is available only to admin workers")
        session = services.session_factory()
        try:
            results = services.asset_resolver.search_properties(
                session,
                query=query,
                limit=limit,
                mapped_only=True,
            )
            return {"query": query, "candidates": [result.model_dump() for result in results]}
        finally:
            session.close()

    @mcp.tool(
        name="list_tenant_contexts",
        description="Admin-only. List the tenant contexts currently published in this MCP, with each tenant's default GA4 property."
    )
    def list_tenant_contexts(
        limit: Annotated[int, Field(description="Maximum number of tenant contexts to return.", ge=1, le=500)] = 100
    ) -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.admin_multi_asset:
            raise PermissionError("list_tenant_contexts is available only to admin workers")
        session = services.session_factory()
        try:
            rows = services.asset_resolver.list_accessible_contexts(session, limit=limit)
            result = {"contexts": rows, "meta": {"limit": max(1, min(limit, 500))}}
            services.audit_service.record(session, request_context, "list_tenant_contexts", result)
            return result
        except Exception as exc:
            services.audit_service.record(
                session,
                request_context,
                "list_tenant_contexts",
                build_failure_summary(exc, step="list_tenant_contexts"),
                status="error",
            )
            raise
        finally:
            session.close()

    @mcp.tool(
        description="Admin-only. Resolve and activate a tenant context from a tenant name or one of its mapped GA4 properties."
    )
    def select_client_context(
        query: Annotated[str, Field(description="Short tenant lookup string, such as a client name, slug, property ID, or measurement ID.")],
        limit: Annotated[int, Field(description="Maximum number of candidates to consider during tenant resolution.", ge=1, le=100)] = 10,
    ) -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.admin_multi_asset:
            raise PermissionError("select_client_context is available only to admin workers")
        session = services.session_factory()
        try:
            result = services.asset_resolver.resolve_context_from_client_query(session, query=query, limit=limit)
            if result.get("resolved") and result.get("context"):
                context = OperationalContext.model_validate(result["context"])
                _save_request_context(session, request_context, context)
                services.audit_service.record(
                    session,
                    request_context,
                    "select_client_context",
                    result,
                    resolved_context=context,
                )
            return result
        except Exception as exc:
            services.audit_service.record(
                session,
                request_context,
                "select_client_context",
                build_failure_summary(exc, step="select_client_context"),
                status="error",
            )
            raise
        finally:
            session.close()

    @mcp.tool(
        description="Admin-only. Explicitly activate a tenant GA4 property when you already know the property ID or alias."
    )
    def select_property_context(
        property_reference: Annotated[str, Field(description="Property ID, measurement ID, hostname, or display-name reference to activate.")]
    ) -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.admin_multi_asset:
            raise PermissionError("select_property_context is available only to admin workers")
        session = services.session_factory()
        try:
            context = services.asset_resolver.resolve_context_from_property_reference(
                session,
                property_reference=property_reference,
                source_query=property_reference,
            )
            payload = context.model_dump()
            services.audit_service.record(
                session,
                request_context,
                "select_property_context",
                payload,
                resolved_context=context,
            )
            _save_request_context(session, request_context, context)
            return payload
        except Exception as exc:
            services.audit_service.record(
                session,
                request_context,
                "select_property_context",
                build_failure_summary(exc, step="select_property_context"),
                status="error",
            )
            raise
        finally:
            session.close()

    @mcp.tool(
        name="sync_account_properties",
        description="Admin-only maintenance tool. Refresh the raw GA4 property inventory visible to the connected Google account."
    )
    async def sync_account_properties() -> dict:
        request_context = get_request_context(mcp)
        if request_context.execution_profile != ExecutionProfile.admin_multi_asset:
            raise PermissionError("sync_account_properties is available only to admin workers")
        session = services.session_factory()
        try:
            response = await services.ga4_client.list_account_summaries()
            synced = 0
            for account_summary in response.get("accountSummaries", []):
                account = account_summary.get("account", "")
                account_id = str(account).split("/")[-1] or None
                for property_summary in account_summary.get("propertySummaries", []):
                    property_resource = str(property_summary.get("property", "")).strip()
                    property_id = property_resource.split("/")[-1]
                    if not property_id:
                        continue
                    display_name = display_name_for_property(
                        property_id,
                        str(property_summary.get("displayName") or "").strip() or None,
                    )
                    data_streams = await services.ga4_client.list_data_streams(property_id)
                    measurement_ids: list[str] = []
                    default_uri: str | None = None
                    for stream in data_streams.get("dataStreams", []):
                        web_stream_data = stream.get("webStreamData") or {}
                        measurement_id = str(web_stream_data.get("measurementId") or "").strip().upper()
                        if measurement_id and measurement_id not in measurement_ids:
                            measurement_ids.append(measurement_id)
                        if default_uri is None:
                            default_uri = str(web_stream_data.get("defaultUri") or "").strip() or None
                    measurement_ids.sort()
                    payload = {
                        "property_id": property_id,
                        "display_name": display_name,
                        "account_id": account_id,
                        "measurement_ids": measurement_ids,
                        "default_uri": default_uri,
                        "hostname": hostname_for_uri(default_uri),
                        "property_summary": property_summary,
                    }
                    existing = session.scalar(select(AssetDirectory).where(AssetDirectory.property_id == property_id))
                    if existing is None:
                        session.add(
                            AssetDirectory(
                                property_id=property_id,
                                property_type=property_type_for_property_id(property_id),
                                display_name=display_name,
                                normalized_name=normalize_query(display_name),
                                account_id=account_id,
                                measurement_ids=measurement_ids,
                                default_uri=default_uri,
                                tenant_id=None,
                                metadata_json=payload,
                            )
                        )
                    else:
                        existing.property_type = property_type_for_property_id(property_id)
                        existing.display_name = display_name
                        existing.normalized_name = normalize_query(display_name)
                        existing.account_id = account_id
                        existing.measurement_ids = measurement_ids
                        existing.default_uri = default_uri
                        existing.metadata_json = payload
                    synced += 1

            session.commit()
            result = {"status": "ok", "synced_properties": synced}
            services.audit_service.record(session, request_context, "sync_account_properties", result)
            return result
        except Exception as exc:
            services.audit_service.record(
                session,
                request_context,
                "sync_account_properties",
                build_failure_summary(exc, step="sync_account_properties"),
                status="error",
            )
            raise
        finally:
            session.close()

    @mcp.tool(description="Return the currently active operational context for this MCP session.")
    def get_active_context() -> dict:
        request_context = get_request_context(mcp)
        session = services.session_factory()
        try:
            context = services.policy_service.resolve_context_for_request(session, request_context)
            return context.model_dump()
        finally:
            session.close()

    @mcp.tool(description="Clear the active operational context for this MCP session.")
    def clear_active_context() -> dict:
        request_context = get_request_context(mcp)
        session = services.session_factory()
        try:
            _clear_request_context(session, request_context)
        finally:
            session.close()
        return {"cleared": True}


def _save_request_context(session, request_context, context: OperationalContext) -> None:
    if request_context.worker_session_id is None:
        return
    if request_context.worker_type == "admin":
        save_admin_context(session, request_context.worker_key_id, request_context.worker_session_id, context)
    else:
        save_context(request_context.worker_key_id, request_context.worker_session_id, context)


def _clear_request_context(session, request_context) -> None:
    if request_context.worker_session_id is None:
        return
    if request_context.worker_type == "admin":
        clear_admin_context(session, request_context.worker_key_id, request_context.worker_session_id)
    else:
        clear_stored_context(request_context.worker_key_id, request_context.worker_session_id)
