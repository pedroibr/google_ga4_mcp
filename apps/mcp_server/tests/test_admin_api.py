from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import create_mcp_server


def _build_client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("DATABASE_URL", f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("WORKER_SHARED_SECRET_SALT", "salt")
    monkeypatch.setenv("ADMIN_API_SHARED_SECRET", "super-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_ID", "client-id")
    monkeypatch.setenv("GOOGLE_OAUTH_CLIENT_SECRET", "client-secret")
    monkeypatch.setenv("GOOGLE_OAUTH_REFRESH_TOKEN", "refresh-token")
    get_settings.cache_clear()
    app, _ = create_mcp_server()
    return TestClient(app)


def test_upsert_and_show_tenant(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/client-tenants/upsert",
        headers={"Authorization": "Bearer super-secret"},
        json={
            "tenant_id": "tenant_luis",
            "tenant_slug": "luis",
            "tenant_name": "Luis Analytics",
            "worker_key_id": "worker-client-luis",
            "worker_secret": "worker-secret",
            "allowed_properties": [
                {
                    "property_id": "123456789",
                    "display_name": "Luis Main",
                    "measurement_ids": ["g-aaaa1111", "G-AAAA1111"],
                    "default_uri": "https://www.luis.com",
                },
                {
                    "property_id": "987654321",
                    "display_name": "Luis Blog",
                    "measurement_ids": ["G-BBBB2222"],
                    "default_uri": "https://blog.luis.com",
                },
            ],
            "default_property_id": "123456789",
        },
    )

    assert response.status_code == 200
    assert response.json()["default_property_id"] == "123456789"
    assert response.json()["allowed_properties"][0]["measurement_ids"] == ["G-AAAA1111"]

    detail = client.get(
        "/api/v1/tenants/tenant_luis",
        headers={"Authorization": "Bearer super-secret"},
    )
    assert detail.status_code == 200
    assert detail.json()["tenant"]["default_property_id"] == "123456789"
    assert detail.json()["asset_directory"][0]["measurement_ids"] == ["G-AAAA1111"]


def test_upsert_rejects_invalid_default(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/client-tenants/upsert",
        headers={"Authorization": "Bearer super-secret"},
        json={
            "tenant_id": "tenant_luis",
            "tenant_slug": "luis",
            "tenant_name": "Luis Analytics",
            "worker_key_id": "worker-client-luis",
            "worker_secret": "worker-secret",
            "allowed_properties": [{"property_id": "123456789"}],
            "default_property_id": "987654321",
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "default_property_id must be included in allowed_properties"


def test_upsert_rejects_duplicate_property_id(tmp_path: Path, monkeypatch) -> None:
    client = _build_client(tmp_path, monkeypatch)
    response = client.post(
        "/api/v1/client-tenants/upsert",
        headers={"Authorization": "Bearer super-secret"},
        json={
            "tenant_id": "tenant_luis",
            "tenant_slug": "luis",
            "tenant_name": "Luis Analytics",
            "worker_key_id": "worker-client-luis",
            "worker_secret": "worker-secret",
            "allowed_properties": [{"property_id": "123456789"}, {"property_id": "123456789"}],
        },
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "allowed_properties must not contain duplicate property_id values"
