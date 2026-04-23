from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlparse

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.context import OperationalContext
from app.db.models import AssetDirectory, Tenant


def normalize_query(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value.casefold())
    ascii_only = "".join(char for char in decomposed if not unicodedata.combining(char))
    punctuation_as_space = re.sub(r"[^a-z0-9]+", " ", ascii_only)
    return " ".join(punctuation_as_space.split())


def property_type_for_property_id(property_id: str) -> str:
    return "ga4_property" if str(property_id).strip() else "unknown"


def display_name_for_property(property_id: str, display_name: str | None = None) -> str:
    if display_name and display_name.strip():
        return display_name.strip()
    return f"GA4 Property {property_id}"


def hostname_for_uri(uri: str | None) -> str | None:
    if not uri:
        return None
    parsed = urlparse(uri)
    return parsed.netloc or None


class PropertySearchCandidate(BaseModel):
    property_id: str
    display_name: str
    property_type: str
    account_id: str | None
    source_id: int | None = None
    measurement_ids: list[str]
    default_uri: str | None
    tenant_id: str | None
    score: int


class AssetResolver:
    def list_accessible_contexts(self, session: Session, *, limit: int = 100) -> list[dict[str, object]]:
        bounded_limit = max(1, min(limit, 500))
        tenants = session.scalars(select(Tenant)).all()
        rows: list[dict[str, object]] = []
        for tenant in tenants:
            if tenant.status.value != "active":
                continue
            rows.append(
                {
                    "tenant_id": tenant.id,
                    "tenant_slug": tenant.slug,
                    "tenant_name": tenant.display_name,
                    "default_property": self._build_property_reference(
                        session,
                        tenant_id=tenant.id,
                        property_id=tenant.default_property_id,
                    ),
                }
            )
        rows.sort(key=lambda item: str(item["tenant_name"]).casefold())
        return rows[:bounded_limit]

    def resolve_context_from_client_query(self, session: Session, *, query: str, limit: int = 10) -> dict:
        tenant_match = self._resolve_tenant_from_query(session, query)
        if tenant_match is not None:
            context = self._build_context_from_tenant(tenant_match, source_query=query)
            return {
                "resolved": True,
                "query": query,
                "match_type": "tenant",
                "tenant": {
                    "tenant_id": tenant_match.id,
                    "slug": tenant_match.slug,
                    "display_name": tenant_match.display_name,
                },
                "context": context.model_dump(),
            }

        candidates = self.search_properties(session, query=query, limit=limit, mapped_only=True)
        if not candidates:
            return {
                "resolved": False,
                "query": query,
                "candidates": [],
                "message": "No tenant or property matched the query",
            }

        best_score = candidates[0].score
        best = [candidate for candidate in candidates if candidate.score == best_score]
        tenant_ids = {candidate.tenant_id for candidate in best if candidate.tenant_id}
        if len(best) == 1 and len(tenant_ids) == 1:
            selected = best[0]
            context = self.resolve_context_from_property_reference(
                session,
                property_reference=selected.property_id,
                source_query=query,
            )
            return {
                "resolved": True,
                "query": query,
                "match_type": "property_fallback",
                "selected_property": selected.model_dump(),
                "context": context.model_dump(),
            }

        return {
            "resolved": False,
            "query": query,
            "candidates": [candidate.model_dump() for candidate in candidates],
            "message": "Multiple tenants or properties matched the query",
        }

    def list_properties_for_tenant(self, session: Session, tenant_id: str, *, limit: int = 50) -> list[PropertySearchCandidate]:
        rows = session.scalars(
            select(AssetDirectory).where(AssetDirectory.tenant_id == tenant_id).order_by(AssetDirectory.display_name)
        ).all()
        return [
            PropertySearchCandidate(
                property_id=row.property_id,
                display_name=row.display_name,
                property_type=row.property_type,
                account_id=row.account_id,
                source_id=row.source_id,
                measurement_ids=list(row.measurement_ids or []),
                default_uri=row.default_uri,
                tenant_id=row.tenant_id,
                score=0,
            )
            for row in rows[:limit]
        ]

    def search_properties(
        self,
        session: Session,
        query: str,
        limit: int = 10,
        *,
        tenant_id: str | None = None,
        mapped_only: bool = False,
    ) -> list[PropertySearchCandidate]:
        normalized = normalize_query(query)
        statement = select(AssetDirectory)
        if tenant_id is not None:
            statement = statement.where(AssetDirectory.tenant_id == tenant_id)
        elif mapped_only:
            statement = statement.where(AssetDirectory.tenant_id.is_not(None))
        rows = session.scalars(statement).all()
        candidates: list[PropertySearchCandidate] = []
        for row in rows:
            score = self._score(normalized, row)
            if score <= 0:
                continue
            candidates.append(
                PropertySearchCandidate(
                    property_id=row.property_id,
                    display_name=row.display_name,
                    property_type=row.property_type,
                    account_id=row.account_id,
                    source_id=row.source_id,
                    measurement_ids=list(row.measurement_ids or []),
                    default_uri=row.default_uri,
                    tenant_id=row.tenant_id,
                    score=score,
                )
            )
        candidates.sort(key=lambda item: (-item.score, item.display_name, item.property_id))
        return candidates[:limit]

    def resolve_context_from_property_reference(
        self,
        session: Session,
        *,
        property_reference: str,
        source_query: str | None = None,
        tenant_id: str | None = None,
    ) -> OperationalContext:
        normalized_reference = normalize_query(property_reference)
        statement = select(AssetDirectory)
        if tenant_id is not None:
            statement = statement.where(AssetDirectory.tenant_id == tenant_id)
        rows = session.scalars(statement).all()

        selected = next(
            (
                row
                for row in rows
                if row.property_id == property_reference
                or row.normalized_name == normalized_reference
                or normalize_query(row.property_id) == normalized_reference
                or normalized_reference in {normalize_query(measurement_id) for measurement_id in (row.measurement_ids or [])}
                or normalize_query(hostname_for_uri(row.default_uri) or "") == normalized_reference
            ),
            None,
        )
        if selected is None:
            matches = self.search_properties(session, property_reference, limit=1, tenant_id=tenant_id)
            if not matches:
                raise ValueError(f"No property matched reference: {property_reference}")
            selected = session.scalar(select(AssetDirectory).where(AssetDirectory.property_id == matches[0].property_id))

        if selected is None:
            raise ValueError(f"No property matched reference: {property_reference}")
        if selected.tenant_id is None:
            raise ValueError(f"Property {selected.property_id} is not mapped to a tenant")

        return OperationalContext(
            tenant_id=selected.tenant_id,
            active_property_id=selected.property_id,
            resolved_from_query=source_query or property_reference,
            resolved_from_property_id=selected.property_id,
        )

    def select_context_from_query(
        self,
        session: Session,
        *,
        query: str,
        tenant_id: str,
        limit: int = 10,
    ) -> dict:
        candidates = self.search_properties(session, query=query, limit=limit, tenant_id=tenant_id)
        if not candidates:
            return {
                "resolved": False,
                "query": query,
                "candidates": [],
                "message": "No allowed properties matched the query",
            }

        best_score = candidates[0].score
        best = [candidate for candidate in candidates if candidate.score == best_score]
        if len(best) != 1:
            return {
                "resolved": False,
                "query": query,
                "candidates": [candidate.model_dump() for candidate in candidates],
                "message": "Multiple allowed properties matched the query",
            }

        winner = best[0]
        context = self.resolve_context_from_property_reference(
            session,
            property_reference=winner.property_id,
            source_query=query,
            tenant_id=tenant_id,
        )
        return {
            "resolved": True,
            "query": query,
            "selected_property": winner.model_dump(),
            "context": context.model_dump(),
        }

    def _resolve_tenant_from_query(self, session: Session, query: str) -> Tenant | None:
        normalized = normalize_query(query)
        tenants = session.scalars(select(Tenant)).all()
        matches = [
            tenant
            for tenant in tenants
            if tenant.status.value == "active"
            and (
                normalize_query(tenant.slug) == normalized
                or normalize_query(tenant.display_name) == normalized
                or normalized in normalize_query(tenant.slug)
                or normalized in normalize_query(tenant.display_name)
            )
        ]
        if len(matches) == 1:
            return matches[0]
        return None

    def _build_context_from_tenant(self, tenant: Tenant, *, source_query: str) -> OperationalContext:
        return OperationalContext(
            tenant_id=tenant.id,
            active_property_id=tenant.default_property_id,
            resolved_from_query=source_query,
            resolved_from_property_id=tenant.default_property_id,
        )

    def _build_property_reference(
        self,
        session: Session,
        *,
        tenant_id: str,
        property_id: str | None,
    ) -> dict[str, object] | None:
        if property_id is None:
            return None
        row = session.scalar(
            select(AssetDirectory).where(
                AssetDirectory.tenant_id == tenant_id,
                AssetDirectory.property_id == property_id,
            )
        )
        if row is None:
            return {"property_id": property_id}
        return {
            "property_id": row.property_id,
            "display_name": row.display_name,
            "property_type": row.property_type,
            "account_id": row.account_id,
            "source_id": row.source_id,
            "measurement_ids": list(row.measurement_ids or []),
            "default_uri": row.default_uri,
        }

    def _score(self, normalized_query: str, row: AssetDirectory) -> int:
        if not normalized_query:
            return 0

        exact_haystacks = {
            normalize_query(row.property_id),
            row.normalized_name,
            normalize_query(hostname_for_uri(row.default_uri) or ""),
            *(normalize_query(measurement_id) for measurement_id in (row.measurement_ids or [])),
        }
        if normalized_query in exact_haystacks:
            return 100

        partial_haystacks = [
            normalize_query(row.property_id),
            row.normalized_name,
            normalize_query(row.account_id or ""),
            normalize_query(hostname_for_uri(row.default_uri) or ""),
            *(normalize_query(measurement_id) for measurement_id in (row.measurement_ids or [])),
        ]
        if any(normalized_query in haystack for haystack in partial_haystacks if haystack):
            return 60
        return 0
