from __future__ import annotations

import logging
from dataclasses import dataclass
import json
from pathlib import Path

from pipeline.config import PipelineSettings
from pipeline.gtfs_rt import parse_trip_updates
from pipeline.gtfs_static import parse_static_feed
from pipeline.http import fetch_bytes
from pipeline.serving import (
    build_current_bottleneck_rows,
    build_current_network_rows,
    build_feed_health_row,
)
from pipeline.storage import trip_update_snapshot_name, upload_bytes
from pipeline.transforms import build_static_edges, compute_edge_delay_state, rank_bottlenecks


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalPipelineOutput:
    current_network: list[dict[str, object]]
    current_bottlenecks: list[dict[str, object]]
    current_feed_health: dict[str, object]


def run_local(static_zip_path: str, trip_updates_payload: bytes) -> LocalPipelineOutput:
    stops, _routes, trips, stop_times = parse_static_feed(static_zip_path)
    static_edges = build_static_edges(stop_times, trips)
    stop_updates = parse_trip_updates(trip_updates_payload)
    edge_states = compute_edge_delay_state(static_edges, stop_updates)
    bottlenecks = rank_bottlenecks(edge_states)
    return LocalPipelineOutput(
        current_network=build_current_network_rows(edge_states, static_edges, stops),
        current_bottlenecks=build_current_bottleneck_rows(bottlenecks),
        current_feed_health=build_feed_health_row(edge_states),
    )


def write_local_serving_output(output: LocalPipelineOutput, output_dir: str) -> None:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "current_network.json").write_text(
        json.dumps(output.current_network, indent=2),
        encoding="utf-8",
    )
    (target / "current_bottlenecks.json").write_text(
        json.dumps(output.current_bottlenecks, indent=2),
        encoding="utf-8",
    )
    (target / "current_feed_health.json").write_text(
        json.dumps(output.current_feed_health, indent=2),
        encoding="utf-8",
    )


def run_once(settings: PipelineSettings | None = None) -> None:
    settings = settings or PipelineSettings.from_env()
    logger.info("Starting MBTA ingest run in %s mode", settings.refresh_mode)

    trip_updates_payload = fetch_bytes(settings.mbta_trip_updates_url)
    stop_updates = parse_trip_updates(trip_updates_payload)
    feed_timestamp = stop_updates[0].feed_timestamp if stop_updates else None

    if settings.raw_bucket_name:
        snapshot_uri = upload_bytes(
            settings.raw_bucket_name,
            trip_update_snapshot_name(feed_timestamp),
            trip_updates_payload,
        )
        logger.info("Saved TripUpdates snapshot to %s", snapshot_uri)

    logger.info("Parsed %s stop updates", len(stop_updates))
    logger.warning("BigQuery write path is scaffolded but not wired into run_once yet")


if __name__ == "__main__":
    run_once()
