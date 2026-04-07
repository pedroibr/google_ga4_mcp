from __future__ import annotations

import pytest

from app.core.context import ExecutionProfile, OperationalContext, WorkerRequestContext
from app.core.policy import PolicyService


def test_policy_resolves_default_property(seeded_db):
    request_context = WorkerRequestContext(
        worker_key_id="client-key-1",
        worker_type="client",
        execution_profile=ExecutionProfile.client_scoped,
        tenant_id="tenant_luis",
    )
    resolved = PolicyService().resolve_context_for_request(seeded_db, request_context)
    assert resolved.active_property_id == "123456789"


def test_policy_exposes_default_property_id(seeded_db):
    policy = PolicyService().get_policy(seeded_db, "tenant_luis")
    assert policy.default_property_id == "123456789"
    assert policy.allowed_property_ids == ["123456789", "987654321"]


def test_policy_rejects_outside_property(seeded_db):
    request_context = WorkerRequestContext(
        worker_key_id="client-key-1",
        worker_type="client",
        execution_profile=ExecutionProfile.client_scoped,
        tenant_id="tenant_luis",
        operational_context=OperationalContext(
            tenant_id="tenant_luis",
            active_property_id="555555555",
        ),
    )
    with pytest.raises(PermissionError):
        PolicyService().resolve_context_for_request(seeded_db, request_context)
