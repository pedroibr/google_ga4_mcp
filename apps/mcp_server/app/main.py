from __future__ import annotations

import os

from fastapi import FastAPI
from mcp.server.fastmcp import FastMCP

from app.api.admin_api import create_admin_api_router
from app.api.admin_ui import create_admin_ui_router
from app.api.direct_mcp import create_direct_mcp_router
from app.config import get_settings
from app.db.session import create_session_factory


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

    mcp = FastMCP(settings.app_name)
    _extend_transport_security_allowed_hosts(mcp)

    app = FastAPI(title=settings.app_name)

    @app.get("/healthz")
    async def healthz() -> dict:
        return {"status": "ok", "app": settings.app_name}

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "app": settings.app_name}

    app.include_router(create_admin_api_router(settings, session_factory))
    app.include_router(create_direct_mcp_router(settings, session_factory))
    app.include_router(create_admin_ui_router(settings, session_factory))
    return app, mcp


app, mcp = create_mcp_server()
