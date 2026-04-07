from __future__ import annotations

import asyncio

import httpx
import pytest

from app.core.ga4_client import GA4ApiError, GA4Client


class FakeResponse:
    def __init__(self, *, status_code: int, payload: dict):
        self.status_code = status_code
        self._payload = payload
        self.text = str(payload)
        self.request = httpx.Request("GET", "https://example.com")

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("boom", request=self.request, response=self)

    def json(self) -> dict:
        return self._payload


class FakeAsyncClient:
    def __init__(self, responses):
        self._responses = responses

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url, data=None):
        return self._responses.pop(0)

    async def request(self, method, url, headers=None, json=None):
        return self._responses.pop(0)


def test_ga4_client_refreshes_and_queries(settings, monkeypatch):
    responses = [
        FakeResponse(status_code=200, payload={"access_token": "token-123", "expires_in": 3600}),
        FakeResponse(status_code=200, payload={"accountSummaries": [{"name": "accounts/1/accountSummaries/1"}]}),
    ]
    monkeypatch.setattr(
        "app.core.ga4_client.httpx.AsyncClient",
        lambda timeout=30.0: FakeAsyncClient(responses),
    )
    client = GA4Client(settings)
    result = asyncio.run(client.list_account_summaries())
    assert result["accountSummaries"][0]["name"] == "accounts/1/accountSummaries/1"


def test_ga4_client_wraps_http_errors(settings, monkeypatch):
    responses = [
        FakeResponse(status_code=200, payload={"access_token": "token-123", "expires_in": 3600}),
        FakeResponse(status_code=403, payload={"error": {"message": "forbidden"}}),
    ]
    monkeypatch.setattr(
        "app.core.ga4_client.httpx.AsyncClient",
        lambda timeout=30.0: FakeAsyncClient(responses),
    )
    client = GA4Client(settings)
    with pytest.raises(GA4ApiError) as exc_info:
        asyncio.run(client.list_account_summaries())
    assert exc_info.value.status_code == 403
    assert exc_info.value.error_type == "http_error"
