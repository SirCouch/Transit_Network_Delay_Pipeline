from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"


class FeedHealthResponse(BaseModel):
    status: str
    data_stale: bool = False
    last_successful_update: datetime | None = None
    message: str | None = None


class NetworkResponse(BaseModel):
    status: str = "ok"
    data_stale: bool = False
    last_successful_update: datetime | None = None
    edges: list[dict[str, Any]] = Field(default_factory=list)
    message: str | None = None


class BottleneckResponse(BaseModel):
    status: str = "ok"
    data_stale: bool = False
    last_successful_update: datetime | None = None
    bottlenecks: list[dict[str, Any]] = Field(default_factory=list)
    message: str | None = None


class SegmentRiskResponse(BaseModel):
    status: str = "ok"
    data_stale: bool = False
    last_successful_update: datetime | None = None
    route_id: str | None = None
    predictions: list[dict[str, Any]] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    message: str | None = None


def sample_timestamp() -> datetime:
    return datetime(2026, 5, 12, 18, 45, tzinfo=timezone.utc)
