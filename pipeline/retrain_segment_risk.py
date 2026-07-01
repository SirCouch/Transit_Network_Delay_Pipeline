from __future__ import annotations

import argparse
import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pipeline.backfill import build_segment_training_frame, decode_snapshot_dir, write_frame
from pipeline.bigquery_writer import BigQueryWriter
from pipeline.cloud_serving import _materialize_artifact
from pipeline.config import PipelineSettings
from pipeline.ml import METRICS_FILENAME, MODEL_FILENAME, train_segment_risk_from_file
from pipeline.storage import download_blobs, list_recent_blobs, upload_file


def retrain_segment_risk_from_gcs(
    *,
    bucket_name: str,
    static_zip_path: str | Path,
    project_id: str | None = None,
    monitoring_dataset: str = "gtfs_monitoring",
    output_prefix: str = "artifacts/models/segment-risk",
    recent_snapshot_count: int = 336,
    horizon_minutes: int = 10,
    threshold_seconds: int = 180,
    threshold_probability: float = 0.5,
    embargo_minutes: int = 10,
    promote: bool = False,
    writer: BigQueryWriter | None = None,
) -> dict[str, Any]:
    started_at = _utc_now()
    run_id = _run_id()
    blob_names = list_recent_blobs(bucket_name, limit=recent_snapshot_count)
    if not blob_names:
        raise ValueError(f"No TripUpdates snapshots found in gs://{bucket_name}")

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        static_zip = _materialize_artifact(static_zip_path, temp_path, "MBTA_GTFS.zip")
        raw_dir = temp_path / "raw"
        downloaded = download_blobs(bucket_name, blob_names, raw_dir)
        stop_updates_path = temp_path / "stop_updates.parquet"
        stop_updates = decode_snapshot_dir(raw_dir, stop_updates_path)
        training = build_segment_training_frame(
            stop_updates,
            horizon_minutes=horizon_minutes,
            threshold_seconds=threshold_seconds,
            static_zip_path=static_zip,
        )
        if training.empty:
            raise ValueError("Retraining produced 0 training examples")
        training_path = temp_path / "segment_training.parquet"
        write_frame(training, training_path)
        model_dir = temp_path / "model"
        artifact = train_segment_risk_from_file(
            training_path,
            output_dir=model_dir,
            threshold_seconds=threshold_seconds,
            threshold_probability=threshold_probability,
            prediction_horizon_minutes=horizon_minutes,
            embargo_minutes=embargo_minutes,
        )

        artifact_prefix = f"{output_prefix.rstrip('/')}/{run_id}"
        model_uri = upload_file(bucket_name, f"{artifact_prefix}/{MODEL_FILENAME}", model_dir / MODEL_FILENAME)
        metrics_uri = upload_file(
            bucket_name,
            f"{artifact_prefix}/{METRICS_FILENAME}",
            model_dir / METRICS_FILENAME,
        )
        training_uri = upload_file(bucket_name, f"{artifact_prefix}/segment_training.parquet", training_path)
        promoted_model_uri = None
        promoted_metrics_uri = None
        if promote:
            promoted_model_uri = upload_file(
                bucket_name,
                f"artifacts/{MODEL_FILENAME}",
                model_dir / MODEL_FILENAME,
            )
            promoted_metrics_uri = upload_file(
                bucket_name,
                f"artifacts/{METRICS_FILENAME}",
                model_dir / METRICS_FILENAME,
            )

    completed_at = _utc_now()
    row = {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "status": "succeeded",
        "message": "Retraining completed successfully.",
        "snapshot_count": len(downloaded),
        "first_snapshot": blob_names[-1],
        "latest_snapshot": blob_names[0],
        "stop_update_rows": int(len(stop_updates)),
        "training_rows": int(len(training)),
        "positive_rate": float(artifact.metrics.get("positive_rate", 0)),
        "model_roc_auc": float(artifact.metrics.get("roc_auc", 0.5)),
        "baseline_roc_auc": float(artifact.metrics.get("baseline_roc_auc", 0.5)),
        "model_pr_auc": float(artifact.metrics.get("pr_auc", 0)),
        "baseline_pr_auc": float(artifact.metrics.get("baseline_pr_auc", 0)),
        "model_precision": float(artifact.metrics.get("precision", 0)),
        "model_recall": float(artifact.metrics.get("recall", 0)),
        "model_f1": float(artifact.metrics.get("f1", 0)),
        "threshold_seconds": threshold_seconds,
        "threshold_probability": threshold_probability,
        "prediction_horizon_minutes": horizon_minutes,
        "embargo_minutes": embargo_minutes,
        "train_window": artifact.metrics.get("train_window"),
        "test_window": artifact.metrics.get("test_window"),
        "model_uri": model_uri,
        "metrics_uri": metrics_uri,
        "training_data_uri": training_uri,
        "promoted": promote,
        "promoted_model_uri": promoted_model_uri,
        "promoted_metrics_uri": promoted_metrics_uri,
    }
    if project_id:
        active_writer = writer or BigQueryWriter(project_id)
        active_writer.append_rows(f"{project_id}.{monitoring_dataset}.retraining_runs", [row])
    return row


def main() -> None:
    settings = PipelineSettings.from_env()
    parser = argparse.ArgumentParser(description="Retrain the segment-risk model from GCS snapshots.")
    parser.add_argument("--bucket", default=settings.raw_bucket_name)
    parser.add_argument("--static-zip", default="gs://")
    parser.add_argument("--project-id", default=settings.project_id)
    parser.add_argument("--monitoring-dataset", default=settings.monitoring_dataset)
    parser.add_argument("--output-prefix", default="artifacts/models/segment-risk")
    parser.add_argument("--recent-snapshot-count", type=int, default=336)
    parser.add_argument("--horizon-minutes", type=int, default=10)
    parser.add_argument("--threshold-seconds", type=int, default=180)
    parser.add_argument("--threshold-probability", type=float, default=0.5)
    parser.add_argument("--embargo-minutes", type=int, default=10)
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    if not args.bucket:
        raise ValueError("--bucket or RAW_BUCKET_NAME is required")
    static_zip = args.static_zip
    if static_zip == "gs://":
        static_zip = f"gs://{args.bucket}/artifacts/MBTA_GTFS.zip"
    row = retrain_segment_risk_from_gcs(
        bucket_name=args.bucket,
        static_zip_path=static_zip,
        project_id=args.project_id,
        monitoring_dataset=args.monitoring_dataset,
        output_prefix=args.output_prefix,
        recent_snapshot_count=args.recent_snapshot_count,
        horizon_minutes=args.horizon_minutes,
        threshold_seconds=args.threshold_seconds,
        threshold_probability=args.threshold_probability,
        embargo_minutes=args.embargo_minutes,
        promote=args.promote,
    )
    print(json.dumps(row, indent=2))


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _run_id() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")


if __name__ == "__main__":
    main()
