from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from pipeline.backfill import decode_snapshot_dir
from pipeline.bigquery_writer import BigQueryWriter
from pipeline.config import PipelineSettings
from pipeline.http import fetch_bytes
from pipeline.ml import PREDICTIONS_FILENAME
from pipeline.model_monitoring import write_prediction_monitoring_row
from pipeline.real_serving import write_real_serving_outputs
from pipeline.storage import download_blobs, list_recent_blobs


SERVING_TABLE_FILES = {
    "current_network": "current_network.json",
    "current_bottlenecks": "current_bottlenecks.json",
    "current_feed_health": "current_feed_health.json",
    "segment_risk": PREDICTIONS_FILENAME,
}


def refresh_serving_from_gcs(
    *,
    bucket_name: str,
    static_zip_path: str | Path,
    model_path: str | Path,
    output_dir: str | Path = "local_serving",
    project_id: str | None = None,
    serving_dataset: str = "gtfs_serving",
    monitoring_dataset: str = "gtfs_monitoring",
    recent_snapshot_count: int = 24,
    max_network_rows: int = 5000,
    write_bigquery: bool = False,
    write_monitoring: bool = False,
) -> dict[str, Any]:
    blob_names = list_recent_blobs(bucket_name, limit=recent_snapshot_count)
    if not blob_names:
        raise ValueError(f"No TripUpdates snapshots found in gs://{bucket_name}")

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp_dir:
        static_zip = _materialize_artifact(static_zip_path, temp_dir, "MBTA_GTFS.zip")
        model = _materialize_artifact(model_path, temp_dir, "segment_risk_model.joblib")
        raw_dir = Path(temp_dir) / "raw"
        downloaded = download_blobs(bucket_name, blob_names, raw_dir)
        stop_updates_path = Path(temp_dir) / "stop_updates.parquet"
        stop_updates = decode_snapshot_dir(raw_dir, stop_updates_path)

        counts = write_real_serving_outputs(
            stop_updates_path=stop_updates_path,
            static_zip_path=static_zip,
            model_path=model,
            output_dir=output_path,
            max_network_rows=max_network_rows,
        )

    counts.update(
        {
            "snapshot_count": len(downloaded),
            "stop_update_rows": int(len(stop_updates)),
            "first_snapshot": blob_names[-1],
            "latest_snapshot": blob_names[0],
        }
    )
    if write_bigquery:
        if not project_id:
            raise ValueError("project_id is required when write_bigquery=True")
        counts["bigquery_tables"] = write_serving_tables_to_bigquery(
            project_id=project_id,
            serving_dataset=serving_dataset,
            serving_dir=output_path,
        )
    if write_monitoring:
        if not project_id:
            raise ValueError("project_id is required when write_monitoring=True")
        counts["prediction_monitoring"] = write_prediction_monitoring_row(
            project_id=project_id,
            monitoring_dataset=monitoring_dataset,
            serving_dir=output_path,
            snapshot_count=len(downloaded),
            first_snapshot=blob_names[-1],
            latest_snapshot=blob_names[0],
        )
    return counts


def write_serving_tables_to_bigquery(
    *,
    project_id: str,
    serving_dataset: str,
    serving_dir: str | Path,
    writer: BigQueryWriter | None = None,
) -> list[str]:
    active_writer = writer or BigQueryWriter(project_id)
    serving_path = Path(serving_dir)
    written_tables: list[str] = []
    for table_name, file_name in SERVING_TABLE_FILES.items():
        rows = _read_json_rows(serving_path / file_name)
        table_ref = f"{project_id}.{serving_dataset}.{table_name}"
        active_writer.replace_rows(table_ref, rows)
        written_tables.append(table_ref)
    return written_tables


def main() -> None:
    settings = PipelineSettings.from_env()
    parser = argparse.ArgumentParser(
        description="Refresh BigQuery serving tables from recent raw GCS TripUpdates snapshots."
    )
    parser.add_argument("--bucket", default=settings.raw_bucket_name)
    parser.add_argument("--static-zip", default="data/raw/mbta_static/MBTA_GTFS.zip")
    parser.add_argument("--model", default="data/ml/generalization/segment_risk_model.joblib")
    parser.add_argument("--output-dir", default="local_serving")
    parser.add_argument("--project-id", default=settings.project_id)
    parser.add_argument("--serving-dataset", default=settings.serving_dataset)
    parser.add_argument("--monitoring-dataset", default=settings.monitoring_dataset)
    parser.add_argument("--recent-snapshot-count", type=int, default=24)
    parser.add_argument("--max-network-rows", type=int, default=5000)
    parser.add_argument("--write-bigquery", action="store_true")
    parser.add_argument("--write-monitoring", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        raise ValueError("--bucket or RAW_BUCKET_NAME is required")

    counts = refresh_serving_from_gcs(
        bucket_name=args.bucket,
        static_zip_path=args.static_zip,
        model_path=args.model,
        output_dir=args.output_dir,
        project_id=args.project_id,
        serving_dataset=args.serving_dataset,
        monitoring_dataset=args.monitoring_dataset,
        recent_snapshot_count=args.recent_snapshot_count,
        max_network_rows=args.max_network_rows,
        write_bigquery=args.write_bigquery,
        write_monitoring=args.write_monitoring,
    )
    print(json.dumps(counts, indent=2))


def _read_json_rows(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        return [payload]
    raise TypeError(f"Expected JSON object or array in {path}")


def _materialize_artifact(uri: str | Path, temp_dir: str | Path, default_name: str) -> Path:
    value = str(uri)
    if value.startswith("gs://"):
        bucket_name, blob_name = _split_gcs_uri(value)
        target = Path(temp_dir) / "artifacts" / (Path(blob_name).name or default_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("google-cloud-storage is required for GCS artifact reads") from exc
        storage.Client().bucket(bucket_name).blob(blob_name).download_to_filename(target)
        return target

    parsed = urlparse(value)
    if parsed.scheme in {"http", "https"}:
        target = Path(temp_dir) / "artifacts" / (Path(parsed.path).name or default_name)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(fetch_bytes(value))
        return target

    return Path(uri)


def _split_gcs_uri(uri: str) -> tuple[str, str]:
    parsed = urlparse(uri)
    if parsed.scheme != "gs" or not parsed.netloc or not parsed.path.strip("/"):
        raise ValueError(f"Expected a gs://bucket/object URI, got {uri!r}")
    return parsed.netloc, parsed.path.lstrip("/")
if __name__ == "__main__":
    main()
