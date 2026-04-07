from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from sqlalchemy import JSON, DateTime, Enum as SqlEnum, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TenantStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class WorkerType(str, Enum):
    client = "client"
    admin = "admin"


class WorkerCredentialStatus(str, Enum):
    active = "active"
    disabled = "disabled"


class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(255))
    status: Mapped[TenantStatus] = mapped_column(SqlEnum(TenantStatus), default=TenantStatus.active)
    default_property_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class TenantAssetPolicy(Base):
    __tablename__ = "tenant_asset_policies"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"), index=True)
    property_id: Mapped[str] = mapped_column(String(128), index=True)
    is_default: Mapped[bool] = mapped_column(default=False)
    label_snapshot: Mapped[str | None] = mapped_column(String(255), nullable=True)


class WorkerCredential(Base):
    __tablename__ = "worker_credentials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_type: Mapped[WorkerType] = mapped_column(SqlEnum(WorkerType), index=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True)
    key_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    secret_hash: Mapped[str] = mapped_column(String(128))
    status: Mapped[WorkerCredentialStatus] = mapped_column(
        SqlEnum(WorkerCredentialStatus),
        default=WorkerCredentialStatus.active,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AssetDirectory(Base):
    __tablename__ = "asset_directory"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    property_id: Mapped[str] = mapped_column(String(128), unique=True, index=True)
    property_type: Mapped[str] = mapped_column(String(64), index=True)
    display_name: Mapped[str] = mapped_column(String(255), index=True)
    normalized_name: Mapped[str] = mapped_column(String(255), index=True)
    account_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    measurement_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_uri: Mapped[str | None] = mapped_column(String(512), nullable=True)
    tenant_id: Mapped[str | None] = mapped_column(ForeignKey("tenants.id"), nullable=True, index=True)
    metadata_json: Mapped[dict] = mapped_column(JSON, default=dict)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    execution_profile: Mapped[str] = mapped_column(String(64), index=True)
    worker_key_id: Mapped[str] = mapped_column(String(128), index=True)
    tenant_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    resolved_context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    tool_name: Mapped[str] = mapped_column(String(128), index=True)
    request_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerSessionContext(Base):
    __tablename__ = "worker_session_contexts"
    __table_args__ = (
        UniqueConstraint("worker_key_id", "worker_session_id", name="uq_worker_session_context"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    worker_key_id: Mapped[str] = mapped_column(String(128), index=True)
    worker_session_id: Mapped[str] = mapped_column(String(255), index=True)
    context_json: Mapped[dict] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)
