from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.core.asset_resolver import normalize_query, property_type_for_property_id
from app.db.models import AssetDirectory, Base, Tenant
from app.db.session import normalize_database_url
from app.main import create_mcp_server
from app.services.platform_service import PlatformService


def _settings(database_url: str) -> Settings:
    return Settings(
        DATABASE_URL=database_url,
        ADMIN_UI_PASSWORD="admin-pass",
        ADMIN_SESSION_SECRET="admin-session-secret",
        CLIENT_TOKEN_SALT="client-token-salt",
        CREDENTIALS_ENCRYPTION_KEY="credentials-key",
        APP_BASE_URL="https://ga4.example.com",
        ADMIN_API_SHARED_SECRET="admin-secret",
    )


def _session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(normalize_database_url(settings.database_url), future=True)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def test_source_secrets_are_encrypted_and_decryptable(tmp_path: Path) -> None:
    settings = _settings(f"sqlite+pysqlite:///{tmp_path / 'test.db'}")
    factory = _session_factory(settings)
    platform = PlatformService(settings)

    with factory() as session:
        source = platform.save_source(
            session,
            slug="agency-google",
            display_name="Agency Google",
            client_id="google-client-id",
            client_secret="google-client-secret",
            refresh_token="google-refresh-token",
            status="active",
        )

        assert source.encrypted_client_id != "google-client-id"
        assert source.encrypted_client_secret != "google-client-secret"
        assert source.encrypted_refresh_token != "google-refresh-token"

        credentials = platform.source_credentials(source)
        assert credentials.client_id == "google-client-id"
        assert credentials.client_secret == "google-client-secret"
        assert credentials.refresh_token == "google-refresh-token"


def test_direct_mcp_auth_and_context_tools_follow_asset_count(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ADMIN_UI_PASSWORD", "admin-pass")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "admin-session-secret")
    monkeypatch.setenv("CLIENT_TOKEN_SALT", "client-token-salt")
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "credentials-key")
    monkeypatch.setenv("APP_BASE_URL", "https://ga4.example.com")
    monkeypatch.setenv("ADMIN_API_SHARED_SECRET", "admin-secret")
    get_settings.cache_clear()
    app, _ = create_mcp_server()
    client = TestClient(app)

    settings = get_settings()
    factory = _session_factory(settings)
    platform = PlatformService(settings)

    with factory() as session:
        source = platform.save_source(
            session,
            slug="agency-google",
            display_name="Agency Google",
            client_id="google-client-id",
            client_secret="google-client-secret",
            refresh_token="google-refresh-token",
            status="active",
        )
        platform.create_client(session, slug="luis", display_name="Luis Analytics")
        _add_asset(session, "123456789", "Luis Main", source.id)
        platform.set_client_properties(
            session,
            client_slug="luis",
            property_ids=["123456789"],
            default_property_id="123456789",
        )
        bearer_token = platform.rotate_bearer_token(session, "luis")

    response = client.post(
        "/mcp/ga4/clients/luis",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "run_report" in tool_names
    assert "list_my_properties" not in tool_names
    assert "select_my_property" not in tool_names

    with factory() as session:
        _add_asset(session, "987654321", "Luis Blog", source.id)
        platform.set_client_properties(
            session,
            client_slug="luis",
            property_ids=["123456789", "987654321"],
            default_property_id="123456789",
        )

    response = client.post(
        "/mcp/ga4/clients/luis",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    )
    assert response.status_code == 200
    tool_names = {tool["name"] for tool in response.json()["result"]["tools"]}
    assert "list_my_properties" in tool_names
    assert "select_my_property" in tool_names

    response = client.post(
        "/mcp/ga4/clients/luis",
        headers={"Authorization": f"Bearer {bearer_token}", "mcp-session-id": "session-1"},
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "select_my_property", "arguments": {"query": "blog"}},
        },
    )
    assert response.status_code == 200
    payload = response.json()["result"]["content"][0]["text"]
    assert '"active_property_id": "987654321"' in payload

    response = client.post(
        "/mcp/ga4/clients/luis",
        headers={"Authorization": f"Bearer {bearer_token}", "mcp-session-id": "session-1"},
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "get_active_context", "arguments": {}},
        },
    )
    assert response.status_code == 200
    payload = response.json()["result"]["content"][0]["text"]
    assert '"active_property_id": "987654321"' in payload


def test_direct_mcp_public_token_auth(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ADMIN_UI_PASSWORD", "admin-pass")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "admin-session-secret")
    monkeypatch.setenv("CLIENT_TOKEN_SALT", "client-token-salt")
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "credentials-key")
    monkeypatch.setenv("APP_BASE_URL", "https://ga4.example.com")
    monkeypatch.setenv("ADMIN_API_SHARED_SECRET", "admin-secret")
    get_settings.cache_clear()
    app, _ = create_mcp_server()
    client = TestClient(app)

    settings = get_settings()
    factory = _session_factory(settings)
    platform = PlatformService(settings)
    with factory() as session:
        source = platform.save_source(
            session,
            slug="agency-google",
            display_name="Agency Google",
            client_id="google-client-id",
            client_secret="google-client-secret",
            refresh_token="google-refresh-token",
            status="active",
        )
        platform.create_client(session, slug="luis", display_name="Luis Analytics")
        _add_asset(session, "123456789", "Luis Main", source.id)
        platform.set_client_properties(
            session,
            client_slug="luis",
            property_ids=["123456789"],
            default_property_id="123456789",
        )
        public_token = platform.enable_public_token(session, "luis")

    response = client.post(
        f"/mcp/ga4/public/{public_token}",
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 200
    assert response.json()["result"]["tools"]


def test_direct_mcp_keeps_context_from_mcp_meta_session_key(tmp_path: Path, monkeypatch) -> None:
    database_url = f"sqlite+pysqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", database_url)
    monkeypatch.setenv("ADMIN_UI_PASSWORD", "admin-pass")
    monkeypatch.setenv("ADMIN_SESSION_SECRET", "admin-session-secret")
    monkeypatch.setenv("CLIENT_TOKEN_SALT", "client-token-salt")
    monkeypatch.setenv("CREDENTIALS_ENCRYPTION_KEY", "credentials-key")
    monkeypatch.setenv("APP_BASE_URL", "https://ga4.example.com")
    monkeypatch.setenv("ADMIN_API_SHARED_SECRET", "admin-secret")
    get_settings.cache_clear()
    app, _ = create_mcp_server()
    client = TestClient(app)

    settings = get_settings()
    factory = _session_factory(settings)
    platform = PlatformService(settings)
    with factory() as session:
        source = platform.save_source(
            session,
            slug="agency-google",
            display_name="Agency Google",
            client_id="google-client-id",
            client_secret="google-client-secret",
            refresh_token="google-refresh-token",
            status="active",
        )
        platform.create_client(session, slug="luis", display_name="Luis Analytics")
        _add_asset(session, "123456789", "Luis Main", source.id)
        _add_asset(session, "987654321", "Luis Blog", source.id)
        platform.set_client_properties(
            session,
            client_slug="luis",
            property_ids=["123456789", "987654321"],
            default_property_id="123456789",
        )
        bearer_token = platform.rotate_bearer_token(session, "luis")

    response = client.post(
        "/mcp/ga4/clients/luis",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "_meta": {"session_id": "meta-session-1"},
                "name": "select_my_property",
                "arguments": {"query": "blog"},
            },
        },
    )
    assert response.status_code == 200
    assert '"active_property_id": "987654321"' in response.json()["result"]["content"][0]["text"]

    response = client.post(
        "/mcp/ga4/clients/luis",
        headers={"Authorization": f"Bearer {bearer_token}"},
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {
                "_meta": {"session_id": "meta-session-1"},
                "name": "get_active_context",
                "arguments": {},
            },
        },
    )
    assert response.status_code == 200
    assert '"active_property_id": "987654321"' in response.json()["result"]["content"][0]["text"]


def _add_asset(session: Session, property_id: str, display_name: str, source_id: int) -> None:
    session.add(
        AssetDirectory(
            property_id=property_id,
            property_type=property_type_for_property_id(property_id),
            display_name=display_name,
            normalized_name=normalize_query(display_name),
            account_id="111111",
            source_id=source_id,
            measurement_ids=[f"G-{property_id[-4:]}"],
            default_uri=f"https://{display_name.lower().replace(' ', '-')}.example.com",
            metadata_json={"property_id": property_id},
        )
    )
    session.commit()
