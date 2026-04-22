from collections.abc import Generator

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Base


def normalize_database_url(database_url: str) -> str:
    if database_url.startswith("postgresql+"):
        return database_url
    if database_url.startswith("postgres://"):
        return database_url.replace("postgres://", "postgresql+psycopg://", 1)
    if database_url.startswith("postgresql://"):
        return database_url.replace("postgresql://", "postgresql+psycopg://", 1)
    return database_url


def create_session_factory(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(normalize_database_url(settings.database_url), future=True)
    Base.metadata.create_all(engine)
    ensure_runtime_columns(engine)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def ensure_runtime_columns(engine) -> None:
    inspector = inspect(engine)
    if "tenants" in inspector.get_table_names():
        _ensure_column(engine, inspector, "tenants", "description", "TEXT")
        _ensure_column(engine, inspector, "tenants", "bearer_token_hash", "VARCHAR(255)")
        _ensure_column(engine, inspector, "tenants", "public_token_hash", "VARCHAR(255)")
        _ensure_column(engine, inspector, "tenants", "public_enabled", "BOOLEAN DEFAULT false")
        _ensure_column(engine, inspector, "tenants", "last_used_at", "TIMESTAMP")
        _ensure_column(engine, inspector, "tenants", "last_public_used_at", "TIMESTAMP")
    if "tenant_asset_policies" in inspector.get_table_names():
        _ensure_column(engine, inspector, "tenant_asset_policies", "source_id", "INTEGER")
    if "asset_directory" in inspector.get_table_names():
        _ensure_column(engine, inspector, "asset_directory", "source_id", "INTEGER")


def _ensure_column(engine, inspector, table_name: str, column_name: str, column_type: str) -> None:
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if column_name in columns:
        return
    with engine.begin() as connection:
        connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"))


def session_dependency(session_factory: sessionmaker[Session]) -> Generator[Session, None, None]:
    session = session_factory()
    try:
        yield session
    finally:
        session.close()
