from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.tools.ga4_tools import _compare_date_ranges, _run_report


class FakeGA4Client:
    def __init__(self):
        self.requests: list[tuple[str, dict]] = []

    async def run_report(self, property_id: str, request: dict) -> dict:
        self.requests.append((property_id, request))
        return {"rows": [{"dimensionValues": [], "metricValues": []}]}


def test_run_report_builds_dimension_filter() -> None:
    fake_client = FakeGA4Client()
    services = SimpleNamespace(ga4_client=fake_client)

    result = asyncio.run(
        _run_report(
            services,
            "123456789",
            start_date="2026-03-01",
            end_date="2026-03-31",
            metrics=["sessions"],
            dimensions=["pagePath"],
            row_limit=50,
            offset=0,
            filters=[{"field_name": "pagePath", "match_type": "EXACT", "value": "/pricing", "values": []}],
            order_bys=[],
            keep_empty_rows=False,
        )
    )

    property_id, request = fake_client.requests[0]
    assert property_id == "123456789"
    assert request["dimensionFilter"]["filter"]["fieldName"] == "pagePath"
    assert result["row_count"] == 1


def test_compare_date_ranges_uses_two_date_ranges() -> None:
    fake_client = FakeGA4Client()
    services = SimpleNamespace(ga4_client=fake_client)

    asyncio.run(
        _compare_date_ranges(
            services,
            "123456789",
            period1_start="2026-03-01",
            period1_end="2026-03-31",
            period2_start="2026-02-01",
            period2_end="2026-02-28",
            metrics=["sessions"],
            dimensions=["sessionDefaultChannelGroup"],
            row_limit=20,
        )
    )

    _, request = fake_client.requests[0]
    assert len(request["dateRanges"]) == 2
    assert request["dateRanges"][0]["name"] == "period_1"
    assert request["dateRanges"][1]["name"] == "period_2"
