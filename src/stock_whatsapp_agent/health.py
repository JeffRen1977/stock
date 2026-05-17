from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class ProviderHealthRecord:
    provider_name: str
    operation: str
    success: bool
    error: str | None
    latency_ms: int
    created_at: str
    stale: bool = False


def make_provider_health_record(
    provider_name: str,
    operation: str,
    success: bool,
    error: str | None,
    latency_ms: int,
    stale: bool = False,
) -> ProviderHealthRecord:
    return ProviderHealthRecord(
        provider_name=provider_name,
        operation=operation,
        success=success,
        error=error,
        latency_ms=latency_ms,
        created_at=datetime.utcnow().isoformat(timespec="seconds") + "Z",
        stale=stale,
    )
