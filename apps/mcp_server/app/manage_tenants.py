from __future__ import annotations

import argparse
import json

from sqlalchemy import create_engine, delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.api.internal_auth import InternalAuthService
from app.config import Settings
from app.db.models import WorkerCredential, WorkerCredentialStatus
from app.db.session import normalize_database_url
from app.services.tenant_admin_service import (
    delete_tenant_and_related,
    list_tenants_payload,
    show_tenant_payload,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Manage tenants and worker credentials")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list-tenants")
    show_tenant = subparsers.add_parser("show-tenant")
    show_tenant.add_argument("--tenant-id", required=True)
    delete_tenant = subparsers.add_parser("delete-tenant")
    delete_tenant.add_argument("--tenant-id", required=True)

    subparsers.add_parser("list-workers")
    show_worker = subparsers.add_parser("show-worker")
    show_worker.add_argument("--worker-key-id", required=True)
    disable_worker = subparsers.add_parser("disable-worker")
    disable_worker.add_argument("--worker-key-id", required=True)
    delete_worker = subparsers.add_parser("delete-worker")
    delete_worker.add_argument("--worker-key-id", required=True)
    rotate_secret = subparsers.add_parser("rotate-worker-secret")
    rotate_secret.add_argument("--worker-key-id", required=True)
    rotate_secret.add_argument("--worker-secret", required=True)

    return parser


def json_print(payload: object) -> None:
    print(json.dumps(payload, indent=2, default=str))


def session_factory_from_settings(settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(normalize_database_url(settings.database_url), future=True)
    return sessionmaker(bind=engine, expire_on_commit=False, class_=Session)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    settings = Settings()
    factory = session_factory_from_settings(settings)

    with factory() as session:
        if args.command == "list-tenants":
            json_print(list_tenants_payload(session))
            return
        if args.command == "show-tenant":
            json_print(show_tenant_payload(session, args.tenant_id))
            return
        if args.command == "delete-tenant":
            json_print(delete_tenant_and_related(session, args.tenant_id))
            return
        if args.command == "list-workers":
            rows = session.scalars(select(WorkerCredential).order_by(WorkerCredential.key_id)).all()
            json_print(
                [
                    {
                        "key_id": row.key_id,
                        "worker_type": row.worker_type.value,
                        "tenant_id": row.tenant_id,
                        "status": row.status.value,
                        "last_used_at": row.last_used_at,
                    }
                    for row in rows
                ]
            )
            return
        if args.command == "show-worker":
            worker = session.scalar(select(WorkerCredential).where(WorkerCredential.key_id == args.worker_key_id))
            if worker is None:
                raise ValueError(f"Unknown worker key: {args.worker_key_id}")
            json_print(
                {
                    "key_id": worker.key_id,
                    "worker_type": worker.worker_type.value,
                    "tenant_id": worker.tenant_id,
                    "status": worker.status.value,
                    "created_at": worker.created_at,
                    "last_used_at": worker.last_used_at,
                }
            )
            return
        if args.command == "disable-worker":
            worker = session.scalar(select(WorkerCredential).where(WorkerCredential.key_id == args.worker_key_id))
            if worker is None:
                raise ValueError(f"Unknown worker key: {args.worker_key_id}")
            worker.status = WorkerCredentialStatus.disabled
            session.add(worker)
            session.commit()
            json_print({"disabled_worker_key_id": args.worker_key_id})
            return
        if args.command == "delete-worker":
            worker = session.scalar(select(WorkerCredential).where(WorkerCredential.key_id == args.worker_key_id))
            if worker is None:
                raise ValueError(f"Unknown worker key: {args.worker_key_id}")
            session.execute(delete(WorkerCredential).where(WorkerCredential.key_id == args.worker_key_id))
            session.commit()
            json_print({"deleted_worker_key_id": args.worker_key_id})
            return
        if args.command == "rotate-worker-secret":
            worker = session.scalar(select(WorkerCredential).where(WorkerCredential.key_id == args.worker_key_id))
            if worker is None:
                raise ValueError(f"Unknown worker key: {args.worker_key_id}")
            auth_service = InternalAuthService(settings)
            worker.secret_hash = auth_service.hash_secret(args.worker_secret, settings.worker_shared_secret_salt)
            worker.status = WorkerCredentialStatus.active
            session.add(worker)
            session.commit()
            json_print({"rotated_worker_key_id": args.worker_key_id})
            return


if __name__ == "__main__":
    main()
