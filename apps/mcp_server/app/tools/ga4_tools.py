from __future__ import annotations

from datetime import date, timedelta
from typing import Annotated, Any

from pydantic import BaseModel, Field

from app.core.context import get_request_context
from app.tools.error_handling import build_failure_summary
from app.tools.services import ToolServices


class ReportFilter(BaseModel):
    field_name: str = Field(description="Dimension field to filter on, for example 'pagePath' or 'sessionDefaultChannelGroup'.")
    match_type: str = Field(
        description="String filter match type: EXACT, CONTAINS, BEGINS_WITH, ENDS_WITH, FULL_REGEXP, PARTIAL_REGEXP, or IN_LIST."
    )
    value: str | None = Field(default=None, description="Filter value for all match types except IN_LIST.")
    values: list[str] = Field(default_factory=list, description="List of values when match_type is IN_LIST.")


class ReportOrderBy(BaseModel):
    field_name: str = Field(description="Metric or dimension name used for ordering.")
    descending: bool = Field(default=True, description="Whether the ordering should be descending.")
    order_type: str = Field(default="metric", description="Use 'metric' or 'dimension'.")


def register_ga4_tools(mcp, services: ToolServices) -> None:
    @mcp.tool(description="Return GA4 property details and known stream metadata for the active property.")
    async def get_property_details() -> dict:
        return await _run_with_context(mcp, services, "get_property_details", _get_property_details)

    @mcp.tool(description="Return GA4 reporting metadata for the active property.")
    async def get_reporting_metadata() -> dict:
        return await _run_with_context(mcp, services, "get_reporting_metadata", _get_reporting_metadata)

    @mcp.tool(
        description="Run a GA4 report for the active property using explicit metrics, optional dimensions, date range, filters, and ordering."
    )
    async def run_report(
        start_date: Annotated[str, Field(description="Inclusive start date in YYYY-MM-DD format or GA4 tokens like '7daysAgo'.")] = "28daysAgo",
        end_date: Annotated[str, Field(description="Inclusive end date in YYYY-MM-DD format or GA4 tokens like 'today'.")] = "today",
        metrics: Annotated[list[str], Field(description="GA4 metric API names, for example ['sessions', 'totalUsers'].")]=["sessions"],
        dimensions: Annotated[list[str] | None, Field(description="Optional GA4 dimension API names.")] = None,
        row_limit: Annotated[int, Field(description="Maximum number of rows to return.", ge=1, le=10000)] = 100,
        offset: Annotated[int, Field(description="Optional row offset for pagination.", ge=0)] = 0,
        filters: Annotated[list[ReportFilter] | None, Field(description="Optional dimension filters.")] = None,
        order_bys: Annotated[list[ReportOrderBy] | None, Field(description="Optional ordering definitions.")] = None,
        keep_empty_rows: Annotated[bool, Field(description="Whether to keep rows with all metrics equal to zero.")] = False,
    ) -> dict:
        return await _run_with_context(
            mcp,
            services,
            "run_report",
            _run_report,
            start_date=start_date,
            end_date=end_date,
            metrics=metrics,
            dimensions=dimensions or [],
            row_limit=row_limit,
            offset=offset,
            filters=[filter_item.model_dump() for filter_item in (filters or [])],
            order_bys=[order_item.model_dump() for order_item in (order_bys or [])],
            keep_empty_rows=keep_empty_rows,
        )

    @mcp.tool(description="Run a GA4 realtime report for the active property.")
    async def run_realtime_report(
        metrics: Annotated[list[str], Field(description="Realtime GA4 metric API names.")]=["activeUsers"],
        dimensions: Annotated[list[str] | None, Field(description="Optional realtime dimension API names.")] = None,
        row_limit: Annotated[int, Field(description="Maximum number of rows to return.", ge=1, le=10000)] = 100,
        minutes_ago: Annotated[int | None, Field(description="Optional realtime lookback in minutes.", ge=1, le=60)] = None,
    ) -> dict:
        return await _run_with_context(
            mcp,
            services,
            "run_realtime_report",
            _run_realtime_report,
            metrics=metrics,
            dimensions=dimensions or [],
            row_limit=row_limit,
            minutes_ago=minutes_ago,
        )

    @mcp.tool(
        description="Return a high-level GA4 traffic overview for the active property over the selected trailing window."
    )
    async def get_traffic_overview(
        days: Annotated[int, Field(description="Trailing number of days to summarize.", ge=1, le=365)] = 28,
    ) -> dict:
        return await _run_with_context(
            mcp,
            services,
            "get_traffic_overview",
            _get_traffic_overview,
            days=days,
        )

    @mcp.tool(
        description="Return GA4 page performance for the active property, optionally filtered to a specific page path."
    )
    async def get_page_performance(
        page_path: Annotated[str | None, Field(description="Optional exact pagePath to analyze, for example '/pricing'.")] = None,
        days: Annotated[int, Field(description="Trailing number of days to summarize.", ge=1, le=365)] = 28,
        row_limit: Annotated[int, Field(description="Maximum number of page rows to return.", ge=1, le=1000)] = 25,
    ) -> dict:
        return await _run_with_context(
            mcp,
            services,
            "get_page_performance",
            _get_page_performance,
            page_path=page_path,
            days=days,
            row_limit=row_limit,
        )

    @mcp.tool(
        description="Compare two GA4 date ranges in a single Data API call for the active property."
    )
    async def compare_date_ranges(
        period1_start: Annotated[str, Field(description="Inclusive start date for the first range.")],
        period1_end: Annotated[str, Field(description="Inclusive end date for the first range.")],
        period2_start: Annotated[str, Field(description="Inclusive start date for the second range.")],
        period2_end: Annotated[str, Field(description="Inclusive end date for the second range.")],
        metrics: Annotated[list[str], Field(description="GA4 metric API names.")]=["sessions"],
        dimensions: Annotated[list[str] | None, Field(description="Optional GA4 dimension API names.")] = None,
        row_limit: Annotated[int, Field(description="Maximum number of rows to return.", ge=1, le=10000)] = 100,
    ) -> dict:
        return await _run_with_context(
            mcp,
            services,
            "compare_date_ranges",
            _compare_date_ranges,
            period1_start=period1_start,
            period1_end=period1_end,
            period2_start=period2_start,
            period2_end=period2_end,
            metrics=metrics,
            dimensions=dimensions or [],
            row_limit=row_limit,
        )


async def _run_with_context(mcp, services: ToolServices, tool_name: str, handler, **kwargs) -> dict:
    request_context = get_request_context(mcp)
    session = services.session_factory()
    try:
        context = services.policy_service.resolve_context_for_request(session, request_context)
        if not context.active_property_id:
            raise PermissionError("No active_property_id is set for the current request")
        result = await handler(services, context.active_property_id, **kwargs)
        services.audit_service.record(session, request_context, tool_name, result, resolved_context=context)
        return result
    except Exception as exc:
        services.audit_service.record(
            session,
            request_context,
            tool_name,
            build_failure_summary(exc, step=tool_name),
            status="error",
            resolved_context=request_context.operational_context,
        )
        raise
    finally:
        session.close()


async def _get_property_details(services: ToolServices, property_id: str) -> dict:
    details = await services.ga4_client.get_property(property_id)
    data_streams = await services.ga4_client.list_data_streams(property_id)
    measurement_ids = [
        str((stream.get("webStreamData") or {}).get("measurementId") or "").strip()
        for stream in data_streams.get("dataStreams", [])
        if str((stream.get("webStreamData") or {}).get("measurementId") or "").strip()
    ]
    default_uris = [
        str((stream.get("webStreamData") or {}).get("defaultUri") or "").strip()
        for stream in data_streams.get("dataStreams", [])
        if str((stream.get("webStreamData") or {}).get("defaultUri") or "").strip()
    ]
    return {
        "property_id": property_id,
        "property": details,
        "data_streams": data_streams.get("dataStreams", []),
        "measurement_ids": measurement_ids,
        "default_uris": default_uris,
    }


async def _get_reporting_metadata(services: ToolServices, property_id: str) -> dict:
    metadata = await services.ga4_client.get_reporting_metadata(property_id)
    return {"property_id": property_id, "metadata": metadata}


def _build_dimension_filter(filters: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not filters:
        return None

    expressions: list[dict[str, Any]] = []
    for filter_item in filters:
        field_name = str(filter_item["field_name"])
        match_type = str(filter_item["match_type"]).upper()
        if match_type == "IN_LIST":
            values = [str(value) for value in filter_item.get("values", []) if str(value).strip()]
            if not values:
                raise ValueError(f"IN_LIST filter for {field_name} requires non-empty values")
            expressions.append(
                {
                    "filter": {
                        "fieldName": field_name,
                        "inListFilter": {
                            "values": values,
                            "caseSensitive": False,
                        },
                    }
                }
            )
            continue

        value = str(filter_item.get("value") or "").strip()
        if not value:
            raise ValueError(f"Filter for {field_name} requires value")
        expressions.append(
            {
                "filter": {
                    "fieldName": field_name,
                    "stringFilter": {
                        "matchType": match_type,
                        "value": value,
                        "caseSensitive": False,
                    },
                }
            }
        )

    if len(expressions) == 1:
        return expressions[0]
    return {"andGroup": {"expressions": expressions}}


def _build_order_bys(order_bys: list[dict[str, Any]]) -> list[dict[str, Any]]:
    built: list[dict[str, Any]] = []
    for order_by in order_bys:
        field_name = str(order_by["field_name"])
        descending = bool(order_by.get("descending", True))
        order_type = str(order_by.get("order_type", "metric")).lower()
        if order_type == "dimension":
            built.append({"dimension": {"dimensionName": field_name}, "desc": descending})
        else:
            built.append({"metric": {"metricName": field_name}, "desc": descending})
    return built


async def _run_report(
    services: ToolServices,
    property_id: str,
    *,
    start_date: str,
    end_date: str,
    metrics: list[str],
    dimensions: list[str],
    row_limit: int,
    offset: int,
    filters: list[dict[str, Any]],
    order_bys: list[dict[str, Any]],
    keep_empty_rows: bool,
) -> dict:
    request: dict[str, Any] = {
        "dateRanges": [{"startDate": start_date, "endDate": end_date}],
        "metrics": [{"name": metric} for metric in metrics],
        "dimensions": [{"name": dimension} for dimension in dimensions],
        "limit": row_limit,
        "offset": offset,
        "keepEmptyRows": keep_empty_rows,
    }
    dimension_filter = _build_dimension_filter(filters)
    if dimension_filter:
        request["dimensionFilter"] = dimension_filter
    built_order_bys = _build_order_bys(order_bys)
    if built_order_bys:
        request["orderBys"] = built_order_bys
    response = await services.ga4_client.run_report(property_id, request)
    return {
        "property_id": property_id,
        "request": request,
        "report": response,
        "row_count": len(response.get("rows", [])),
    }


async def _run_realtime_report(
    services: ToolServices,
    property_id: str,
    *,
    metrics: list[str],
    dimensions: list[str],
    row_limit: int,
    minutes_ago: int | None,
) -> dict:
    request: dict[str, Any] = {
        "metrics": [{"name": metric} for metric in metrics],
        "dimensions": [{"name": dimension} for dimension in dimensions],
        "limit": row_limit,
    }
    if minutes_ago is not None:
        request["minuteRanges"] = [{"startMinutesAgo": minutes_ago, "endMinutesAgo": 0}]
    response = await services.ga4_client.run_realtime_report(property_id, request)
    return {
        "property_id": property_id,
        "request": request,
        "report": response,
        "row_count": len(response.get("rows", [])),
    }


async def _get_traffic_overview(services: ToolServices, property_id: str, *, days: int) -> dict:
    start_date = f"{days}daysAgo"
    summary_request = {
        "dateRanges": [{"startDate": start_date, "endDate": "today"}],
        "metrics": [{"name": metric} for metric in ["sessions", "totalUsers", "newUsers", "engagedSessions", "engagementRate", "screenPageViews"]],
    }
    channels_request = {
        "dateRanges": [{"startDate": start_date, "endDate": "today"}],
        "metrics": [{"name": metric} for metric in ["sessions", "totalUsers", "engagedSessions"]],
        "dimensions": [{"name": "sessionDefaultChannelGroup"}],
        "limit": 10,
        "orderBys": [{"metric": {"metricName": "sessions"}, "desc": True}],
    }
    summary = await services.ga4_client.run_report(property_id, summary_request)
    top_channels = await services.ga4_client.run_report(property_id, channels_request)
    return {
        "property_id": property_id,
        "days": days,
        "summary": summary,
        "top_channels": top_channels,
    }


async def _get_page_performance(
    services: ToolServices,
    property_id: str,
    *,
    page_path: str | None,
    days: int,
    row_limit: int,
) -> dict:
    filters = []
    if page_path:
        filters.append({"field_name": "pagePath", "match_type": "EXACT", "value": page_path, "values": []})
    request = {
        "dateRanges": [{"startDate": f"{days}daysAgo", "endDate": "today"}],
        "metrics": [{"name": metric} for metric in ["screenPageViews", "sessions", "activeUsers", "engagementRate"]],
        "dimensions": [{"name": "pagePath"}, {"name": "pageTitle"}],
        "limit": row_limit,
        "orderBys": [{"metric": {"metricName": "screenPageViews"}, "desc": True}],
    }
    dimension_filter = _build_dimension_filter(filters)
    if dimension_filter:
        request["dimensionFilter"] = dimension_filter
    response = await services.ga4_client.run_report(property_id, request)
    return {
        "property_id": property_id,
        "days": days,
        "page_path": page_path,
        "report": response,
        "row_count": len(response.get("rows", [])),
    }


async def _compare_date_ranges(
    services: ToolServices,
    property_id: str,
    *,
    period1_start: str,
    period1_end: str,
    period2_start: str,
    period2_end: str,
    metrics: list[str],
    dimensions: list[str],
    row_limit: int,
) -> dict:
    request = {
        "dateRanges": [
            {"startDate": period1_start, "endDate": period1_end, "name": "period_1"},
            {"startDate": period2_start, "endDate": period2_end, "name": "period_2"},
        ],
        "metrics": [{"name": metric} for metric in metrics],
        "dimensions": [{"name": dimension} for dimension in dimensions],
        "limit": row_limit,
    }
    response = await services.ga4_client.run_report(property_id, request)
    return {
        "property_id": property_id,
        "request": request,
        "comparison": response,
        "row_count": len(response.get("rows", [])),
    }
