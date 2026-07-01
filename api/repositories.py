from __future__ import annotations

import json
from pathlib import Path
import threading
import time
from typing import Any, Protocol

from google.api_core.exceptions import Forbidden, ResourceExhausted, TooManyRequests

from api.config import ApiSettings
from api.schemas import (
    BottleneckResponse,
    FeedHealthResponse,
    NetworkResponse,
    SegmentRiskResponse,
    sample_timestamp,
)


class ServingRepository(Protocol):
    def current_network(self) -> NetworkResponse:
        ...

    def current_bottlenecks(self, limit: int) -> BottleneckResponse:
        ...

    def current_feed_health(self) -> FeedHealthResponse:
        ...

    def segment_risk(self, route_id: str | None = None) -> SegmentRiskResponse:
        ...


class BigQueryQuotaError(RuntimeError):
    pass


class BigQueryServingRepository:
    def __init__(self, settings: ApiSettings):
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise RuntimeError("google-cloud-bigquery is required for BigQuery reads") from exc
        self._bigquery = bigquery
        self._client = bigquery.Client(project=settings.project_id or None)
        self._project_id = settings.project_id
        self._dataset = settings.serving_dataset
        self._max_bytes_billed = settings.max_bytes_billed
        self._cache_ttl_seconds = max(0, settings.response_cache_ttl_seconds)
        self._query_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}
        self._cache_lock = threading.Lock()

    def current_network(self) -> NetworkResponse:
        rows = self._query(
            f"""
            SELECT *
            FROM `{self._project_id}.{self._dataset}.current_network`
            ORDER BY route_id, trip_id, edge_id
            LIMIT 10000
            """
        )
        health = self.current_feed_health()
        return NetworkResponse(
            status=health.status,
            data_stale=health.data_stale,
            last_successful_update=health.last_successful_update,
            edges=rows,
            message=health.message,
        )

    def current_bottlenecks(self, limit: int) -> BottleneckResponse:
        rows = self._query(
            f"""
            SELECT *
            FROM `{self._project_id}.{self._dataset}.current_bottlenecks`
            ORDER BY rank, bottleneck_score DESC
            LIMIT @limit
            """,
            parameters=[
                self._bigquery.ScalarQueryParameter("limit", "INT64", limit),
            ],
        )
        health = self.current_feed_health()
        return BottleneckResponse(
            status=health.status,
            data_stale=health.data_stale,
            last_successful_update=health.last_successful_update,
            bottlenecks=rows,
            message=health.message,
        )

    def current_feed_health(self) -> FeedHealthResponse:
        rows = self._query(
            f"""
            SELECT status, data_stale, last_successful_update, message
            FROM `{self._project_id}.{self._dataset}.current_feed_health`
            ORDER BY generated_at DESC
            LIMIT 1
            """
        )
        if not rows:
            return FeedHealthResponse(
                status="degraded",
                data_stale=True,
                message="No feed health row is available yet.",
            )
        return FeedHealthResponse(**rows[0])

    def segment_risk(self, route_id: str | None = None) -> SegmentRiskResponse:
        where_clause = "WHERE route_id = @route_id" if route_id else ""
        parameters = (
            [self._bigquery.ScalarQueryParameter("route_id", "STRING", route_id)]
            if route_id
            else []
        )
        rows = self._query(
            f"""
            SELECT *
            FROM `{self._project_id}.{self._dataset}.segment_risk`
            {where_clause}
            ORDER BY risk_probability DESC
            LIMIT 10000
            """,
            parameters=parameters,
        )
        health = self.current_feed_health()
        return SegmentRiskResponse(
            status=health.status,
            data_stale=health.data_stale,
            last_successful_update=health.last_successful_update,
            route_id=route_id,
            predictions=rows,
            metrics={},
            message=health.message,
        )

    def _query(
        self,
        sql: str,
        parameters: list[Any] | None = None,
    ) -> list[dict[str, Any]]:
        config = self._bigquery.QueryJobConfig(
            maximum_bytes_billed=self._max_bytes_billed,
            query_parameters=parameters or [],
        )
        try:
            cache_key = _query_cache_key(sql, parameters)
            cached = self._cached_query(cache_key)
            if cached is not None:
                return cached

            result = self._client.query(sql, job_config=config).result()
            rows = [dict(row.items()) for row in result]
            self._store_cached_query(cache_key, rows)
            return rows
        except (Forbidden, ResourceExhausted, TooManyRequests) as exc:
            raise BigQueryQuotaError(str(exc)) from exc

    def _cached_query(self, cache_key: str) -> list[dict[str, Any]] | None:
        if self._cache_ttl_seconds <= 0:
            return None
        now = time.monotonic()
        with self._cache_lock:
            cached = self._query_cache.get(cache_key)
            if not cached:
                return None
            stored_at, rows = cached
            if now - stored_at > self._cache_ttl_seconds:
                self._query_cache.pop(cache_key, None)
                return None
            return [dict(row) for row in rows]

    def _store_cached_query(self, cache_key: str, rows: list[dict[str, Any]]) -> None:
        if self._cache_ttl_seconds <= 0:
            return
        with self._cache_lock:
            self._query_cache[cache_key] = (time.monotonic(), [dict(row) for row in rows])


class SampleServingRepository:
    def current_network(self) -> NetworkResponse:
        timestamp = sample_timestamp()
        return NetworkResponse(
            last_successful_update=timestamp,
            edges=[
                {
                    "route_id": "Red",
                    "trip_id": "sample-trip",
                    "edge_id": "sample-trip:1:2",
                    "src_stop_id": "place-sstat",
                    "dst_stop_id": "place-dwnxg",
                    "edge_delay_seconds": 180,
                    "is_delayed": True,
                }
            ],
        )

    def current_bottlenecks(self, limit: int) -> BottleneckResponse:
        timestamp = sample_timestamp()
        return BottleneckResponse(
            last_successful_update=timestamp,
            bottlenecks=[
                {
                    "rank": 1,
                    "route_id": "Red",
                    "edge_id": "sample-trip:1:2",
                    "affected_downstream_stops": 3,
                    "avg_delay_seconds": 180.0,
                    "bottleneck_score": 540.0,
                }
            ][:limit],
        )

    def current_feed_health(self) -> FeedHealthResponse:
        return FeedHealthResponse(
            status="ok",
            data_stale=False,
            last_successful_update=sample_timestamp(),
            message="Serving sample data.",
        )

    def segment_risk(self, route_id: str | None = None) -> SegmentRiskResponse:
        timestamp = sample_timestamp()
        return SegmentRiskResponse(
            last_successful_update=timestamp,
            route_id=route_id,
            predictions=[
                {
                    "route_id": route_id or "Red",
                    "edge_id": "sample-trip:1:2",
                    "risk_probability": 0.82,
                    "risk_label": "high",
                    "current_delay_seconds": 180,
                    "threshold_seconds": 180,
                }
            ],
            metrics={"roc_auc": 0.91, "baseline_roc_auc": 0.71},
        )


class FileServingRepository:
    def __init__(self, serving_dir: str):
        self._serving_dir = Path(serving_dir)

    def current_network(self) -> NetworkResponse:
        rows = self._read_json("current_network.json", default=[])
        health = self.current_feed_health()
        return NetworkResponse(
            status=health.status,
            data_stale=health.data_stale,
            last_successful_update=health.last_successful_update,
            edges=rows,
            message=health.message,
        )

    def current_bottlenecks(self, limit: int) -> BottleneckResponse:
        rows = self._read_json("current_bottlenecks.json", default=[])
        health = self.current_feed_health()
        return BottleneckResponse(
            status=health.status,
            data_stale=health.data_stale,
            last_successful_update=health.last_successful_update,
            bottlenecks=rows[:limit],
            message=health.message,
        )

    def current_feed_health(self) -> FeedHealthResponse:
        row = self._read_json("current_feed_health.json", default=None)
        if not row:
            return FeedHealthResponse(
                status="degraded",
                data_stale=True,
                message="No local feed health file is available yet.",
            )
        return FeedHealthResponse(**row)

    def segment_risk(self, route_id: str | None = None) -> SegmentRiskResponse:
        rows = self._read_json("segment_risk.json", default=[])
        metrics = self._read_json("model_metrics.json", default={})
        if route_id:
            rows = [row for row in rows if row.get("route_id") == route_id]
        health = self.current_feed_health()
        return SegmentRiskResponse(
            status=health.status,
            data_stale=health.data_stale,
            last_successful_update=health.last_successful_update,
            route_id=route_id,
            predictions=rows,
            metrics=metrics,
            message=health.message,
        )

    def _read_json(self, name: str, default: Any) -> Any:
        path = self._serving_dir / name
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8"))


class CachedFallbackRepository:
    def __init__(self, primary: ServingRepository):
        self._primary = primary
        self._last_network: NetworkResponse | None = None
        self._last_bottlenecks: BottleneckResponse | None = None
        self._last_segment_risk: dict[str | None, SegmentRiskResponse] = {}

    def current_network(self) -> NetworkResponse:
        try:
            response = self._primary.current_network()
            self._last_network = response
            return response
        except BigQueryQuotaError:
            if self._last_network:
                return _stale_network(self._last_network)
            raise

    def current_bottlenecks(self, limit: int) -> BottleneckResponse:
        try:
            response = self._primary.current_bottlenecks(limit)
            self._last_bottlenecks = response
            return response
        except BigQueryQuotaError:
            if self._last_bottlenecks:
                return _stale_bottlenecks(self._last_bottlenecks, limit)
            raise

    def current_feed_health(self) -> FeedHealthResponse:
        return self._primary.current_feed_health()

    def segment_risk(self, route_id: str | None = None) -> SegmentRiskResponse:
        try:
            response = self._primary.segment_risk(route_id)
            self._last_segment_risk[route_id] = response
            return response
        except BigQueryQuotaError:
            if route_id in self._last_segment_risk:
                return _stale_segment_risk(self._last_segment_risk[route_id])
            raise


def build_repository(settings: ApiSettings) -> ServingRepository:
    if settings.local_serving_dir:
        return FileServingRepository(settings.local_serving_dir)
    if settings.use_sample_data or not settings.project_id:
        return SampleServingRepository()
    return CachedFallbackRepository(BigQueryServingRepository(settings))


def _query_cache_key(sql: str, parameters: list[Any] | None) -> str:
    parameter_key = "|".join(repr(parameter) for parameter in parameters or [])
    return f"{sql.strip()}::{parameter_key}"


def _stale_network(response: NetworkResponse) -> NetworkResponse:
    return response.model_copy(
        update={
            "status": "degraded",
            "data_stale": True,
            "message": "Daily BigQuery quota exhausted; returning last cached network state.",
        }
    )


def _stale_bottlenecks(response: BottleneckResponse, limit: int) -> BottleneckResponse:
    return response.model_copy(
        update={
            "status": "degraded",
            "data_stale": True,
            "bottlenecks": response.bottlenecks[:limit],
            "message": "Daily BigQuery quota exhausted; returning last cached bottleneck state.",
        }
    )


def _stale_segment_risk(response: SegmentRiskResponse) -> SegmentRiskResponse:
    return response.model_copy(
        update={
            "status": "degraded",
            "data_stale": True,
            "message": "Daily BigQuery quota exhausted; returning last cached segment risk state.",
        }
    )
