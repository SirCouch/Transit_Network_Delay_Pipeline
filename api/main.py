from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse

from api.config import ApiSettings
from api.rate_limit import FixedWindowRateLimiter, client_identifier
from api.repositories import BigQueryQuotaError, ServingRepository, build_repository
from api.schemas import BottleneckResponse, HealthResponse, NetworkResponse, SegmentRiskResponse


app = FastAPI(title="Transit Network Delay API", version="0.1.0")
_settings = ApiSettings.from_env()
_repository = build_repository(_settings)
_rate_limiter = FixedWindowRateLimiter(
    max_requests=_settings.rate_limit_requests,
    window_seconds=_settings.rate_limit_window_seconds,
)
_rate_limit_exempt_paths = {"/health", "/api/v1/health"}


def get_repository() -> ServingRepository:
    return _repository


@app.middleware("http")
async def rate_limit_requests(request: Request, call_next):
    if _settings.rate_limit_enabled and request.url.path not in _rate_limit_exempt_paths:
        decision = _rate_limiter.check(client_identifier(request))
        headers = {
            "X-RateLimit-Limit": str(_settings.rate_limit_requests),
            "X-RateLimit-Remaining": str(decision.remaining),
            "X-RateLimit-Reset": str(decision.reset_seconds),
        }
        if not decision.allowed:
            headers["Retry-After"] = str(decision.reset_seconds)
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={
                    "status": "degraded",
                    "data_stale": True,
                    "message": "API rate limit exceeded. Retry after the window resets.",
                },
                headers=headers,
            )

        response = await call_next(request)
        response.headers.update(headers)
        return response

    return await call_next(request)


@app.get("/api/v1/health", response_model=HealthResponse)
@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse()


@app.get("/api/v1/network/current", response_model=NetworkResponse)
def current_network(repository: ServingRepository = Depends(get_repository)) -> NetworkResponse:
    try:
        return repository.current_network()
    except BigQueryQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "data_stale": True,
                "message": "Daily BigQuery quota exhausted; no cached network state is available.",
            },
        ) from exc


@app.get("/api/v1/network/bottlenecks", response_model=BottleneckResponse)
def current_bottlenecks(
    limit: int = Query(default=5, ge=1, le=50),
    repository: ServingRepository = Depends(get_repository),
) -> BottleneckResponse:
    try:
        return repository.current_bottlenecks(limit)
    except BigQueryQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "data_stale": True,
                "message": "Daily BigQuery quota exhausted; no cached bottleneck state is available.",
            },
        ) from exc


@app.get("/api/v1/predictions/segment-risk", response_model=SegmentRiskResponse)
def segment_risk(
    route_id: str | None = Query(default=None),
    repository: ServingRepository = Depends(get_repository),
) -> SegmentRiskResponse:
    try:
        return repository.segment_risk(route_id)
    except BigQueryQuotaError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "status": "degraded",
                "data_stale": True,
                "message": "Daily BigQuery quota exhausted; no segment risk predictions are available.",
            },
        ) from exc
