from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pandas as pd

from pipeline.backfill import (
    build_segment_training_frame,
    decode_snapshot_dir,
    list_snapshot_paths,
    read_frame,
    write_frame,
)
from pipeline.ml import train_segment_risk_from_file
from tests.fixtures import build_trip_updates_payload
from tests.fixtures import write_static_feed


def test_decode_snapshot_dir_writes_stop_update_table(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    timestamp = datetime(2026, 5, 12, 12, tzinfo=timezone.utc)
    (raw_dir / "trip_updates_20260512T120000Z.pb").write_bytes(
        build_trip_updates_payload(feed_timestamp=timestamp, stop_delays=(10, 80, 160))
    )

    output_path = tmp_path / "processed" / "stop_updates.parquet"
    frame = decode_snapshot_dir(raw_dir, output_path)
    round_tripped = read_frame(output_path)

    assert output_path.exists()
    assert len(frame) == 3
    assert len(round_tripped) == 3
    assert {"feed_timestamp", "route_id", "stop_id", "best_delay_seconds"}.issubset(frame)


def test_decode_snapshot_dir_reads_nested_snapshots_with_bounds(tmp_path):
    raw_dir = tmp_path / "raw"
    nested_dir = raw_dir / "2026-05-12"
    nested_dir.mkdir(parents=True)
    for index in range(4):
        timestamp = datetime(2026, 5, 12, 12, 5 * index, tzinfo=timezone.utc)
        (nested_dir / f"trip_updates_{index}.pb").write_bytes(
            build_trip_updates_payload(feed_timestamp=timestamp, stop_delays=(10, 80, 160))
        )

    output_path = tmp_path / "processed" / "bounded_stop_updates.parquet"
    frame = decode_snapshot_dir(raw_dir, output_path, max_snapshots=2, snapshot_stride=2)

    assert [path.name for path in list_snapshot_paths(raw_dir, max_snapshots=2, snapshot_stride=2)] == [
        "trip_updates_0.pb",
        "trip_updates_2.pb",
    ]
    assert len(frame) == 6


def test_decode_snapshot_dir_time_sample_keeps_future_offsets(tmp_path):
    raw_dir = tmp_path / "raw"
    nested_dir = raw_dir / "2026-05-12"
    nested_dir.mkdir(parents=True)
    start = datetime(2026, 5, 12, 12, tzinfo=timezone.utc)
    for minute in range(0, 70, 5):
        timestamp = start + timedelta(minutes=minute)
        (nested_dir / f"{timestamp:%H%M%S}.pb").write_bytes(
            build_trip_updates_payload(feed_timestamp=timestamp, stop_delays=(10, 80, 160))
        )

    paths = list_snapshot_paths(
        raw_dir,
        sample_every_minutes=30,
        include_offsets_minutes=[0, 10],
    )

    assert [path.name for path in paths] == [
        "120000.pb",
        "121000.pb",
        "123000.pb",
        "124000.pb",
        "130000.pb",
    ]


def test_build_segment_training_frame_labels_future_delay_window(tmp_path):
    stop_updates = _backfill_stop_updates_frame(tmp_path)
    static_zip = tmp_path / "static.zip"
    write_static_feed(static_zip)

    training = build_segment_training_frame(
        stop_updates,
        horizon_minutes=10,
        threshold_seconds=100,
        static_zip_path=static_zip,
    )

    assert not training.empty
    assert {"edge_id", "current_delay_seconds", "future_delay_seconds"}.issubset(training)
    assert set(training["target_delay_exceeds_threshold"]) == {0, 1}
    assert training["previous_delay_seconds"].notna().all()
    assert set(training["hour_of_day"]) == {8}
    assert set(training["day_of_week"]) == {1}


def test_train_segment_risk_from_real_backfill_examples(tmp_path):
    training = build_segment_training_frame(
        _backfill_stop_updates_frame(tmp_path),
        horizon_minutes=10,
        threshold_seconds=100,
        static_zip_path=_static_zip(tmp_path),
    )
    training_path = tmp_path / "segment_training.parquet"
    output_dir = tmp_path / "model"
    write_frame(training, training_path)

    artifact = train_segment_risk_from_file(
        training_path,
        output_dir=output_dir,
        threshold_seconds=100,
    )

    assert (output_dir / "segment_risk_model.joblib").exists()
    assert (output_dir / "model_metrics.json").exists()
    assert artifact.metrics["training_rows"] == len(training)
    written_metrics = json.loads((output_dir / "model_metrics.json").read_text(encoding="utf-8"))
    assert {
        "positive_rate",
        "f1",
        "baseline_f1",
        "pr_auc",
        "baseline_pr_auc",
        "threshold_probability",
        "time_split",
        "train_window",
        "test_window",
        "prediction_horizon_minutes",
        "embargo_minutes",
        "precision",
        "recall",
        "roc_auc",
        "baseline_roc_auc",
    }.issubset(written_metrics)
    assert written_metrics["time_split"] is True


def _backfill_stop_updates_frame(tmp_path) -> pd.DataFrame:
    rows = []
    start = datetime(2026, 5, 12, 12, tzinfo=timezone.utc)
    edge_delays = [20, 40, 160, 40, 190, 60, 210, 50]
    for index, edge_delay in enumerate(edge_delays):
        timestamp = start + timedelta(minutes=5 * index)
        payload = build_trip_updates_payload(
            feed_timestamp=timestamp,
            stop_delays=(10, 10 + edge_delay, 40 + edge_delay),
        )
        snapshot_path = tmp_path / f"trip_updates_{index}.pb"
        snapshot_path.write_bytes(payload)
        from pipeline.backfill import decode_snapshot_file

        rows.extend(decode_snapshot_file(snapshot_path))
    return pd.DataFrame(rows)


def _static_zip(tmp_path):
    path = tmp_path / "static.zip"
    write_static_feed(path)
    return path
