from __future__ import annotations

import argparse
import json
import re
import tempfile
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from statistics import mean, stdev
from typing import Any

import pandas as pd

from pipeline.backfill import build_segment_training_frame, decode_snapshot_paths
from pipeline.evaluate_segment_risk import build_topk_metrics
from pipeline.ml import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    _ensure_feature_columns,
    _safe_auc,
    _safe_pr_auc,
    build_segment_risk_pipeline,
)


SNAPSHOT_PATTERN = re.compile(r"realtime/trip_updates/(\d{4}-\d{2}-\d{2})/(\d{6})\.pb$")


@dataclass(frozen=True)
class SnapshotBlob:
    name: str
    timestamp: datetime


@dataclass(frozen=True)
class FoldWindow:
    test_date: date
    train_start: datetime
    train_end: datetime
    test_start: datetime
    test_end: datetime


def run_rolling_origin_evaluation(
    *,
    bucket_name: str,
    static_zip_path: str | Path,
    output_dir: str | Path = "data/ml/rolling_origin",
    cache_dir: str | Path = "data/cache/rolling_origin_snapshots",
    prefix: str = "realtime/trip_updates/",
    test_days: int = 10,
    train_days: int = 5,
    sample_every_minutes: int = 120,
    horizon_minutes: int = 10,
    threshold_seconds: int = 180,
    embargo_minutes: int = 120,
) -> dict[str, Any]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    snapshots = list_snapshot_blobs(bucket_name, prefix=prefix)
    if not snapshots:
        raise ValueError(f"No snapshots found in gs://{bucket_name}/{prefix}")

    test_dates = choose_test_dates(snapshots, train_days=train_days, test_days=test_days)
    if not test_dates:
        raise ValueError("No eligible test dates found for the requested train/test windows")

    static_zip = materialize_artifact(static_zip_path, output_path / "artifacts", "MBTA_GTFS.zip")
    cache_path = Path(cache_dir)
    fold_rows: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        for test_day in test_dates:
            window = build_fold_window(
                test_day,
                train_days=train_days,
                embargo_minutes=embargo_minutes,
            )
            fold_rows.append(
                evaluate_fold(
                    bucket_name=bucket_name,
                    snapshots=snapshots,
                    window=window,
                    static_zip_path=static_zip,
                    cache_dir=cache_path,
                    work_dir=temp_path / test_day.isoformat(),
                    sample_every_minutes=sample_every_minutes,
                    horizon_minutes=horizon_minutes,
                    threshold_seconds=threshold_seconds,
                )
            )

    fold_frame = pd.DataFrame(fold_rows)
    fold_frame.to_csv(output_path / "fold_metrics.csv", index=False)
    summary = build_summary(
        fold_rows,
        parameters={
            "bucket_name": bucket_name,
            "prefix": prefix,
            "test_days": test_days,
            "train_days": train_days,
            "sample_every_minutes": sample_every_minutes,
            "horizon_minutes": horizon_minutes,
            "threshold_seconds": threshold_seconds,
            "embargo_minutes": embargo_minutes,
            "snapshot_count": len(snapshots),
            "first_snapshot": snapshots[0].timestamp.isoformat(),
            "latest_snapshot": snapshots[-1].timestamp.isoformat(),
        },
    )
    (output_path / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return summary


def evaluate_fold(
    *,
    bucket_name: str,
    snapshots: list[SnapshotBlob],
    window: FoldWindow,
    static_zip_path: Path,
    cache_dir: Path,
    work_dir: Path,
    sample_every_minutes: int,
    horizon_minutes: int,
    threshold_seconds: int,
) -> dict[str, Any]:
    train_blobs = select_snapshot_pairs(
        snapshots,
        start=window.train_start,
        end=window.train_end,
        sample_every_minutes=sample_every_minutes,
        horizon_minutes=horizon_minutes,
    )
    test_blobs = select_snapshot_pairs(
        snapshots,
        start=window.test_start,
        end=window.test_end,
        sample_every_minutes=sample_every_minutes,
        horizon_minutes=horizon_minutes,
    )
    if not train_blobs or not test_blobs:
        return skipped_fold(window, "missing sampled train/test snapshots")

    work_dir.mkdir(parents=True, exist_ok=True)
    train_paths = ensure_cached_blobs(bucket_name, train_blobs, cache_dir)
    test_paths = ensure_cached_blobs(bucket_name, test_blobs, cache_dir)
    train_stop_updates = decode_snapshot_paths(train_paths, work_dir / "train_stop_updates.parquet")
    test_stop_updates = decode_snapshot_paths(test_paths, work_dir / "test_stop_updates.parquet")
    train_frame = build_segment_training_frame(
        train_stop_updates,
        horizon_minutes=horizon_minutes,
        threshold_seconds=threshold_seconds,
        static_zip_path=static_zip_path,
    )
    test_frame = build_segment_training_frame(
        test_stop_updates,
        horizon_minutes=horizon_minutes,
        threshold_seconds=threshold_seconds,
        static_zip_path=static_zip_path,
    )
    if train_frame.empty or test_frame.empty:
        return skipped_fold(window, "empty train/test examples")
    if train_frame[TARGET_COLUMN].nunique() < 2:
        return skipped_fold(window, "training fold has one target class")

    train_frame = _ensure_feature_columns(train_frame)
    test_frame = _ensure_feature_columns(test_frame)
    model = build_segment_risk_pipeline()
    model.fit(train_frame[FEATURE_COLUMNS], train_frame[TARGET_COLUMN])
    target = test_frame[TARGET_COLUMN].astype(int)
    model_scores = model.predict_proba(test_frame[FEATURE_COLUMNS])[:, 1]
    baseline_scores = (test_frame["current_edge_delay_seconds"] / threshold_seconds).clip(0, 1)
    topk = build_topk_metrics(target, model_scores, baseline_scores)

    return {
        **fold_window_row(window),
        "status": "evaluated",
        "message": "ok",
        "train_snapshot_count": len(train_blobs),
        "test_snapshot_count": len(test_blobs),
        "train_rows": int(len(train_frame)),
        "test_rows": int(len(test_frame)),
        "train_positive_rate": float(train_frame[TARGET_COLUMN].mean()),
        "test_positive_rate": float(target.mean()),
        "model_pr_auc": _safe_pr_auc(target, model_scores),
        "baseline_pr_auc": _safe_pr_auc(target, baseline_scores),
        "model_roc_auc": _safe_auc(target, model_scores),
        "baseline_roc_auc": _safe_auc(target, baseline_scores),
        "model_precision_at_25": topk["model"]["precision_at_25"],
        "model_precision_at_50": topk["model"]["precision_at_50"],
        "model_precision_at_100": topk["model"]["precision_at_100"],
        "model_recall_at_100": topk["model"]["recall_at_100"],
        "baseline_precision_at_50": topk["persistence"]["precision_at_50"],
        "baseline_precision_at_100": topk["persistence"]["precision_at_100"],
    }


def list_snapshot_blobs(bucket_name: str, prefix: str = "realtime/trip_updates/") -> list[SnapshotBlob]:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for GCS reads") from exc

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    snapshots = [
        SnapshotBlob(name=blob.name, timestamp=timestamp)
        for blob in bucket.list_blobs(prefix=prefix)
        if (timestamp := parse_snapshot_timestamp(blob.name)) is not None
    ]
    return sorted(snapshots, key=lambda item: item.timestamp)


def parse_snapshot_timestamp(blob_name: str) -> datetime | None:
    match = SNAPSHOT_PATTERN.search(blob_name)
    if not match:
        return None
    date_part, time_part = match.groups()
    return datetime.strptime(f"{date_part}{time_part}", "%Y-%m-%d%H%M%S").replace(
        tzinfo=timezone.utc
    )


def choose_test_dates(
    snapshots: list[SnapshotBlob],
    *,
    train_days: int,
    test_days: int,
) -> list[date]:
    if not snapshots:
        return []
    earliest = snapshots[0].timestamp
    available_dates = sorted({snapshot.timestamp.date() for snapshot in snapshots})
    eligible = [
        day
        for day in available_dates
        if datetime.combine(day, time.min, tzinfo=timezone.utc)
        - timedelta(days=train_days)
        >= earliest
    ]
    return eligible[-test_days:]


def build_fold_window(test_day: date, *, train_days: int, embargo_minutes: int) -> FoldWindow:
    test_start = datetime.combine(test_day, time.min, tzinfo=timezone.utc)
    return FoldWindow(
        test_date=test_day,
        train_start=test_start - timedelta(days=train_days),
        train_end=test_start - timedelta(minutes=embargo_minutes),
        test_start=test_start,
        test_end=test_start + timedelta(days=1),
    )


def select_snapshot_pairs(
    snapshots: list[SnapshotBlob],
    *,
    start: datetime,
    end: datetime,
    sample_every_minutes: int,
    horizon_minutes: int,
) -> list[str]:
    selected: dict[str, None] = {}
    cursor = start
    future_offsets = sorted({max(1, horizon_minutes // 2), horizon_minutes})
    while cursor < end:
        base = first_snapshot_at_or_after(snapshots, cursor, end=end)
        if base is None:
            break
        futures = [
            future
            for offset in future_offsets
            if (
                future := first_snapshot_at_or_after(
                    snapshots,
                    base.timestamp + timedelta(minutes=offset),
                    end=end,
                )
            )
            is not None
        ]
        if futures:
            selected[base.name] = None
            for future in futures:
                selected[future.name] = None
        cursor += timedelta(minutes=sample_every_minutes)
    return list(selected)


def first_snapshot_at_or_after(
    snapshots: list[SnapshotBlob],
    target: datetime,
    *,
    end: datetime,
) -> SnapshotBlob | None:
    for snapshot in snapshots:
        if snapshot.timestamp >= end:
            return None
        if snapshot.timestamp >= target:
            return snapshot
    return None


def ensure_cached_blobs(bucket_name: str, blob_names: list[str], cache_dir: Path) -> list[Path]:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for GCS reads") from exc

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    paths: list[Path] = []
    for blob_name in blob_names:
        local_path = cache_dir / blob_name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        if not local_path.exists():
            bucket.blob(blob_name).download_to_filename(local_path)
        paths.append(local_path)
    return paths


def materialize_artifact(source: str | Path, output_dir: Path, default_name: str) -> Path:
    source_value = str(source)
    output_dir.mkdir(parents=True, exist_ok=True)
    if source_value.startswith("gs://"):
        try:
            from google.cloud import storage
        except ImportError as exc:
            raise RuntimeError("google-cloud-storage is required for GCS reads") from exc
        bucket_name, blob_name = source_value.removeprefix("gs://").split("/", 1)
        target = output_dir / (Path(blob_name).name or default_name)
        storage.Client().bucket(bucket_name).blob(blob_name).download_to_filename(target)
        return target
    return Path(source)


def build_summary(fold_rows: list[dict[str, Any]], parameters: dict[str, Any]) -> dict[str, Any]:
    evaluated = [row for row in fold_rows if row.get("status") == "evaluated"]
    positive_test = [
        row
        for row in evaluated
        if float(row.get("test_positive_rate") or 0) > 0
    ]
    return {
        "parameters": parameters,
        "fold_count": len(fold_rows),
        "evaluated_fold_count": len(evaluated),
        "positive_test_fold_count": len(positive_test),
        "skipped_fold_count": len(fold_rows) - len(evaluated),
        "metrics": {
            "model_pr_auc": mean_sd(evaluated, "model_pr_auc"),
            "baseline_pr_auc": mean_sd(evaluated, "baseline_pr_auc"),
            "model_precision_at_50": mean_sd(evaluated, "model_precision_at_50"),
            "baseline_precision_at_50": mean_sd(evaluated, "baseline_precision_at_50"),
            "model_precision_at_100": mean_sd(evaluated, "model_precision_at_100"),
            "baseline_precision_at_100": mean_sd(evaluated, "baseline_precision_at_100"),
            "model_recall_at_100": mean_sd(evaluated, "model_recall_at_100"),
        },
        "positive_test_metrics": {
            "model_pr_auc": mean_sd(positive_test, "model_pr_auc"),
            "baseline_pr_auc": mean_sd(positive_test, "baseline_pr_auc"),
            "model_precision_at_50": mean_sd(positive_test, "model_precision_at_50"),
            "baseline_precision_at_50": mean_sd(positive_test, "baseline_precision_at_50"),
            "model_precision_at_100": mean_sd(positive_test, "model_precision_at_100"),
            "baseline_precision_at_100": mean_sd(positive_test, "baseline_precision_at_100"),
            "model_recall_at_100": mean_sd(positive_test, "model_recall_at_100"),
        },
        "folds": fold_rows,
    }


def mean_sd(rows: list[dict[str, Any]], key: str) -> dict[str, float | None]:
    values = [float(row[key]) for row in rows if row.get(key) is not None]
    if not values:
        return {"mean": None, "sd": None}
    return {
        "mean": float(mean(values)),
        "sd": float(stdev(values)) if len(values) > 1 else 0.0,
    }


def skipped_fold(window: FoldWindow, message: str) -> dict[str, Any]:
    return {
        **fold_window_row(window),
        "status": "skipped",
        "message": message,
    }


def fold_window_row(window: FoldWindow) -> dict[str, Any]:
    return {
        "test_date": window.test_date.isoformat(),
        "train_start": window.train_start.isoformat(),
        "train_end": window.train_end.isoformat(),
        "test_start": window.test_start.isoformat(),
        "test_end": window.test_end.isoformat(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Run purged rolling-origin segment-risk evaluation.")
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--static-zip", required=True)
    parser.add_argument("--output-dir", default="data/ml/rolling_origin")
    parser.add_argument("--cache-dir", default="data/cache/rolling_origin_snapshots")
    parser.add_argument("--prefix", default="realtime/trip_updates/")
    parser.add_argument("--test-days", type=int, default=10)
    parser.add_argument("--train-days", type=int, default=5)
    parser.add_argument("--sample-every-minutes", type=int, default=120)
    parser.add_argument("--horizon-minutes", type=int, default=10)
    parser.add_argument("--threshold-seconds", type=int, default=180)
    parser.add_argument("--embargo-minutes", type=int, default=120)
    args = parser.parse_args()
    run_rolling_origin_evaluation(
        bucket_name=args.bucket,
        static_zip_path=args.static_zip,
        output_dir=args.output_dir,
        cache_dir=args.cache_dir,
        prefix=args.prefix,
        test_days=args.test_days,
        train_days=args.train_days,
        sample_every_minutes=args.sample_every_minutes,
        horizon_minutes=args.horizon_minutes,
        threshold_seconds=args.threshold_seconds,
        embargo_minutes=args.embargo_minutes,
    )


if __name__ == "__main__":
    main()
