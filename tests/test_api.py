from __future__ import annotations

from fastapi.testclient import TestClient

from api.main import app, get_repository
from api.repositories import (
    BigQueryQuotaError,
    CachedFallbackRepository,
    FileServingRepository,
    SampleServingRepository,
)
from api.schemas import BottleneckResponse, FeedHealthResponse, NetworkResponse, SegmentRiskResponse
from pipeline.ml import write_segment_risk_serving_outputs
from pipeline.runner import run_local, write_local_serving_output
from tests.fixtures import build_trip_updates_payload, write_static_feed


def test_current_network_returns_sample_data():
    app.dependency_overrides[get_repository] = lambda: SampleServingRepository()
    try:
        response = TestClient(app).get("/api/v1/network/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["edges"]


def test_quota_error_returns_clear_503_when_no_cache_available():
    class FailingRepository:
        def current_network(self):
            raise BigQueryQuotaError("quota exceeded")

        def current_bottlenecks(self, limit: int):
            raise BigQueryQuotaError("quota exceeded")

        def current_feed_health(self):
            raise BigQueryQuotaError("quota exceeded")

        def segment_risk(self, route_id=None):
            raise BigQueryQuotaError("quota exceeded")

    app.dependency_overrides[get_repository] = lambda: FailingRepository()
    try:
        response = TestClient(app).get("/api/v1/network/current")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "degraded"
    assert response.json()["detail"]["data_stale"] is True


def test_segment_risk_quota_error_returns_clear_503_when_no_cache_available():
    class FailingRepository:
        def current_network(self):
            raise BigQueryQuotaError("quota exceeded")

        def current_bottlenecks(self, limit: int):
            raise BigQueryQuotaError("quota exceeded")

        def current_feed_health(self):
            raise BigQueryQuotaError("quota exceeded")

        def segment_risk(self, route_id=None):
            raise BigQueryQuotaError("quota exceeded")

    app.dependency_overrides[get_repository] = lambda: FailingRepository()
    try:
        response = TestClient(app).get("/api/v1/predictions/segment-risk?route_id=R")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert response.json()["detail"]["status"] == "degraded"
    assert response.json()["detail"]["data_stale"] is True


def test_cached_segment_risk_returns_stale_response_after_quota_error():
    class FlakyRepository:
        def __init__(self):
            self.calls = 0

        def current_network(self):
            return NetworkResponse()

        def current_bottlenecks(self, limit: int):
            return BottleneckResponse()

        def current_feed_health(self):
            return FeedHealthResponse(status="ok")

        def segment_risk(self, route_id=None):
            self.calls += 1
            if self.calls > 1:
                raise BigQueryQuotaError("quota exceeded")
            return SegmentRiskResponse(
                route_id=route_id,
                predictions=[{"route_id": route_id, "risk_probability": 0.8}],
                metrics={"roc_auc": 0.9, "baseline_roc_auc": 0.7},
            )

    repository = CachedFallbackRepository(FlakyRepository())

    fresh = repository.segment_risk("R")
    stale = repository.segment_risk("R")

    assert fresh.status == "ok"
    assert stale.status == "degraded"
    assert stale.data_stale is True
    assert stale.predictions == fresh.predictions


def test_api_reads_local_serving_outputs(tmp_path):
    static_zip = tmp_path / "mbta_static_sample.zip"
    serving_dir = tmp_path / "serving"
    write_static_feed(static_zip)
    output = run_local(str(static_zip), build_trip_updates_payload())
    write_local_serving_output(output, str(serving_dir))
    write_segment_risk_serving_outputs(output.current_network, str(serving_dir))

    app.dependency_overrides[get_repository] = lambda: FileServingRepository(str(serving_dir))
    try:
        client = TestClient(app)
        network = client.get("/api/v1/network/current")
        bottlenecks = client.get("/api/v1/network/bottlenecks?limit=1")
        risks = client.get("/api/v1/predictions/segment-risk?route_id=R")
    finally:
        app.dependency_overrides.clear()

    assert network.status_code == 200
    assert network.json()["edges"]
    assert bottlenecks.status_code == 200
    assert len(bottlenecks.json()["bottlenecks"]) == 1
    assert risks.status_code == 200
    assert risks.json()["predictions"]
    assert risks.json()["metrics"]["roc_auc"] > risks.json()["metrics"]["baseline_roc_auc"]
