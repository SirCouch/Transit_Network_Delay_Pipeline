from __future__ import annotations

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class ApiSettings:
    project_id: str
    serving_dataset: str
    max_bytes_billed: int
    use_sample_data: bool
    local_serving_dir: str | None
    rate_limit_enabled: bool
    rate_limit_requests: int
    rate_limit_window_seconds: int
    response_cache_ttl_seconds: int

    @classmethod
    def from_env(cls) -> "ApiSettings":
        return cls(
            project_id=os.getenv("GCP_PROJECT_ID", ""),
            serving_dataset=os.getenv("GTFS_SERVING_DATASET", "gtfs_serving"),
            max_bytes_billed=int(os.getenv("BIGQUERY_MAX_BYTES_BILLED", "104857600")),
            use_sample_data=os.getenv("API_USE_SAMPLE_DATA", "false").lower() == "true",
            local_serving_dir=os.getenv("LOCAL_SERVING_DIR"),
            rate_limit_enabled=os.getenv("API_RATE_LIMIT_ENABLED", "true").lower() == "true",
            rate_limit_requests=int(os.getenv("API_RATE_LIMIT_REQUESTS", "120")),
            rate_limit_window_seconds=int(os.getenv("API_RATE_LIMIT_WINDOW_SECONDS", "60")),
            response_cache_ttl_seconds=int(os.getenv("API_RESPONSE_CACHE_TTL_SECONDS", "30")),
        )
