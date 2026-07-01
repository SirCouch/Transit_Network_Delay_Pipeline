from __future__ import annotations

from dataclasses import dataclass
import os


DEFAULT_MBTA_STATIC_URL = "https://cdn.mbta.com/MBTA_GTFS.zip"
DEFAULT_MBTA_TRIP_UPDATES_URL = "https://cdn.mbta.com/realtime/TripUpdates.pb"
TRANSIT_TIMEZONE = "America/New_York"


def _env_or_default(name: str, default: str) -> str:
    return os.getenv(name) or default


@dataclass(frozen=True)
class PipelineSettings:
    project_id: str
    raw_bucket_name: str | None
    mbta_static_url: str
    mbta_trip_updates_url: str
    refresh_mode: str
    static_dataset: str
    graph_dataset: str
    rt_dataset: str
    analytics_dataset: str
    serving_dataset: str
    monitoring_dataset: str

    @classmethod
    def from_env(cls) -> "PipelineSettings":
        return cls(
            project_id=os.getenv("GCP_PROJECT_ID", ""),
            raw_bucket_name=os.getenv("RAW_BUCKET_NAME"),
            mbta_static_url=_env_or_default("MBTA_STATIC_URL", DEFAULT_MBTA_STATIC_URL),
            mbta_trip_updates_url=_env_or_default(
                "MBTA_TRIP_UPDATES_URL", DEFAULT_MBTA_TRIP_UPDATES_URL
            ),
            refresh_mode=os.getenv("REFRESH_MODE", "cost_safe"),
            static_dataset=os.getenv("GTFS_STATIC_DATASET", "gtfs_static"),
            graph_dataset=os.getenv("GTFS_GRAPH_DATASET", "gtfs_graph"),
            rt_dataset=os.getenv("GTFS_RT_DATASET", "gtfs_rt"),
            analytics_dataset=os.getenv("GTFS_ANALYTICS_DATASET", "gtfs_analytics"),
            serving_dataset=os.getenv("GTFS_SERVING_DATASET", "gtfs_serving"),
            monitoring_dataset=os.getenv("GTFS_MONITORING_DATASET", "gtfs_monitoring"),
        )
