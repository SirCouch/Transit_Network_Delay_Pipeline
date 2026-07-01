from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from pipeline.backfill import build_segment_training_frame, decode_snapshot_file, write_frame
from pipeline.ml import train_segment_risk_from_file
from pipeline.real_serving import write_real_serving_outputs
from tests.fixtures import build_trip_updates_payload, write_static_feed


def test_write_real_serving_outputs_from_trained_backfill(tmp_path):
    static_zip = tmp_path / "static.zip"
    stop_updates_path = tmp_path / "stop_updates.parquet"
    training_path = tmp_path / "segment_training.parquet"
    model_dir = tmp_path / "model"
    serving_dir = tmp_path / "serving"
    write_static_feed(static_zip)

    stop_updates = _stop_updates_frame(tmp_path)
    write_frame(stop_updates, stop_updates_path)
    training = build_segment_training_frame(
        stop_updates,
        horizon_minutes=10,
        threshold_seconds=100,
        static_zip_path=static_zip,
    )
    write_frame(training, training_path)
    train_segment_risk_from_file(training_path, output_dir=model_dir, threshold_seconds=100)

    counts = write_real_serving_outputs(
        stop_updates_path=stop_updates_path,
        static_zip_path=static_zip,
        model_path=model_dir / "segment_risk_model.joblib",
        output_dir=serving_dir,
        max_network_rows=25,
    )

    assert counts["network_rows"] > 0
    assert counts["prediction_rows"] == counts["network_rows"]
    assert (serving_dir / "current_network.json").exists()
    assert (serving_dir / "segment_risk.json").exists()
    network = json.loads((serving_dir / "current_network.json").read_text(encoding="utf-8"))
    predictions = json.loads((serving_dir / "segment_risk.json").read_text(encoding="utf-8"))
    assert {
        "route_name",
        "mode",
        "edge_id",
        "src_stop_lat",
        "dst_stop_lon",
        "edge_delay_seconds",
        "previous_edge_delay_seconds",
        "rolling_mean_delay_15m",
        "downstream_delay_score",
    }.issubset(network[0])
    assert {
        "edge_id",
        "risk_probability",
        "model_risk_probability",
        "risk_label",
        "threshold_seconds",
    }.issubset(predictions[0])


def test_route_display_name_uses_short_and_long_gtfs_names():
    from pipeline.real_serving import _route_mode, _route_name

    class Route:
        route_short_name = "1"
        route_long_name = "Harvard Square - Nubian Station"

    assert _route_name("1", Route()) == "1 - Harvard Square - Nubian Station"
    assert _route_mode(3) == "Bus"
    assert _route_mode(2) == "Commuter rail"
    assert _route_mode(4) == "Ferry"


def test_serving_limit_keeps_complete_routes_for_selected_rows():
    from pipeline.real_serving import _limit_network_rows

    frame = pd.DataFrame(
        [
            {
                "route_id": "rail",
                "mode": "Subway",
                "route_name": "Rail",
                "direction_id": 0,
                "stop_position": 1,
                "edge_delay_seconds": 0,
                "trip_count": 1,
            },
            {
                "route_id": "716",
                "mode": "Bus",
                "route_name": "716",
                "direction_id": 0,
                "stop_position": 1,
                "edge_delay_seconds": 500,
                "trip_count": 1,
            },
            {
                "route_id": "716",
                "mode": "Bus",
                "route_name": "716",
                "direction_id": 0,
                "stop_position": 2,
                "edge_delay_seconds": 0,
                "trip_count": 1,
            },
            {
                "route_id": "other",
                "mode": "Bus",
                "route_name": "Other",
                "direction_id": 0,
                "stop_position": 1,
                "edge_delay_seconds": 300,
                "trip_count": 1,
            },
        ]
    )

    limited = _limit_network_rows(frame, 3)

    assert set(limited[limited["route_id"] == "716"]["stop_position"]) == {1, 2}


def _stop_updates_frame(tmp_path) -> pd.DataFrame:
    rows = []
    start = datetime(2026, 5, 12, 12, tzinfo=timezone.utc)
    edge_delays = [20, 40, 160, 40, 190, 60, 210, 50]
    for index, edge_delay in enumerate(edge_delays):
        snapshot_path = tmp_path / f"trip_updates_{index}.pb"
        snapshot_path.write_bytes(
            build_trip_updates_payload(
                feed_timestamp=start + timedelta(minutes=5 * index),
                stop_delays=(10, 10 + edge_delay, 40 + edge_delay),
            )
        )
        rows.extend(decode_snapshot_file(snapshot_path))
    return pd.DataFrame(rows)
