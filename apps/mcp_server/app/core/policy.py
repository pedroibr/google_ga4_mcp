from __future__ import annotations

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import ExecutionProfile, OperationalContext, WorkerRequestContext
from app.db.models import AssetDirectory, Tenant, TenantAssetPolicy


class TenantPolicySnapshot(BaseModel):
    tenant_id: str
    default_property_id: str | None
    allowed_property_ids: list[str]


class PolicyService:
    def get_policy(self, session: Session, tenant_id: str) -> TenantPolicySnapshot:
        tenant = session.get(Tenant, tenant_id)
        if tenant is None:
            raise ValueError(f"Unknown tenant: {tenant_id}")
        if tenant.status.value != "active":
            raise PermissionError(f"Tenant is not active: {tenant_id}")

        rows = session.scalars(
            select(TenantAssetPolicy).where(TenantAssetPolicy.tenant_id == tenant_id)
        ).all()
        return TenantPolicySnapshot(
            tenant_id=tenant_id,
            default_property_id=tenant.default_property_id,
            allowed_property_ids=[row.property_id for row in rows],
        )

    def resolve_context_for_request(self, session: Session, request_context: WorkerRequestContext) -> OperationalContext:
        if request_context.execution_profile == ExecutionProfile.client_scoped:
            if not request_context.tenant_id:
                raise PermissionError("Client worker requests require tenant_id")
            policy = self.get_policy(session, request_context.tenant_id)
            if request_context.operational_context is not None:
                if request_context.operational_context.tenant_id not in (None, request_context.tenant_id):
                    raise PermissionError("Client worker context tenant mismatch")
                request_context.operational_context.tenant_id = request_context.tenant_id
                self.assert_context_allowed(session, policy, request_context.operational_context)
                return request_context.operational_context
            context = OperationalContext(
                tenant_id=policy.tenant_id,
                active_property_id=policy.default_property_id,
                resolved_from_query=None,
                resolved_from_property_id=policy.default_property_id,
            )
            if context.active_property_id:
                self.assert_context_allowed(session, policy, context)
            return context

        if request_context.operational_context is None:
            raise PermissionError("Admin requests require an operational context")
        if not request_context.operational_context.tenant_id:
            raise PermissionError("Operational context is missing tenant_id")
        policy = self.get_policy(session, request_context.operational_context.tenant_id)
        self.assert_context_allowed(session, policy, request_context.operational_context)
        return request_context.operational_context

    def assert_context_allowed(
        self,
        session: Session,
        policy: TenantPolicySnapshot,
        operational_context: OperationalContext,
    ) -> None:
        if operational_context.active_property_id is None:
            raise PermissionError("Operational context is missing active_property_id")
        if operational_context.active_property_id not in policy.allowed_property_ids:
            raise PermissionError(f"Property {operational_context.active_property_id} is outside tenant policy")
        if operational_context.source_id is None:
            asset = session.scalar(
                select(AssetDirectory).where(
                    AssetDirectory.tenant_id == policy.tenant_id,
                    AssetDirectory.property_id == operational_context.active_property_id,
                )
            )
            if asset is not None:
                operational_context.source_id = asset.source_id
