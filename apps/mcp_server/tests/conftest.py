from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.api.internal_auth import InternalAuthService
from app.config import Settings
from app.db.models import (
    AssetDirectory,
    Base,
    Tenant,
    TenantAssetPolicy,
    TenantStatus,
    WorkerCredential,
    WorkerCredentialStatus,
    WorkerType,
)


@pytest.fixture()
def settings() -> Settings:
    return Settings(
        DATABASE_URL="sqlite+pysqlite:///:memory:",
        WORKER_SHARED_SECRET_SALT="test-salt",
        GOOGLE_OAUTH_CLIENT_ID="client-id",
        GOOGLE_OAUTH_CLIENT_SECRET="client-secret",
        GOOGLE_OAUTH_REFRESH_TOKEN="refresh-token",
        ADMIN_API_SHARED_SECRET="admin-secret",
    )


@pytest.fixture()
def session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(settings.database_url, future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


@pytest.fixture()
def session(session_factory: sessionmaker[Session]) -> Session:
    db = session_factory()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def seeded_db(session: Session, settings: Settings) -> Session:
    tenant = Tenant(
        id="tenant_luis",
        slug="luis",
        display_name="Luis Analytics",
        status=TenantStatus.active,
        default_property_id="123456789",
    )
    session.add(tenant)
    session.add_all(
        [
            TenantAssetPolicy(
                tenant_id=tenant.id,
                property_id="123456789",
                is_default=True,
                label_snapshot="Luis Main",
            ),
            TenantAssetPolicy(
                tenant_id=tenant.id,
                property_id="987654321",
                is_default=False,
                label_snapshot="Luis Blog",
            ),
        ]
    )
    session.add_all(
        [
            AssetDirectory(
                property_id="123456789",
                property_type="ga4_property",
                display_name="Luis Main",
                normalized_name="luis main",
                account_id="111111",
                measurement_ids=["G-AAAA1111"],
                default_uri="https://www.luis.com",
                tenant_id=tenant.id,
                metadata_json={"property_id": "123456789"},
            ),
            AssetDirectory(
                property_id="987654321",
                property_type="ga4_property",
                display_name="Luis Blog",
                normalized_name="luis blog",
                account_id="111111",
                measurement_ids=["G-BBBB2222"],
                default_uri="https://blog.luis.com",
                tenant_id=tenant.id,
                metadata_json={"property_id": "987654321"},
            ),
            AssetDirectory(
                property_id="555555555",
                property_type="ga4_property",
                display_name="Brand Property",
                normalized_name="brand property",
                account_id="222222",
                measurement_ids=["G-CCCC3333"],
                default_uri="https://brand.example.com",
                tenant_id="tenant_brand",
                metadata_json={"property_id": "555555555"},
            ),
        ]
    )
    auth_service = InternalAuthService(settings)
    session.add(
        WorkerCredential(
            worker_type=WorkerType.client,
            tenant_id=tenant.id,
            key_id="client-key-1",
            secret_hash=auth_service.hash_secret("client-secret", settings.worker_shared_secret_salt),
            status=WorkerCredentialStatus.active,
        )
    )
    session.add(
        WorkerCredential(
            worker_type=WorkerType.admin,
            tenant_id=None,
            key_id="admin-key-1",
            secret_hash=auth_service.hash_secret("admin-secret", settings.worker_shared_secret_salt),
            status=WorkerCredentialStatus.active,
        )
    )
    session.commit()
    return session
