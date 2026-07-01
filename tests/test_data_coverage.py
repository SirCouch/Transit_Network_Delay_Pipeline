from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd

from pipeline.backfill import write_frame
from pipeline.data_coverage import build_coverage_report


def test_coverage_report_summarizes_day_hour_and_target_balance(tmp_path):
    stop_updates_path = tmp_path / "stop_updates.parquet"
    training_path = tmp_path / "segment_training.parquet"
    start = datetime(2026, 5, 16, 9, tzinfo=timezone.utc)
    stop_updates = pd.DataFrame(
        [
            {
                "feed_timestamp": start + timedelta(days=day, hours=hour),
                "route_id": "1",
                "trip_id": f"trip-{day}-{hour}",
            }
            for day in range(2)
            for hour in (0, 9, 17)
        ]
    )
    training = pd.DataFrame(
        [
            {
                "feed_timestamp": start,
                "route_id": "1",
                "edge_id": "1:A:B",
                "target_delay_exceeds_threshold": 1,
            },
            {
                "feed_timestamp": start + timedelta(hours=1),
                "route_id": "1",
                "edge_id": "1:B:C",
                "target_delay_exceeds_threshold": 0,
            },
        ]
    )
    write_frame(stop_updates, stop_updates_path)
    write_frame(training, training_path)

    report = build_coverage_report(stop_updates_path, training_path)

    assert report["stop_updates"]["snapshots"] == 6
    assert report["stop_updates"]["unique_service_dates"] == 2
    assert report["stop_updates"]["timezone"] == "America/New_York"
    assert report["stop_updates"]["hour_coverage"] == {"5": 2, "14": 2, "22": 2}
    assert report["training"]["positive_targets"] == 1
    assert report["training"]["negative_targets"] == 1
    assert "Collect more snapshots" in report["recommendation"]
