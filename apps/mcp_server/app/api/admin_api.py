from __future__ import annotations

from collections.abc import Generator

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.services.tenant_admin_service import (
    delete_tenant_and_related,
    list_tenants_payload,
    show_tenant_payload,
    upsert_client_tenant,
)


class AllowedPropertyInput(BaseModel):
    property_id: str
    display_name: str | None = None
    measurement_ids: list[str] = Field(default_factory=list)
    account_id: str | None = None
    default_uri: str | None = None


class ClientTenantUpsertRequest(BaseModel):
    tenant_id: str
    tenant_slug: str
    tenant_name: str
    worker_key_id: str
    worker_secret: str
    allowed_properties: list[AllowedPropertyInput] = Field(default_factory=list)
    default_property_id: str | None = None


def create_admin_api_router(settings: Settings, session_factory: sessionmaker[Session]) -> APIRouter:
    router = APIRouter(prefix="/api/v1", tags=["admin-api"])

    def session_dependency() -> Generator[Session, None, None]:
        session = session_factory()
        try:
            yield session
        finally:
            session.close()

    def require_admin_api_secret(
        authorization: str | None = Header(default=None),
        x_admin_api_key: str | None = Header(default=None),
    ) -> None:
        expected_secret = settings.admin_api_shared_secret.strip()
        if not expected_secret:
            raise HTTPException(status_code=503, detail="Admin API is not configured")

        bearer_secret: str | None = None
        if authorization and authorization.lower().startswith("bearer "):
            bearer_secret = authorization.split(" ", 1)[1].strip()

        provided_secret = bearer_secret or (x_admin_api_key.strip() if x_admin_api_key else None)
        if provided_secret != expected_secret:
            raise HTTPException(status_code=401, detail="Invalid admin API secret")

    @router.post("/client-tenants/upsert", dependencies=[Depends(require_admin_api_secret)])
    def upsert_client_tenant_endpoint(
        payload: ClientTenantUpsertRequest,
        session: Session = Depends(session_dependency),
    ) -> dict[str, object]:
        try:
            return upsert_client_tenant(
                session,
                settings,
                tenant_id=payload.tenant_id,
                tenant_slug=payload.tenant_slug,
                tenant_name=payload.tenant_name,
                worker_key_id=payload.worker_key_id,
                worker_secret=payload.worker_secret,
                allowed_properties=[property_item.model_dump() for property_item in payload.allowed_properties],
                default_property_id=payload.default_property_id,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/tenants", dependencies=[Depends(require_admin_api_secret)])
    def list_tenants_endpoint(session: Session = Depends(session_dependency)) -> list[dict[str, object]]:
        return list_tenants_payload(session)

    @router.get("/tenants/{tenant_id}", dependencies=[Depends(require_admin_api_secret)])
    def show_tenant_endpoint(tenant_id: str, session: Session = Depends(session_dependency)) -> dict[str, object]:
        try:
            return show_tenant_payload(session, tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.delete(
        "/tenants/{tenant_id}",
        dependencies=[Depends(require_admin_api_secret)],
        status_code=status.HTTP_200_OK,
    )
    def delete_tenant_endpoint(tenant_id: str, session: Session = Depends(session_dependency)) -> dict[str, str]:
        try:
            return delete_tenant_and_related(session, tenant_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    return router
