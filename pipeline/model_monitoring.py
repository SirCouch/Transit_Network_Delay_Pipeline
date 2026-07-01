from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean
from typing import Any

from pipeline.bigquery_writer import BigQueryWriter


def build_prediction_monitoring_row(
    *,
    serving_dir: str | Path,
    snapshot_count: int | None = None,
    first_snapshot: str | None = None,
    latest_snapshot: str | None = None,
) -> dict[str, Any]:
    serving_path = Path(serving_dir)
    predictions = _read_json(serving_path / "segment_risk.json", default=[])
    network = _read_json(serving_path / "current_network.json", default=[])
    feed_health = _read_json(serving_path / "current_feed_health.json", default={})
    metrics = _read_json(serving_path / "model_metrics.json", default={})

    if not isinstance(predictions, list):
        predictions = []
    if not isinstance(network, list):
        network = []
    if not isinstance(feed_health, dict):
        feed_health = {}
    if not isinstance(metrics, dict):
        metrics = {}

    risk_values = [_number(row.get("risk_probability")) for row in predictions]
    risk_values = [value for value in risk_values if value is not None]
    model_values = [_number(row.get("model_risk_probability")) for row in predictions]
    model_values = [value for value in model_values if value is not None]
    delay_values = [
        _number(row.get("edge_delay_seconds") or row.get("current_edge_delay_seconds"))
        for row in network
    ]
    delay_values = [value for value in delay_values if value is not None]
    top_50 = sorted(risk_values, reverse=True)[:50]

    return {
        "logged_at": _utc_now(),
        "generated_at": _first_value(predictions, "generated_at")
        or feed_health.get("generated_at")
        or _utc_now(),
        "feed_timestamp": feed_health.get("feed_timestamp")
        or _first_value(network, "feed_timestamp"),
        "model_version": _model_version(metrics),
        "prediction_count": len(predictions),
        "network_edge_count": len(network),
        "missing_prediction_count": max(0, len(network) - len(predictions)),
        "avg_risk_probability": _average(risk_values),
        "min_risk_probability": min(risk_values) if risk_values else None,
        "max_risk_probability": max(risk_values) if risk_values else None,
        "avg_model_risk_probability": _average(model_values),
        "top_50_avg_risk_probability": _average(top_50),
        "high_risk_count": sum(1 for value in risk_values if value >= 0.75),
        "medium_or_high_risk_count": sum(1 for value in risk_values if value >= 0.5),
        "avg_current_delay_seconds": _average(delay_values),
        "max_current_delay_seconds": max(delay_values) if delay_values else None,
        "delayed_edge_count": sum(1 for value in delay_values if value > 60),
        "model_roc_auc": _number(metrics.get("roc_auc")),
        "baseline_roc_auc": _number(metrics.get("baseline_roc_auc")),
        "model_pr_auc": _number(metrics.get("pr_auc")),
        "baseline_pr_auc": _number(metrics.get("baseline_pr_auc")),
        "model_precision": _number(metrics.get("precision")),
        "model_recall": _number(metrics.get("recall")),
        "positive_rate": _number(metrics.get("positive_rate")),
        "training_rows": _number(metrics.get("training_rows")),
        "train_window": metrics.get("train_window"),
        "test_window": metrics.get("test_window"),
        "threshold_seconds": _number(metrics.get("threshold_seconds"))
        or _first_number(predictions, "threshold_seconds"),
        "prediction_horizon_minutes": _number(metrics.get("prediction_horizon_minutes")),
        "snapshot_count": snapshot_count,
        "first_snapshot": first_snapshot,
        "latest_snapshot": latest_snapshot,
    }


def write_prediction_monitoring_row(
    *,
    project_id: str,
    monitoring_dataset: str,
    serving_dir: str | Path,
    snapshot_count: int | None = None,
    first_snapshot: str | None = None,
    latest_snapshot: str | None = None,
    writer: BigQueryWriter | None = None,
) -> dict[str, Any]:
    row = build_prediction_monitoring_row(
        serving_dir=serving_dir,
        snapshot_count=snapshot_count,
        first_snapshot=first_snapshot,
        latest_snapshot=latest_snapshot,
    )
    active_writer = writer or BigQueryWriter(project_id)
    active_writer.append_rows(
        f"{project_id}.{monitoring_dataset}.prediction_monitoring",
        [row],
    )
    return row


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _number(value: object) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric


def _average(values: list[float]) -> float | None:
    return float(mean(values)) if values else None


def _first_value(rows: list[dict[str, Any]], key: str) -> Any:
    for row in rows:
        value = row.get(key)
        if value is not None:
            return value
    return None


def _first_number(rows: list[dict[str, Any]], key: str) -> float | None:
    for row in rows:
        value = _number(row.get(key))
        if value is not None:
            return value
    return None


def _model_version(metrics: dict[str, Any]) -> str:
    train_window = metrics.get("train_window") or "unknown-train-window"
    threshold = metrics.get("threshold_seconds") or "unknown-threshold"
    return f"segment-risk:{train_window}:threshold-{threshold}"
