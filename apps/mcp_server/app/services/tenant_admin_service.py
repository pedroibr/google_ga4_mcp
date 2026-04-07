from __future__ import annotations

from collections.abc import Sequence
import json

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.internal_auth import InternalAuthService
from app.config import Settings
from app.core.asset_resolver import (
    display_name_for_property,
    hostname_for_uri,
    normalize_query,
    property_type_for_property_id,
)
from app.db.models import (
    AssetDirectory,
    AuditLog,
    Tenant,
    TenantAssetPolicy,
    TenantStatus,
    WorkerCredential,
    WorkerCredentialStatus,
    WorkerType,
)


def parse_json_list(value: str) -> list[dict[str, object]]:
    if not value.strip():
        return []
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("allowed_properties must be a JSON array")
    return [item for item in parsed if isinstance(item, dict)]


def normalize_measurement_ids(measurement_ids: Sequence[str]) -> list[str]:
    normalized = sorted({measurement_id.strip().upper() for measurement_id in measurement_ids if measurement_id.strip()})
    return normalized


def pick_default(explicit_default: str | None, property_ids: Sequence[str]) -> str | None:
    if explicit_default:
        return explicit_default
    if property_ids:
        return property_ids[0]
    return None


def list_tenants_payload(session: Session) -> list[dict[str, object]]:
    rows = session.scalars(select(Tenant).order_by(Tenant.slug)).all()
    return [
        {
            "id": tenant.id,
            "slug": tenant.slug,
            "display_name": tenant.display_name,
            "status": tenant.status.value,
            "default_property_id": tenant.default_property_id,
        }
        for tenant in rows
    ]


def show_tenant_payload(session: Session, tenant_id: str) -> dict[str, object]:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError(f"Unknown tenant: {tenant_id}")

    policies = session.scalars(select(TenantAssetPolicy).where(TenantAssetPolicy.tenant_id == tenant_id)).all()
    assets = session.scalars(select(AssetDirectory).where(AssetDirectory.tenant_id == tenant_id)).all()
    workers = session.scalars(select(WorkerCredential).where(WorkerCredential.tenant_id == tenant_id)).all()

    return {
        "tenant": {
            "id": tenant.id,
            "slug": tenant.slug,
            "display_name": tenant.display_name,
            "status": tenant.status.value,
            "default_property_id": tenant.default_property_id,
            "created_at": tenant.created_at,
            "updated_at": tenant.updated_at,
        },
        "property_policies": [
            {
                "property_id": row.property_id,
                "is_default": row.is_default,
                "label_snapshot": row.label_snapshot,
            }
            for row in policies
        ],
        "asset_directory": [
            {
                "property_id": row.property_id,
                "display_name": row.display_name,
                "property_type": row.property_type,
                "account_id": row.account_id,
                "measurement_ids": list(row.measurement_ids or []),
                "default_uri": row.default_uri,
            }
            for row in assets
        ],
        "worker_credentials": [
            {
                "key_id": row.key_id,
                "worker_type": row.worker_type.value,
                "status": row.status.value,
                "last_used_at": row.last_used_at,
            }
            for row in workers
        ],
    }


def delete_tenant_and_related(session: Session, tenant_id: str) -> dict[str, str]:
    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        raise ValueError(f"Unknown tenant: {tenant_id}")

    session.execute(delete(TenantAssetPolicy).where(TenantAssetPolicy.tenant_id == tenant_id))
    session.execute(delete(WorkerCredential).where(WorkerCredential.tenant_id == tenant_id))
    session.execute(delete(AssetDirectory).where(AssetDirectory.tenant_id == tenant_id))
    session.execute(delete(AuditLog).where(AuditLog.tenant_id == tenant_id))
    session.execute(delete(Tenant).where(Tenant.id == tenant_id))
    session.commit()
    return {"deleted_tenant_id": tenant_id}


def upsert_worker_credential(
    session: Session,
    settings: Settings,
    *,
    worker_key_id: str,
    worker_secret: str,
    worker_type: WorkerType,
    tenant_id: str | None,
) -> WorkerCredential:
    auth_service = InternalAuthService(settings)
    credential = session.scalar(select(WorkerCredential).where(WorkerCredential.key_id == worker_key_id))
    if credential is None:
        credential = WorkerCredential(
            key_id=worker_key_id,
            worker_type=worker_type,
            tenant_id=tenant_id,
            secret_hash="",
            status=WorkerCredentialStatus.active,
        )
        session.add(credential)

    credential.worker_type = worker_type
    credential.tenant_id = tenant_id
    credential.secret_hash = auth_service.hash_secret(worker_secret, settings.worker_shared_secret_salt)
    credential.status = WorkerCredentialStatus.active
    return credential


def _replace_property_policies(
    session: Session,
    tenant_id: str,
    *,
    allowed_properties: Sequence[dict[str, object]],
    default_property_id: str | None,
) -> None:
    session.execute(delete(TenantAssetPolicy).where(TenantAssetPolicy.tenant_id == tenant_id))
    policies: list[TenantAssetPolicy] = []

    for allowed_property in allowed_properties:
        property_id = str(allowed_property["property_id"]).strip()
        display_name = display_name_for_property(property_id, str(allowed_property.get("display_name") or "").strip() or None)
        measurement_ids = normalize_measurement_ids(
            [str(measurement_id) for measurement_id in (allowed_property.get("measurement_ids") or [])]
        )
        default_uri = str(allowed_property.get("default_uri") or "").strip() or None
        account_id = str(allowed_property.get("account_id") or "").strip() or None
        metadata_json = {
            "property_id": property_id,
            "display_name": display_name,
            "measurement_ids": measurement_ids,
            "account_id": account_id,
            "default_uri": default_uri,
            "hostname": hostname_for_uri(default_uri),
        }

        policies.append(
            TenantAssetPolicy(
                tenant_id=tenant_id,
                property_id=property_id,
                is_default=property_id == default_property_id,
                label_snapshot=display_name,
            )
        )

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
                    tenant_id=tenant_id,
                    metadata_json=metadata_json,
                )
            )
        else:
            existing.property_type = property_type_for_property_id(property_id)
            existing.display_name = display_name
            existing.normalized_name = normalize_query(display_name)
            existing.account_id = account_id
            existing.measurement_ids = measurement_ids
            existing.default_uri = default_uri
            existing.tenant_id = tenant_id
            existing.metadata_json = {**existing.metadata_json, **metadata_json}

    session.add_all(policies)


def upsert_client_tenant(
    session: Session,
    settings: Settings,
    *,
    tenant_id: str,
    tenant_slug: str,
    tenant_name: str,
    worker_key_id: str,
    worker_secret: str,
    allowed_properties: Sequence[dict[str, object]],
    default_property_id: str | None,
) -> dict[str, object]:
    normalized_allowed_properties: list[dict[str, object]] = []
    seen_property_ids: set[str] = set()

    for property_item in allowed_properties:
        property_id = str(property_item.get("property_id") or "").strip()
        if not property_id:
            raise ValueError("Each allowed property must include property_id")
        if property_id in seen_property_ids:
            raise ValueError("allowed_properties must not contain duplicate property_id values")
        seen_property_ids.add(property_id)
        normalized_allowed_properties.append(
            {
                "property_id": property_id,
                "display_name": str(property_item.get("display_name") or "").strip() or None,
                "measurement_ids": normalize_measurement_ids(
                    [str(measurement_id) for measurement_id in (property_item.get("measurement_ids") or [])]
                ),
                "account_id": str(property_item.get("account_id") or "").strip() or None,
                "default_uri": str(property_item.get("default_uri") or "").strip() or None,
            }
        )

    if not normalized_allowed_properties:
        raise ValueError("allowed_properties must contain at least one property")

    resolved_default = pick_default(default_property_id, [item["property_id"] for item in normalized_allowed_properties])
    if resolved_default not in {item["property_id"] for item in normalized_allowed_properties}:
        raise ValueError("default_property_id must be included in allowed_properties")

    tenant = session.get(Tenant, tenant_id)
    if tenant is None:
        tenant = Tenant(id=tenant_id, slug=tenant_slug, display_name=tenant_name, status=TenantStatus.active)
        session.add(tenant)

    tenant.slug = tenant_slug
    tenant.display_name = tenant_name
    tenant.default_property_id = resolved_default

    _replace_property_policies(
        session,
        tenant_id,
        allowed_properties=normalized_allowed_properties,
        default_property_id=resolved_default,
    )

    credential = upsert_worker_credential(
        session,
        settings,
        worker_key_id=worker_key_id,
        worker_secret=worker_secret,
        worker_type=WorkerType.client,
        tenant_id=tenant_id,
    )
    session.commit()

    return {
        "tenant_id": tenant_id,
        "worker_key_id": credential.key_id,
        "allowed_properties": normalized_allowed_properties,
        "default_property_id": resolved_default,
    }
