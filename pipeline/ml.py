from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import joblib
import pandas as pd
from lightgbm import LGBMClassifier
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    average_precision_score,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from pipeline.backfill import read_frame
from pipeline.config import TRANSIT_TIMEZONE


MODEL_FILENAME = "segment_risk_model.joblib"
METRICS_FILENAME = "model_metrics.json"
PREDICTIONS_FILENAME = "segment_risk.json"

NUMERIC_FEATURES = [
    "current_edge_delay_seconds",
    "previous_edge_delay_seconds",
    "delay_delta_seconds",
    "rolling_mean_delay_15m",
    "rolling_max_delay_30m",
    "stop_position",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "is_peak_period",
    "downstream_delay_score",
    "affected_downstream_stops",
]
CATEGORICAL_FEATURES = ["route_id", "direction_id"]
FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES
TARGET_COLUMN = "target_delay_exceeds_threshold"


@dataclass(frozen=True)
class SegmentRiskArtifact:
    model: Pipeline
    threshold_seconds: int
    metrics: dict[str, Any]


@dataclass(frozen=True)
class SplitResult:
    train: pd.DataFrame
    test: pd.DataFrame
    time_split: bool
    train_window: str
    test_window: str


def build_training_frame(
    current_network: list[dict[str, Any]],
    periods: int = 96,
    threshold_seconds: int = 180,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    ordered_edges = sorted(current_network, key=lambda row: str(row.get("edge_id", "")))
    for edge_index, edge in enumerate(ordered_edges):
        base_delay = int(edge.get("edge_delay_seconds") or 0)
        route_id = str(edge.get("route_id") or "unknown")
        edge_id = str(edge.get("edge_id") or f"edge-{edge_index}")
        direction_id = str(edge.get("direction_id", 0))
        stop_position = int(edge.get("stop_position") or edge_index + 1)
        previous_delay = max(0, base_delay - 45)
        delay_history: list[int] = []

        for period in range(periods):
            hour = period % 24
            day = (period // 24) % 7
            commute_pressure = 90 if hour in {7, 8, 16, 17, 18} else 0
            weekly_pressure = 35 if day in {1, 2, 3} else 0
            wave = ((period * 37 + edge_index * 23) % 140) - 55
            current_delay = max(0, base_delay + commute_pressure + weekly_pressure + wave)
            trend = current_delay - previous_delay
            downstream = max(0, current_delay - 30 + edge_index * 25)
            downstream_score = downstream + max(0, edge_index * 10)
            affected_downstream_stops = max(1, edge_index + 1) if downstream_score > 0 else 0
            next_delay = current_delay + (0.65 * trend) + (0.35 * downstream) + commute_pressure
            recent_15m = [*delay_history[-2:], current_delay]
            recent_30m = [*delay_history[-5:], current_delay]

            rows.append(
                {
                    "sample_index": period,
                    "route_id": route_id,
                    "edge_id": edge_id,
                    "direction_id": direction_id,
                    "hour_of_day": hour,
                    "day_of_week": day,
                    "is_weekend": int(day >= 5),
                    "is_peak_period": int(hour in {7, 8, 16, 17, 18}),
                    "stop_position": stop_position,
                    "current_edge_delay_seconds": current_delay,
                    "previous_edge_delay_seconds": previous_delay,
                    "delay_delta_seconds": current_delay - previous_delay,
                    "rolling_mean_delay_15m": sum(recent_15m) / len(recent_15m),
                    "rolling_max_delay_30m": max(recent_30m),
                    "downstream_delay_score": downstream_score,
                    "affected_downstream_stops": affected_downstream_stops,
                    "current_delay_seconds": current_delay,
                    "previous_delay_seconds": previous_delay,
                    "downstream_congestion_seconds": downstream,
                    TARGET_COLUMN: int(next_delay > threshold_seconds),
                }
            )
            delay_history.append(current_delay)
            previous_delay = current_delay
    return pd.DataFrame(rows)


def train_segment_risk_model(
    training_frame: pd.DataFrame,
    threshold_seconds: int = 180,
    threshold_probability: float = 0.5,
    prediction_horizon_minutes: int = 10,
    embargo_minutes: int = 0,
) -> SegmentRiskArtifact:
    if training_frame[TARGET_COLUMN].nunique() < 2:
        raise ValueError("Training data must contain both positive and negative target classes")

    frame = _ensure_feature_columns(training_frame)
    split = _time_ordered_split(frame, embargo_minutes=embargo_minutes)
    train = split.train
    test = split.test
    if train.empty or test.empty:
        raise ValueError("Training data must contain enough rows for a time-ordered split")

    model = build_segment_risk_pipeline()
    model.fit(train[FEATURE_COLUMNS], train[TARGET_COLUMN])

    probabilities = model.predict_proba(test[FEATURE_COLUMNS])[:, 1]
    predictions = (probabilities >= threshold_probability).astype(int)
    baseline_scores = (test["current_edge_delay_seconds"] / threshold_seconds).clip(0, 1)
    baseline_predictions = (test["current_edge_delay_seconds"] > threshold_seconds).astype(int)

    metrics = {
        "positive_rate": float(frame[TARGET_COLUMN].mean()),
        "precision": float(precision_score(test[TARGET_COLUMN], predictions, zero_division=0)),
        "recall": float(recall_score(test[TARGET_COLUMN], predictions, zero_division=0)),
        "f1": float(f1_score(test[TARGET_COLUMN], predictions, zero_division=0)),
        "roc_auc": _safe_auc(test[TARGET_COLUMN], probabilities),
        "pr_auc": _safe_pr_auc(test[TARGET_COLUMN], probabilities),
        "baseline_precision": float(
            precision_score(test[TARGET_COLUMN], baseline_predictions, zero_division=0)
        ),
        "baseline_recall": float(
            recall_score(test[TARGET_COLUMN], baseline_predictions, zero_division=0)
        ),
        "baseline_f1": float(
            f1_score(test[TARGET_COLUMN], baseline_predictions, zero_division=0)
        ),
        "baseline_roc_auc": _safe_auc(test[TARGET_COLUMN], baseline_scores),
        "baseline_pr_auc": _safe_pr_auc(test[TARGET_COLUMN], baseline_scores),
        "threshold_probability": float(threshold_probability),
        "threshold_seconds": float(threshold_seconds),
        "training_rows": float(len(training_frame)),
        "time_split": split.time_split,
        "train_window": split.train_window,
        "test_window": split.test_window,
        "prediction_horizon_minutes": float(prediction_horizon_minutes),
        "embargo_minutes": float(embargo_minutes),
    }
    return SegmentRiskArtifact(model=model, threshold_seconds=threshold_seconds, metrics=metrics)


def build_segment_risk_pipeline() -> Pipeline:
    preprocessor = ColumnTransformer(
        transformers=[
            ("numeric", "passthrough", NUMERIC_FEATURES),
            ("categorical", OneHotEncoder(handle_unknown="ignore"), CATEGORICAL_FEATURES),
        ]
    )
    return Pipeline(
        steps=[
            ("features", preprocessor),
            (
                "model",
                LGBMClassifier(
                    n_estimators=80,
                    learning_rate=0.08,
                    max_depth=4,
                    min_child_samples=5,
                    random_state=42,
                    verbose=-1,
                ),
            ),
        ]
    )


def train_segment_risk_from_file(
    training_path: str | Path,
    output_dir: str | Path = "data/ml",
    threshold_seconds: int = 180,
    threshold_probability: float = 0.5,
    prediction_horizon_minutes: int = 10,
    embargo_minutes: int = 0,
) -> SegmentRiskArtifact:
    training_frame = read_frame(training_path)
    artifact = train_segment_risk_model(
        training_frame,
        threshold_seconds=threshold_seconds,
        threshold_probability=threshold_probability,
        prediction_horizon_minutes=prediction_horizon_minutes,
        embargo_minutes=embargo_minutes,
    )
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    save_segment_risk_artifact(artifact, output_path / MODEL_FILENAME)
    (output_path / METRICS_FILENAME).write_text(
        json.dumps(artifact.metrics, indent=2),
        encoding="utf-8",
    )
    return artifact


def predict_segment_risk(
    artifact: SegmentRiskArtifact,
    current_network: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    prediction_frame = build_prediction_frame(current_network)
    probabilities = artifact.model.predict_proba(prediction_frame[FEATURE_COLUMNS])[:, 1]
    prediction_frame = prediction_frame.copy()
    prediction_frame["model_risk_probability"] = probabilities
    prediction_frame["risk_probability"] = _propagate_route_risk(prediction_frame)
    rows: list[dict[str, Any]] = []
    generated_at = datetime.utcnow().isoformat() + "Z"
    for row in prediction_frame.to_dict("records"):
        probability = float(row["risk_probability"])
        model_probability = float(row["model_risk_probability"])
        rows.append(
            {
                "generated_at": generated_at,
                "route_id": row["route_id"],
                "edge_id": row["edge_id"],
                "direction_id": row["direction_id"],
                "risk_probability": round(probability, 4),
                "model_risk_probability": round(model_probability, 4),
                "risk_label": _risk_label(probability),
                "threshold_seconds": artifact.threshold_seconds,
                "current_delay_seconds": row["current_edge_delay_seconds"],
                "previous_delay_seconds": row["previous_edge_delay_seconds"],
                "current_edge_delay_seconds": row["current_edge_delay_seconds"],
                "previous_edge_delay_seconds": row["previous_edge_delay_seconds"],
                "delay_delta_seconds": row["delay_delta_seconds"],
                "rolling_mean_delay_15m": round(float(row["rolling_mean_delay_15m"]), 2),
                "rolling_max_delay_30m": row["rolling_max_delay_30m"],
                "downstream_delay_score": row["downstream_delay_score"],
                "affected_downstream_stops": row["affected_downstream_stops"],
                "model_roc_auc": artifact.metrics["roc_auc"],
                "baseline_roc_auc": artifact.metrics["baseline_roc_auc"],
            }
        )
    return rows


def build_prediction_frame(current_network: list[dict[str, Any]]) -> pd.DataFrame:
    ordered_edges = sorted(
        current_network,
        key=lambda row: (
            str(row.get("route_id") or "unknown"),
            str(row.get("direction_id", 0)),
            int(row.get("stop_position") or row.get("src_stop_sequence") or 0),
            str(row.get("edge_id", "")),
        ),
    )
    rows: list[dict[str, Any]] = []
    for index, row in enumerate(ordered_edges):
        current_delay = int(row.get("edge_delay_seconds") or 0)
        previous_delay = int(
            row.get("previous_edge_delay_seconds")
            or row.get("previous_delay_seconds")
            or row.get("src_delay_seconds")
            or current_delay
        )
        feed_timestamp = pd.to_datetime(row.get("feed_timestamp"), utc=True, errors="coerce")
        local_hour, local_day = _local_temporal_features(feed_timestamp)
        rows.append(
            {
                "route_id": str(row.get("route_id") or "unknown"),
                "edge_id": str(row.get("edge_id") or f"edge-{index}"),
                "direction_id": str(row.get("direction_id", 0)),
                "hour_of_day": local_hour,
                "day_of_week": local_day,
                "is_weekend": int(local_day >= 5),
                "is_peak_period": int(_is_peak_period(local_hour)),
                "stop_position": int(row.get("stop_position") or index + 1),
                "current_edge_delay_seconds": current_delay,
                "previous_edge_delay_seconds": previous_delay,
                "delay_delta_seconds": current_delay - previous_delay,
                "rolling_mean_delay_15m": float(row.get("rolling_mean_delay_15m") or current_delay),
                "rolling_max_delay_30m": int(row.get("rolling_max_delay_30m") or current_delay),
                "downstream_delay_score": int(row.get("downstream_delay_score") or current_delay),
                "affected_downstream_stops": int(
                    row.get("affected_downstream_stops") or int(current_delay > 0)
                ),
                "current_delay_seconds": current_delay,
                "previous_delay_seconds": previous_delay,
                "downstream_congestion_seconds": current_delay,
            }
        )
    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    frame = _add_downstream_prediction_features(frame)
    return frame


def save_segment_risk_artifact(artifact: SegmentRiskArtifact, path: str | Path) -> None:
    joblib.dump(
        {
            "model": artifact.model,
            "threshold_seconds": artifact.threshold_seconds,
            "metrics": artifact.metrics,
        },
        path,
    )


def write_segment_risk_serving_outputs(
    current_network: list[dict[str, Any]],
    output_dir: str | Path,
) -> SegmentRiskArtifact:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    training_frame = build_training_frame(current_network)
    artifact = train_segment_risk_model(training_frame)
    save_segment_risk_artifact(artifact, output_path / MODEL_FILENAME)
    (output_path / METRICS_FILENAME).write_text(
        json.dumps(artifact.metrics, indent=2),
        encoding="utf-8",
    )
    (output_path / PREDICTIONS_FILENAME).write_text(
        json.dumps(predict_segment_risk(artifact, current_network), indent=2),
        encoding="utf-8",
    )
    return artifact


def train_main() -> None:
    parser = argparse.ArgumentParser(
        description="Train and evaluate the segment-risk model from real backfill examples."
    )
    parser.add_argument("--input", default="data/ml/segment_training.parquet")
    parser.add_argument("--output-dir", default="data/ml")
    parser.add_argument("--threshold-seconds", type=int, default=180)
    parser.add_argument("--threshold-probability", type=float, default=0.5)
    parser.add_argument("--prediction-horizon-minutes", type=int, default=10)
    parser.add_argument("--embargo-minutes", type=int, default=0)
    args = parser.parse_args()
    artifact = train_segment_risk_from_file(
        args.input,
        output_dir=args.output_dir,
        threshold_seconds=args.threshold_seconds,
        threshold_probability=args.threshold_probability,
        prediction_horizon_minutes=args.prediction_horizon_minutes,
        embargo_minutes=args.embargo_minutes,
    )
    print(json.dumps(artifact.metrics, indent=2))


def load_segment_risk_artifact(path: str | Path) -> SegmentRiskArtifact:
    payload = joblib.load(path)
    return SegmentRiskArtifact(
        model=payload["model"],
        threshold_seconds=int(payload["threshold_seconds"]),
        metrics=payload["metrics"],
    )


def _safe_auc(target: pd.Series, scores: pd.Series | list[float]) -> float:
    if target.nunique() < 2:
        return 0.5
    return float(roc_auc_score(target, scores))


def _safe_pr_auc(target: pd.Series, scores: pd.Series | list[float]) -> float:
    if target.nunique() < 2:
        return float(target.mean())
    return float(average_precision_score(target, scores))


def _ensure_feature_columns(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    if "current_edge_delay_seconds" not in prepared.columns:
        prepared["current_edge_delay_seconds"] = _first_available_series(
            prepared,
            ["current_delay_seconds", "edge_delay_seconds"],
            0,
        )
    if "previous_edge_delay_seconds" not in prepared.columns:
        prepared["previous_edge_delay_seconds"] = _first_available_series(
            prepared,
            ["previous_delay_seconds", "current_edge_delay_seconds"],
            0,
        )
    if "delay_delta_seconds" not in prepared.columns:
        prepared["delay_delta_seconds"] = (
            prepared["current_edge_delay_seconds"] - prepared["previous_edge_delay_seconds"]
        )
    if "rolling_mean_delay_15m" not in prepared.columns:
        prepared["rolling_mean_delay_15m"] = prepared["current_edge_delay_seconds"]
    if "rolling_max_delay_30m" not in prepared.columns:
        prepared["rolling_max_delay_30m"] = prepared["current_edge_delay_seconds"]
    if "hour_of_day" not in prepared.columns or "day_of_week" not in prepared.columns:
        hours: list[int] = []
        days: list[int] = []
        for value in prepared.get("feed_timestamp", pd.Series([pd.NaT] * len(prepared))):
            hour, day = _local_temporal_features(value)
            hours.append(hour)
            days.append(day)
        prepared["hour_of_day"] = prepared.get("hour_of_day", pd.Series(hours, index=prepared.index))
        prepared["day_of_week"] = prepared.get("day_of_week", pd.Series(days, index=prepared.index))
    if "is_weekend" not in prepared.columns:
        prepared["is_weekend"] = (prepared["day_of_week"].astype(int) >= 5).astype(int)
    if "is_peak_period" not in prepared.columns:
        prepared["is_peak_period"] = prepared["hour_of_day"].astype(int).map(_is_peak_period).astype(int)
    if "stop_position" not in prepared.columns:
        prepared["stop_position"] = 0
    if "downstream_delay_score" not in prepared.columns:
        prepared["downstream_delay_score"] = _first_available_series(
            prepared,
            ["downstream_congestion_seconds", "current_edge_delay_seconds"],
            0,
        )
    if "affected_downstream_stops" not in prepared.columns:
        prepared["affected_downstream_stops"] = (
            prepared["downstream_delay_score"].astype(float) > 0
        ).astype(int)

    for column in NUMERIC_FEATURES:
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce").fillna(0)
    for column in CATEGORICAL_FEATURES:
        if column not in prepared.columns:
            prepared[column] = "unknown"
        prepared[column] = prepared[column].fillna("unknown").astype(str)
    return prepared


def _first_available_series(
    frame: pd.DataFrame,
    columns: list[str],
    default: int | float,
) -> pd.Series:
    for column in columns:
        if column in frame.columns:
            return pd.to_numeric(frame[column], errors="coerce").fillna(default)
    return pd.Series([default] * len(frame), index=frame.index)


def _local_temporal_features(value: Any) -> tuple[int, int]:
    if pd.isna(value):
        return 0, 0
    timestamp = pd.to_datetime(value, utc=True)
    local_timestamp = timestamp.tz_convert(ZoneInfo(TRANSIT_TIMEZONE))
    return int(local_timestamp.hour), int(local_timestamp.dayofweek)


def _is_peak_period(hour: int) -> bool:
    return hour in {7, 8, 16, 17, 18}


def _time_ordered_split(frame: pd.DataFrame, embargo_minutes: int = 0) -> SplitResult:
    if "feed_timestamp" in frame.columns:
        frame["feed_timestamp"] = pd.to_datetime(frame["feed_timestamp"], utc=True)
        frame = frame.sort_values("feed_timestamp")
        timestamps = sorted(frame["feed_timestamp"].dropna().unique())
        if len(timestamps) > 1:
            split_timestamp = timestamps[max(0, int(len(timestamps) * 0.7) - 1)]
            train = frame[frame["feed_timestamp"] <= split_timestamp]
            test_start = pd.to_datetime(split_timestamp, utc=True) + pd.Timedelta(
                minutes=embargo_minutes
            )
            test = frame[frame["feed_timestamp"] > test_start]
            return SplitResult(
                train=train,
                test=test,
                time_split=True,
                train_window=_window_label(train),
                test_window=_window_label(test),
            )

    if "sample_index" in frame.columns:
        frame = frame.sort_values("sample_index")
        split_index = int(frame["sample_index"].max() * 0.7)
        train = frame[frame["sample_index"] <= split_index]
        test = frame[frame["sample_index"] > split_index]
        return SplitResult(
            train=train,
            test=test,
            time_split=True,
            train_window=_window_label(train),
            test_window=_window_label(test),
        )

    split_row = int(len(frame) * 0.7)
    train = frame.iloc[:split_row]
    test = frame.iloc[split_row:]
    return SplitResult(
        train=train,
        test=test,
        time_split=False,
        train_window=_window_label(train),
        test_window=_window_label(test),
    )


def _window_label(frame: pd.DataFrame) -> str:
    if frame.empty:
        return "empty"
    if "feed_timestamp" in frame.columns and frame["feed_timestamp"].notna().any():
        timestamps = pd.to_datetime(frame["feed_timestamp"], utc=True)
        return f"{timestamps.min().isoformat()} to {timestamps.max().isoformat()}"
    if "sample_index" in frame.columns:
        return f"sample_index {int(frame['sample_index'].min())} to {int(frame['sample_index'].max())}"
    return f"rows {int(frame.index.min())} to {int(frame.index.max())}"


def _add_downstream_prediction_features(frame: pd.DataFrame) -> pd.DataFrame:
    prepared = frame.copy()
    congestion = pd.Series(index=prepared.index, dtype="int64")
    scores = pd.Series(index=prepared.index, dtype="int64")
    affected = pd.Series(index=prepared.index, dtype="int64")
    grouped = frame.sort_values("stop_position").groupby(
        ["route_id", "direction_id"],
        sort=False,
    )
    for _key, group in grouped:
        ordered = group.sort_values("stop_position")
        downstream_delays = ordered["current_edge_delay_seconds"].astype(int).iloc[::-1]
        congestion.loc[ordered.index] = downstream_delays.cummax().iloc[::-1].astype(int)
        scores.loc[ordered.index] = downstream_delays.cumsum().iloc[::-1].astype(int)
        affected.loc[ordered.index] = (
            (downstream_delays > 0).astype(int).cumsum().iloc[::-1].astype(int)
        )
    prepared["downstream_congestion_seconds"] = congestion.astype(int)
    prepared["downstream_delay_score"] = scores.astype(int)
    prepared["affected_downstream_stops"] = affected.astype(int)
    return prepared


def _propagate_route_risk(frame: pd.DataFrame) -> pd.Series:
    values = pd.Series(index=frame.index, dtype="float64")
    grouped = frame.sort_values("stop_position").groupby(
        ["route_id", "direction_id"],
        sort=False,
    )
    for _key, group in grouped:
        ordered = group.sort_values("stop_position")
        values.loc[ordered.index] = ordered["model_risk_probability"].cummax()
    return values.astype(float)


def _risk_label(probability: float) -> str:
    if probability >= 0.75:
        return "high"
    if probability >= 0.5:
        return "medium"
    return "low"
