from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from app.api.admin_api import create_admin_api_router
from app.api.internal_auth import InternalAuthService
from app.api.mcp_http import MCPAuthenticationMiddleware
from app.config import get_settings
from app.core.asset_resolver import AssetResolver
from app.core.audit import AuditService
from app.core.ga4_client import GA4Client
from app.core.policy import PolicyService
from app.db.session import create_session_factory
from app.tools.context_tools import register_context_tools
from app.tools.ga4_tools import register_ga4_tools
from app.tools.services import ToolServices


def _extend_transport_security_allowed_hosts(mcp: FastMCP) -> None:
    transport_security = mcp.settings.transport_security
    transport_security.enable_dns_rebinding_protection = False

    public_domain = os.getenv("RAILWAY_PUBLIC_DOMAIN")
    if not public_domain:
        return

    allowed_hosts = list(transport_security.allowed_hosts)
    allowed_origins = list(transport_security.allowed_origins)

    host_candidates = [public_domain, f"{public_domain}:*"]
    origin_candidates = [f"https://{public_domain}", f"https://{public_domain}:*"]

    for candidate in host_candidates:
        if candidate not in allowed_hosts:
            allowed_hosts.append(candidate)
    for candidate in origin_candidates:
        if candidate not in allowed_origins:
            allowed_origins.append(candidate)

    transport_security.allowed_hosts = allowed_hosts
    transport_security.allowed_origins = allowed_origins


def create_mcp_server() -> tuple[FastAPI, FastMCP]:
    settings = get_settings()
    session_factory = create_session_factory(settings)
    services = ToolServices(
        session_factory=session_factory,
        policy_service=PolicyService(),
        asset_resolver=AssetResolver(),
        ga4_client=GA4Client(settings),
        audit_service=AuditService(),
    )
    auth_service = InternalAuthService(settings)

    mcp = FastMCP(settings.app_name)
    register_context_tools(mcp, services)
    register_ga4_tools(mcp, services)
    _extend_transport_security_allowed_hosts(mcp)
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title=settings.app_name, lifespan=lifespan)
    app.add_middleware(
        MCPAuthenticationMiddleware,
        session_factory=session_factory,
        auth_service=auth_service,
    )

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "app": settings.app_name}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    @app.get("/")
    async def root() -> dict:
        return {"status": "ok", "app": settings.app_name, "service": "google-ga4-mcp"}

    app.include_router(create_admin_api_router(settings, session_factory))
    app.mount("/mcp", mcp_app)
    return app, mcp


app, mcp = create_mcp_server()
