from __future__ import annotations

import json

from pipeline.cloud_serving import _split_gcs_uri, write_serving_tables_to_bigquery


class RecordingWriter:
    def __init__(self):
        self.calls = []

    def replace_rows(self, table_ref, rows):
        self.calls.append((table_ref, list(rows)))


def test_write_serving_tables_replaces_expected_bigquery_tables(tmp_path):
    serving_dir = tmp_path / "serving"
    serving_dir.mkdir()
    (serving_dir / "current_network.json").write_text(
        json.dumps([{"edge_id": "edge-1"}]),
        encoding="utf-8",
    )
    (serving_dir / "current_bottlenecks.json").write_text(
        json.dumps([{"rank": 1}]),
        encoding="utf-8",
    )
    (serving_dir / "current_feed_health.json").write_text(
        json.dumps({"status": "ok"}),
        encoding="utf-8",
    )
    (serving_dir / "segment_risk.json").write_text(
        json.dumps([{"edge_id": "edge-1", "risk_probability": 0.4}]),
        encoding="utf-8",
    )
    writer = RecordingWriter()

    tables = write_serving_tables_to_bigquery(
        project_id="project",
        serving_dataset="gtfs_serving",
        serving_dir=serving_dir,
        writer=writer,
    )

    assert tables == [
        "project.gtfs_serving.current_network",
        "project.gtfs_serving.current_bottlenecks",
        "project.gtfs_serving.current_feed_health",
        "project.gtfs_serving.segment_risk",
    ]
    assert writer.calls[0] == ("project.gtfs_serving.current_network", [{"edge_id": "edge-1"}])
    assert writer.calls[2] == ("project.gtfs_serving.current_feed_health", [{"status": "ok"}])


def test_split_gcs_uri():
    assert _split_gcs_uri("gs://bucket/path/to/model.joblib") == (
        "bucket",
        "path/to/model.joblib",
    )
