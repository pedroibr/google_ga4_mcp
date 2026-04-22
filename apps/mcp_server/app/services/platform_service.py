from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import urlparse

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.config import Settings
from app.core.asset_resolver import display_name_for_property, hostname_for_uri, normalize_query, property_type_for_property_id
from app.core.ga4_client import GA4Client, GA4Credentials
from app.core.secrets import decrypt_secret, encrypt_secret, hash_token, issue_token, verify_token
from app.db.models import (
    AssetDirectory,
    ClientSessionContext,
    Source,
    SourceStatus,
    Tenant,
    TenantAssetPolicy,
    TenantStatus,
)


def normalize_slug(value: str) -> str:
    normalized = normalize_query(value).replace(" ", "-")
    if not normalized:
        raise ValueError("Slug is required")
    return normalized[:128]


def normalize_measurement_ids(values: list[str]) -> list[str]:
    return sorted({value.strip().upper() for value in values if value.strip()})


class PlatformService:
    def __init__(self, settings: Settings):
        self.settings = settings

    def list_clients(self, session: Session) -> list[Tenant]:
        return list(session.scalars(select(Tenant).order_by(Tenant.slug)).all())

    def get_client(self, session: Session, client_slug: str) -> Tenant:
        client = session.scalar(select(Tenant).where(Tenant.slug == client_slug))
        if client is None:
            raise ValueError("Unknown client")
        return client

    def create_client(self, session: Session, *, slug: str, display_name: str, description: str | None = None) -> Tenant:
        client = Tenant(
            id=f"client_{normalize_slug(slug)}",
            slug=normalize_slug(slug),
            display_name=display_name.strip() or slug.strip(),
            description=description.strip() if description else None,
            status=TenantStatus.active,
        )
        session.add(client)
        session.commit()
        return client

    def update_client(
        self,
        session: Session,
        client_slug: str,
        *,
        display_name: str,
        description: str | None,
        status: str,
        default_property_id: str | None,
    ) -> Tenant:
        client = self.get_client(session, client_slug)
        client.display_name = display_name.strip() or client.display_name
        client.description = description.strip() if description else None
        client.status = TenantStatus(status)
        if default_property_id:
            allowed = self.list_client_properties(session, client.id)
            if default_property_id not in {item.property_id for item in allowed}:
                raise ValueError("Default property must be linked to this client")
        client.default_property_id = default_property_id or None
        session.add(client)
        session.commit()
        return client

    def delete_client(self, session: Session, client_slug: str) -> None:
        client = self.get_client(session, client_slug)
        session.execute(delete(TenantAssetPolicy).where(TenantAssetPolicy.tenant_id == client.id))
        session.execute(delete(ClientSessionContext).where(ClientSessionContext.tenant_id == client.id))
        assets = session.scalars(select(AssetDirectory).where(AssetDirectory.tenant_id == client.id)).all()
        for asset in assets:
            asset.tenant_id = None
        session.delete(client)
        session.commit()

    def rotate_bearer_token(self, session: Session, client_slug: str) -> str:
        client = self.get_client(session, client_slug)
        token = issue_token("ga4mcp")
        client.bearer_token_hash = hash_token(token, self.settings.client_token_salt)
        session.add(client)
        session.commit()
        return token

    def enable_public_token(self, session: Session, client_slug: str) -> str:
        client = self.get_client(session, client_slug)
        token = issue_token("ga4public")
        client.public_enabled = True
        client.public_token_hash = hash_token(token, self.settings.client_token_salt)
        session.add(client)
        session.commit()
        return token

    def disable_public_token(self, session: Session, client_slug: str) -> None:
        client = self.get_client(session, client_slug)
        client.public_enabled = False
        client.public_token_hash = None
        session.add(client)
        session.commit()

    def authenticate_bearer(self, session: Session, client_slug: str, token: str) -> Tenant:
        client = self.get_client(session, client_slug)
        if client.status != TenantStatus.active:
            raise PermissionError("Client is disabled")
        if not verify_token(token, client.bearer_token_hash, self.settings.client_token_salt):
            raise PermissionError("Invalid bearer token")
        client.last_used_at = datetime.now(timezone.utc)
        session.add(client)
        session.commit()
        return client

    def authenticate_public(self, session: Session, public_token: str) -> Tenant:
        token_hash = hash_token(public_token, self.settings.client_token_salt)
        client = session.scalar(
            select(Tenant).where(
                Tenant.public_enabled.is_(True),
                Tenant.public_token_hash == token_hash,
            )
        )
        if client is None:
            raise PermissionError("Invalid public token")
        if client.status != TenantStatus.active:
            raise PermissionError("Client is disabled")
        client.last_used_at = datetime.now(timezone.utc)
        client.last_public_used_at = datetime.now(timezone.utc)
        session.add(client)
        session.commit()
        return client

    def list_sources(self, session: Session) -> list[Source]:
        return list(session.scalars(select(Source).order_by(Source.slug)).all())

    def get_source(self, session: Session, source_slug: str) -> Source:
        source = session.scalar(select(Source).where(Source.slug == source_slug))
        if source is None:
            raise ValueError("Unknown source")
        return source

    def save_source(
        self,
        session: Session,
        *,
        slug: str,
        display_name: str,
        client_id: str,
        client_secret: str,
        refresh_token: str,
        status: str,
        existing_slug: str | None = None,
    ) -> Source:
        source = self.get_source(session, existing_slug) if existing_slug else None
        if source is None:
            required = [client_id, client_secret, refresh_token]
            if any(not value.strip() for value in required):
                raise ValueError("Google client id, client secret, and refresh token are required")
            source = Source(
                slug=normalize_slug(slug),
                display_name=display_name.strip() or slug.strip(),
                encrypted_client_id="",
                encrypted_client_secret="",
                encrypted_refresh_token="",
            )
            session.add(source)
        source.slug = normalize_slug(slug)
        source.display_name = display_name.strip() or source.display_name
        source.status = SourceStatus(status)
        if client_id.strip():
            source.encrypted_client_id = encrypt_secret(client_id.strip(), self.settings.credentials_encryption_key)
        if client_secret.strip():
            source.encrypted_client_secret = encrypt_secret(client_secret.strip(), self.settings.credentials_encryption_key)
        if refresh_token.strip():
            source.encrypted_refresh_token = encrypt_secret(refresh_token.strip(), self.settings.credentials_encryption_key)
        session.commit()
        return source

    def delete_source(self, session: Session, source_slug: str) -> None:
        source = self.get_source(session, source_slug)
        assets = session.scalars(select(AssetDirectory).where(AssetDirectory.source_id == source.id)).all()
        for asset in assets:
            asset.source_id = None
        policies = session.scalars(select(TenantAssetPolicy).where(TenantAssetPolicy.source_id == source.id)).all()
        for policy in policies:
            policy.source_id = None
        session.delete(source)
        session.commit()

    def source_credentials(self, source: Source) -> GA4Credentials:
        return GA4Credentials(
            client_id=decrypt_secret(source.encrypted_client_id, self.settings.credentials_encryption_key),
            client_secret=decrypt_secret(source.encrypted_client_secret, self.settings.credentials_encryption_key),
            refresh_token=decrypt_secret(source.encrypted_refresh_token, self.settings.credentials_encryption_key),
        )

    async def sync_source(self, session: Session, source_slug: str) -> dict[str, object]:
        source = self.get_source(session, source_slug)
        client = GA4Client(self.settings, self.source_credentials(source))
        synced = 0
        try:
            response = await client.list_account_summaries()
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
                    data_streams = await client.list_data_streams(property_id)
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
                    self.upsert_asset(
                        session,
                        source_id=source.id,
                        property_id=property_id,
                        display_name=display_name,
                        account_id=account_id,
                        measurement_ids=measurement_ids,
                        default_uri=default_uri,
                        metadata={"property_summary": property_summary},
                    )
                    synced += 1
            source.last_synced_at = datetime.now(timezone.utc)
            source.last_sync_error = None
            session.add(source)
            session.commit()
            return {"status": "ok", "synced_properties": synced}
        except Exception as exc:
            source.last_sync_error = str(exc)
            session.add(source)
            session.commit()
            raise

    def upsert_asset(
        self,
        session: Session,
        *,
        source_id: int | None,
        property_id: str,
        display_name: str,
        account_id: str | None,
        measurement_ids: list[str],
        default_uri: str | None,
        metadata: dict,
    ) -> AssetDirectory:
        payload = {
            "property_id": property_id,
            "display_name": display_name,
            "account_id": account_id,
            "measurement_ids": measurement_ids,
            "default_uri": default_uri,
            "hostname": hostname_for_uri(default_uri),
            **metadata,
        }
        asset = session.scalar(select(AssetDirectory).where(AssetDirectory.property_id == property_id))
        if asset is None:
            asset = AssetDirectory(
                property_id=property_id,
                property_type=property_type_for_property_id(property_id),
                display_name=display_name,
                normalized_name=normalize_query(display_name),
                account_id=account_id,
                source_id=source_id,
                measurement_ids=measurement_ids,
                default_uri=default_uri,
                metadata_json=payload,
            )
            session.add(asset)
        else:
            asset.property_type = property_type_for_property_id(property_id)
            asset.display_name = display_name
            asset.normalized_name = normalize_query(display_name)
            asset.account_id = account_id
            asset.source_id = source_id
            asset.measurement_ids = measurement_ids
            asset.default_uri = default_uri
            asset.metadata_json = {**(asset.metadata_json or {}), **payload}
        return asset

    def list_assets(self, session: Session) -> list[AssetDirectory]:
        return list(session.scalars(select(AssetDirectory).order_by(AssetDirectory.display_name)).all())

    def list_client_properties(self, session: Session, tenant_id: str) -> list[AssetDirectory]:
        return list(
            session.scalars(
                select(AssetDirectory)
                .where(AssetDirectory.tenant_id == tenant_id)
                .order_by(AssetDirectory.display_name)
            ).all()
        )

    def set_client_properties(
        self,
        session: Session,
        *,
        client_slug: str,
        property_ids: list[str],
        default_property_id: str | None,
    ) -> None:
        client = self.get_client(session, client_slug)
        normalized_ids = [property_id.strip() for property_id in property_ids if property_id.strip()]
        seen = set(normalized_ids)
        if default_property_id and default_property_id not in seen:
            raise ValueError("Default property must be selected")
        if not default_property_id and normalized_ids:
            default_property_id = normalized_ids[0]

        session.execute(delete(TenantAssetPolicy).where(TenantAssetPolicy.tenant_id == client.id))
        for asset in session.scalars(select(AssetDirectory).where(AssetDirectory.tenant_id == client.id)).all():
            if asset.property_id not in seen:
                asset.tenant_id = None

        for property_id in normalized_ids:
            asset = session.scalar(select(AssetDirectory).where(AssetDirectory.property_id == property_id))
            if asset is None:
                continue
            asset.tenant_id = client.id
            session.add(
                TenantAssetPolicy(
                    tenant_id=client.id,
                    property_id=asset.property_id,
                    source_id=asset.source_id,
                    is_default=asset.property_id == default_property_id,
                    label_snapshot=asset.display_name,
                )
            )
        client.default_property_id = default_property_id
        session.add(client)
        session.commit()

    def build_mcp_urls(self, client_slug: str, public_token: str | None = None) -> dict[str, str]:
        base = self.settings.app_base_url.rstrip("/")
        if not base:
            return {"authenticated_url": "", "public_url": ""}
        return {
            "authenticated_url": f"{base}/mcp/ga4/clients/{client_slug}",
            "public_url": f"{base}/mcp/ga4/public/{public_token}" if public_token else "",
        }

