from __future__ import annotations

from app.core.asset_resolver import AssetResolver
from app.db.models import AssetDirectory


def test_search_properties_matches_property_id(seeded_db) -> None:
    resolver = AssetResolver()
    results = resolver.search_properties(seeded_db, query="123456789", tenant_id="tenant_luis")
    assert results[0].property_id == "123456789"


def test_search_properties_matches_measurement_id(seeded_db) -> None:
    resolver = AssetResolver()
    results = resolver.search_properties(seeded_db, query="G-BBBB2222", tenant_id="tenant_luis")
    assert results[0].property_id == "987654321"


def test_select_context_from_hostname(seeded_db) -> None:
    resolver = AssetResolver()
    result = resolver.select_context_from_query(seeded_db, query="blog.luis.com", tenant_id="tenant_luis")
    assert result["resolved"] is True
    assert result["context"]["active_property_id"] == "987654321"


def test_resolve_context_from_client_query_matches_tenant(seeded_db) -> None:
    resolver = AssetResolver()
    result = resolver.resolve_context_from_client_query(seeded_db, query="Luis Analytics")
    assert result["resolved"] is True
    assert result["context"]["active_property_id"] == "123456789"


def test_resolve_context_from_property_reference_rejects_unmapped_property(seeded_db) -> None:
    seeded_db.add(
        AssetDirectory(
            property_id="999999999",
            property_type="ga4_property",
            display_name="Unmapped",
            normalized_name="unmapped",
            account_id="333333",
            measurement_ids=["G-ZZZZ9999"],
            default_uri="https://unmapped.example.com",
            tenant_id=None,
            metadata_json={"property_id": "999999999"},
        )
    )
    seeded_db.commit()

    resolver = AssetResolver()
    try:
        resolver.resolve_context_from_property_reference(seeded_db, property_reference="999999999")
        assert False, "Expected ValueError"
    except ValueError as exc:
        assert str(exc) == "Property 999999999 is not mapped to a tenant"
