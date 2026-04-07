from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.orm import sessionmaker

from app.core.asset_resolver import AssetResolver
from app.core.audit import AuditService
from app.core.ga4_client import GA4Client
from app.core.policy import PolicyService


@dataclass(slots=True)
class ToolServices:
    session_factory: sessionmaker
    policy_service: PolicyService
    asset_resolver: AssetResolver
    ga4_client: GA4Client
    audit_service: AuditService
