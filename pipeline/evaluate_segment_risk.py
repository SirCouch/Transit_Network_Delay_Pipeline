from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.calibration import calibration_curve
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.pipeline import Pipeline

from pipeline.backfill import read_frame
from pipeline.ml import (
    FEATURE_COLUMNS,
    TARGET_COLUMN,
    build_segment_risk_pipeline,
    load_segment_risk_artifact,
    _ensure_feature_columns,
    _time_ordered_split,
    _window_label,
)


@dataclass(frozen=True)
class CalibrationSplit:
    model_train: pd.DataFrame
    calibration: pd.DataFrame
    test: pd.DataFrame


def evaluate_main() -> None:
    parser = argparse.ArgumentParser(
        description="Evaluate segment-risk thresholds, top-K ranking, and calibration."
    )
    parser.add_argument("--input", default="data/ml/segment_training_generalization.parquet")
    parser.add_argument("--model", default="data/ml/generalization/segment_risk_model.joblib")
    parser.add_argument("--output-dir", default="data/ml/generalization/evaluation")
    parser.add_argument("--threshold-seconds", type=int, default=180)
    parser.add_argument("--embargo-minutes", type=int, default=10)
    parser.add_argument("--calibration-bins", type=int, default=10)
    args = parser.parse_args()

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    frame = _ensure_feature_columns(read_frame(args.input))
    artifact = load_segment_risk_artifact(args.model)
    split = _time_ordered_split(frame, embargo_minutes=args.embargo_minutes)
    test = split.test
    if test.empty:
        raise ValueError("Held-out test split is empty")

    target = test[TARGET_COLUMN].astype(int)
    model_scores = artifact.model.predict_proba(test[FEATURE_COLUMNS])[:, 1]
    baseline_scores = (test["current_edge_delay_seconds"] / args.threshold_seconds).clip(0, 1)

    threshold_rows = threshold_sweep(target, model_scores)
    threshold_frame = pd.DataFrame(threshold_rows)
    threshold_frame.to_csv(output_dir / "threshold_sweep.csv", index=False)

    topk_metrics = build_topk_metrics(target, model_scores, baseline_scores)
    (output_dir / "topk_metrics.json").write_text(
        json.dumps(topk_metrics, indent=2),
        encoding="utf-8",
    )

    calibration = build_calibration_report(
        frame,
        existing_model=artifact.model,
        threshold_seconds=args.threshold_seconds,
        embargo_minutes=args.embargo_minutes,
        bins=args.calibration_bins,
    )
    (output_dir / "calibration.json").write_text(
        json.dumps(calibration, indent=2),
        encoding="utf-8",
    )
    pd.DataFrame(calibration["curve"]).to_csv(output_dir / "calibration_curve.csv", index=False)

    summary = {
        "test_rows": int(len(test)),
        "test_positive_rate": float(target.mean()),
        "train_window": split.train_window,
        "test_window": split.test_window,
        "best_f1_threshold": max(threshold_rows, key=lambda row: row["f1"]),
        "topk": topk_metrics,
        "brier": calibration["brier"],
        "outputs": {
            "threshold_sweep": str((output_dir / "threshold_sweep.csv").resolve()),
            "topk_metrics": str((output_dir / "topk_metrics.json").resolve()),
            "calibration": str((output_dir / "calibration.json").resolve()),
            "calibration_curve": str((output_dir / "calibration_curve.csv").resolve()),
        },
    }
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def threshold_sweep(target: Any, scores: Any) -> list[dict[str, Any]]:
    target = pd.Series(target).astype(int)
    scores = pd.Series(scores)
    rows: list[dict[str, Any]] = []
    total = len(target)
    for step in range(1, 51):
        threshold = step / 100
        predictions = (scores >= threshold).astype(int)
        flagged = int(predictions.sum())
        rows.append(
            {
                "threshold": round(threshold, 2),
                "precision": float(precision_score(target, predictions, zero_division=0)),
                "recall": float(recall_score(target, predictions, zero_division=0)),
                "f1": float(f1_score(target, predictions, zero_division=0)),
                "flagged_segment_count": flagged,
                "flagged_percentage": float(flagged / total) if total else 0.0,
            }
        )
    return rows


def build_topk_metrics(
    target: Any,
    model_scores: Any,
    baseline_scores: Any,
) -> dict[str, Any]:
    target = pd.Series(target).astype(int)
    return {
        "model": {
            "precision_at_25": precision_at_k(target, model_scores, 25),
            "precision_at_50": precision_at_k(target, model_scores, 50),
            "precision_at_100": precision_at_k(target, model_scores, 100),
            "recall_at_100": recall_at_k(target, model_scores, 100),
        },
        "persistence": {
            "precision_at_50": precision_at_k(target, baseline_scores, 50),
            "precision_at_100": precision_at_k(target, baseline_scores, 100),
        },
    }


def precision_at_k(target: pd.Series, scores: Any, k: int) -> float:
    top_target = _top_k_target(target, scores, k)
    if top_target.empty:
        return 0.0
    return float(top_target.mean())


def recall_at_k(target: pd.Series, scores: Any, k: int) -> float:
    positives = int(target.sum())
    if positives == 0:
        return 0.0
    return float(_top_k_target(target, scores, k).sum() / positives)


def build_calibration_report(
    frame: pd.DataFrame,
    existing_model: Pipeline,
    threshold_seconds: int,
    embargo_minutes: int,
    bins: int,
) -> dict[str, Any]:
    frame = _ensure_feature_columns(frame)
    split = _calibration_split(frame, embargo_minutes=embargo_minutes)
    existing_raw_scores = existing_model.predict_proba(split.test[FEATURE_COLUMNS])[:, 1]

    model = build_segment_risk_pipeline()
    model.fit(split.model_train[FEATURE_COLUMNS], split.model_train[TARGET_COLUMN])

    calibration_scores = model.predict_proba(split.calibration[FEATURE_COLUMNS])[:, 1]
    calibration_target = split.calibration[TARGET_COLUMN].astype(int)
    test_scores = model.predict_proba(split.test[FEATURE_COLUMNS])[:, 1]
    test_target = split.test[TARGET_COLUMN].astype(int)

    platt = LogisticRegression(max_iter=1000)
    platt.fit(pd.DataFrame({"score": calibration_scores}), calibration_target)
    platt_scores = platt.predict_proba(pd.DataFrame({"score": test_scores}))[:, 1]

    isotonic = IsotonicRegression(out_of_bounds="clip")
    isotonic.fit(calibration_scores, calibration_target)
    isotonic_scores = isotonic.predict(test_scores)

    curve_prob_true, curve_prob_pred = calibration_curve(
        test_target,
        existing_raw_scores,
        n_bins=bins,
        strategy="quantile",
    )
    baseline_scores = (split.test["current_edge_delay_seconds"] / threshold_seconds).clip(0, 1)
    return {
        "split": {
            "model_train_window": _window_label(split.model_train),
            "calibration_window": _window_label(split.calibration),
            "test_window": _window_label(split.test),
        },
        "brier": {
            "raw_existing_model": float(brier_score_loss(test_target, existing_raw_scores)),
            "raw_retrained_model": float(brier_score_loss(test_target, test_scores)),
            "platt": float(brier_score_loss(test_target, platt_scores)),
            "isotonic": float(brier_score_loss(test_target, isotonic_scores)),
            "persistence": float(brier_score_loss(test_target, baseline_scores)),
        },
        "curve": [
            {
                "bin": index + 1,
                "mean_predicted_probability": float(predicted),
                "observed_positive_rate": float(observed),
            }
            for index, (predicted, observed) in enumerate(zip(curve_prob_pred, curve_prob_true))
        ],
    }


def _top_k_target(target: pd.Series, scores: Any, k: int) -> pd.Series:
    frame = pd.DataFrame({"target": target.to_numpy(), "score": pd.Series(scores).to_numpy()})
    return frame.sort_values("score", ascending=False).head(k)["target"]


def _calibration_split(frame: pd.DataFrame, embargo_minutes: int) -> CalibrationSplit:
    prepared = frame.copy()
    prepared["feed_timestamp"] = pd.to_datetime(prepared["feed_timestamp"], utc=True)
    prepared = prepared.sort_values("feed_timestamp")
    timestamps = sorted(prepared["feed_timestamp"].dropna().unique())
    if len(timestamps) < 3:
        raise ValueError("Calibration requires at least three distinct timestamps")

    model_train_end = timestamps[max(0, int(len(timestamps) * 0.6) - 1)]
    calibration_end = timestamps[max(0, int(len(timestamps) * 0.8) - 1)]
    calibration_start = pd.to_datetime(model_train_end, utc=True) + pd.Timedelta(
        minutes=embargo_minutes
    )
    test_start = pd.to_datetime(calibration_end, utc=True) + pd.Timedelta(
        minutes=embargo_minutes
    )

    model_train = prepared[prepared["feed_timestamp"] <= model_train_end]
    calibration = prepared[
        (prepared["feed_timestamp"] > calibration_start)
        & (prepared["feed_timestamp"] <= calibration_end)
    ]
    test = prepared[prepared["feed_timestamp"] > test_start]
    if model_train.empty or calibration.empty or test.empty:
        raise ValueError("Calibration split produced an empty model/calibration/test window")
    return CalibrationSplit(model_train=model_train, calibration=calibration, test=test)


if __name__ == "__main__":
    evaluate_main()
