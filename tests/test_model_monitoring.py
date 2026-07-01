from __future__ import annotations

import json

from pipeline.model_monitoring import (
    build_prediction_monitoring_row,
    write_prediction_monitoring_row,
)


class RecordingWriter:
    def __init__(self):
        self.calls = []

    def append_rows(self, table_ref, rows):
        self.calls.append((table_ref, list(rows)))


def test_build_prediction_monitoring_row_summarizes_serving_outputs(tmp_path):
    serving_dir = tmp_path / "serving"
    serving_dir.mkdir()
    (serving_dir / "segment_risk.json").write_text(
        json.dumps(
            [
                {
                    "generated_at": "2026-06-03T12:00:00Z",
                    "risk_probability": 0.9,
                    "model_risk_probability": 0.8,
                    "threshold_seconds": 180,
                },
                {
                    "generated_at": "2026-06-03T12:00:00Z",
                    "risk_probability": 0.3,
                    "model_risk_probability": 0.2,
                    "threshold_seconds": 180,
                },
            ]
        ),
        encoding="utf-8",
    )
    (serving_dir / "current_network.json").write_text(
        json.dumps(
            [
                {"feed_timestamp": "2026-06-03T11:58:00Z", "edge_delay_seconds": 120},
                {"feed_timestamp": "2026-06-03T11:58:00Z", "edge_delay_seconds": 0},
                {"feed_timestamp": "2026-06-03T11:58:00Z", "edge_delay_seconds": 240},
            ]
        ),
        encoding="utf-8",
    )
    (serving_dir / "current_feed_health.json").write_text(
        json.dumps({"feed_timestamp": "2026-06-03T11:58:00Z"}),
        encoding="utf-8",
    )
    (serving_dir / "model_metrics.json").write_text(
        json.dumps(
            {
                "roc_auc": 0.82,
                "baseline_roc_auc": 0.7,
                "pr_auc": 0.5,
                "baseline_pr_auc": 0.3,
                "precision": 0.4,
                "recall": 0.6,
                "positive_rate": 0.1,
                "training_rows": 1000,
                "train_window": "train",
                "test_window": "test",
                "threshold_seconds": 180,
                "prediction_horizon_minutes": 10,
            }
        ),
        encoding="utf-8",
    )

    row = build_prediction_monitoring_row(
        serving_dir=serving_dir,
        snapshot_count=4,
        first_snapshot="old.pb",
        latest_snapshot="new.pb",
    )

    assert row["prediction_count"] == 2
    assert row["network_edge_count"] == 3
    assert row["missing_prediction_count"] == 1
    assert row["avg_risk_probability"] == 0.6
    assert row["high_risk_count"] == 1
    assert row["delayed_edge_count"] == 2
    assert row["model_roc_auc"] == 0.82
    assert row["snapshot_count"] == 4


def test_write_prediction_monitoring_row_appends_to_bigquery_table(tmp_path):
    serving_dir = tmp_path / "serving"
    serving_dir.mkdir()
    (serving_dir / "segment_risk.json").write_text("[]", encoding="utf-8")
    (serving_dir / "current_network.json").write_text("[]", encoding="utf-8")
    (serving_dir / "current_feed_health.json").write_text("{}", encoding="utf-8")
    writer = RecordingWriter()

    row = write_prediction_monitoring_row(
        project_id="project",
        monitoring_dataset="gtfs_monitoring",
        serving_dir=serving_dir,
        writer=writer,
    )

    assert writer.calls == [
        ("project.gtfs_monitoring.prediction_monitoring", [row])
    ]
