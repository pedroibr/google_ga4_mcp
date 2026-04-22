from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import json
from typing import Any

import httpx

from app.config import Settings


@dataclass(slots=True)
class OAuthToken:
    access_token: str
    expires_at: datetime


@dataclass(slots=True)
class GA4Credentials:
    client_id: str
    client_secret: str
    refresh_token: str


class GA4ApiError(RuntimeError):
    def __init__(
        self,
        *,
        operation: str,
        method: str,
        url: str,
        message: str,
        error_type: str,
        status_code: int | None = None,
        response_body: str | None = None,
    ) -> None:
        super().__init__(message)
        self.operation = operation
        self.method = method
        self.url = url
        self.message = message
        self.error_type = error_type
        self.status_code = status_code
        self.response_body = response_body

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "error_type": self.error_type,
            "operation": self.operation,
            "method": self.method,
            "url": self.url,
            "message": self.message,
            "status_code": self.status_code,
        }
        if self.response_body:
            payload["response_body"] = self.response_body
        return payload


class GA4Client:
    DATA_API_BASE_URL = "https://analyticsdata.googleapis.com/v1beta"
    ADMIN_API_BASE_URL = "https://analyticsadmin.googleapis.com/v1beta"
    TOKEN_URL = "https://oauth2.googleapis.com/token"

    def __init__(self, settings: Settings, credentials: GA4Credentials | None = None):
        self._settings = settings
        self._credentials = credentials
        self._token: OAuthToken | None = None

    async def list_account_summaries(self) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.ADMIN_API_BASE_URL}/accountSummaries",
            operation="list_account_summaries",
        )

    async def get_property(self, property_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.ADMIN_API_BASE_URL}/properties/{property_id}",
            operation="get_property",
        )

    async def get_reporting_metadata(self, property_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.DATA_API_BASE_URL}/properties/{property_id}/metadata",
            operation="get_reporting_metadata",
        )

    async def list_data_streams(self, property_id: str) -> dict[str, Any]:
        return await self._request_json(
            "GET",
            f"{self.ADMIN_API_BASE_URL}/properties/{property_id}/dataStreams",
            operation="list_data_streams",
        )

    async def run_report(self, property_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"{self.DATA_API_BASE_URL}/properties/{property_id}:runReport",
            operation="run_report",
            json_body=request,
        )

    async def run_realtime_report(self, property_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return await self._request_json(
            "POST",
            f"{self.DATA_API_BASE_URL}/properties/{property_id}:runRealtimeReport",
            operation="run_realtime_report",
            json_body=request,
        )

    async def _request_json(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        headers = {
            "authorization": f"Bearer {await self._get_access_token()}",
            "accept": "application/json",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.request(method, url, headers=headers, json=json_body)
                response.raise_for_status()
                return response.json()
            except httpx.HTTPStatusError as exc:
                raise self._build_http_error(exc.response, method=method, url=url, operation=operation) from exc
            except httpx.TimeoutException as exc:
                raise GA4ApiError(
                    operation=operation,
                    method=method,
                    url=url,
                    message=f"Google Analytics request timed out during {operation}",
                    error_type="timeout",
                ) from exc
            except httpx.HTTPError as exc:
                raise GA4ApiError(
                    operation=operation,
                    method=method,
                    url=url,
                    message=f"Google Analytics request failed during {operation}: {exc.__class__.__name__}",
                    error_type="network_error",
                ) from exc
            except ValueError as exc:
                raise GA4ApiError(
                    operation=operation,
                    method=method,
                    url=url,
                    message=f"Google Analytics returned invalid JSON during {operation}",
                    error_type="invalid_response",
                ) from exc

    async def _get_access_token(self) -> str:
        if self._token is not None and self._token.expires_at > datetime.now(timezone.utc) + timedelta(minutes=1):
            return self._token.access_token

        credentials = self._credentials or GA4Credentials(
            client_id=self._settings.google_oauth_client_id,
            client_secret=self._settings.google_oauth_client_secret,
            refresh_token=self._settings.google_oauth_refresh_token,
        )
        required = (credentials.client_id, credentials.client_secret, credentials.refresh_token)
        if any(not item.strip() for item in required):
            raise GA4ApiError(
                operation="refresh_access_token",
                method="POST",
                url=self.TOKEN_URL,
                message="Missing Google OAuth credentials",
                error_type="configuration_error",
            )

        payload = {
            "client_id": credentials.client_id,
            "client_secret": credentials.client_secret,
            "refresh_token": credentials.refresh_token,
            "grant_type": "refresh_token",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            try:
                response = await client.post(self.TOKEN_URL, data=payload)
                response.raise_for_status()
                data = response.json()
            except httpx.HTTPStatusError as exc:
                raise self._build_http_error(
                    exc.response,
                    method="POST",
                    url=self.TOKEN_URL,
                    operation="refresh_access_token",
                ) from exc
            except httpx.HTTPError as exc:
                raise GA4ApiError(
                    operation="refresh_access_token",
                    method="POST",
                    url=self.TOKEN_URL,
                    message=f"Failed to refresh Google OAuth token: {exc.__class__.__name__}",
                    error_type="network_error",
                ) from exc

        access_token = str(data.get("access_token", "")).strip()
        expires_in = int(data.get("expires_in", 3600))
        if not access_token:
            raise GA4ApiError(
                operation="refresh_access_token",
                method="POST",
                url=self.TOKEN_URL,
                message="Google OAuth token refresh succeeded without returning access_token",
                error_type="invalid_response",
                response_body=json.dumps(data),
            )
        self._token = OAuthToken(
            access_token=access_token,
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )
        return access_token

    def _build_http_error(
        self,
        response: httpx.Response,
        *,
        method: str,
        url: str,
        operation: str,
    ) -> GA4ApiError:
        try:
            payload = response.json()
            response_body = json.dumps(payload)
            error = payload.get("error", {})
            message = error.get("message") if isinstance(error, dict) else None
        except ValueError:
            response_body = response.text or None
            message = None

        return GA4ApiError(
            operation=operation,
            method=method,
            url=url,
            message=message or f"Google Analytics request failed during {operation}",
            error_type="http_error",
            status_code=response.status_code,
            response_body=response_body,
        )
