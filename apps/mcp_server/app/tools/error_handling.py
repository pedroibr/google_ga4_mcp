from __future__ import annotations

from app.core.ga4_client import GA4ApiError


def build_failure_summary(exc: Exception, *, step: str) -> dict[str, object]:
    if isinstance(exc, GA4ApiError):
        payload = exc.to_dict()
        payload["step"] = step
        return payload
    return {
        "error_type": exc.__class__.__name__,
        "message": str(exc),
        "step": step,
    }
