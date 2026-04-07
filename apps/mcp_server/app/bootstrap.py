from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.db.models import Base, WorkerType
from app.db.session import normalize_database_url
from app.services.tenant_admin_service import parse_json_list, upsert_client_tenant, upsert_worker_credential


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Bootstrap tenant and worker credentials")
    parser.add_argument("--tenant-id")
    parser.add_argument("--tenant-slug")
    parser.add_argument("--tenant-name")
    parser.add_argument("--default-property-id")
    parser.add_argument("--allowed-properties", default="[]")
    parser.add_argument("--worker-type", choices=[item.value for item in WorkerType], required=True)
    parser.add_argument("--worker-key-id", required=True)
    parser.add_argument("--worker-secret", required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    settings = Settings()
    engine = create_engine(normalize_database_url(settings.database_url), future=True)
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, expire_on_commit=False, class_=Session)

    with session_factory() as session:
        if args.worker_type == WorkerType.client.value:
            output = upsert_client_tenant(
                session,
                settings,
                tenant_id=args.tenant_id,
                tenant_slug=args.tenant_slug,
                tenant_name=args.tenant_name,
                worker_key_id=args.worker_key_id,
                worker_secret=args.worker_secret,
                allowed_properties=parse_json_list(args.allowed_properties),
                default_property_id=args.default_property_id,
            )
        else:
            credential = upsert_worker_credential(
                session,
                settings,
                worker_key_id=args.worker_key_id,
                worker_secret=args.worker_secret,
                worker_type=WorkerType.admin,
                tenant_id=None,
            )
            session.commit()
            output = {"tenant_id": None, "worker_key_id": credential.key_id}

    output["worker_type"] = args.worker_type
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
