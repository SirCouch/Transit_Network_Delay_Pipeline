from __future__ import annotations

import pandas as pd

from pipeline.ml import (
    _propagate_route_risk,
    build_prediction_frame,
    build_training_frame,
    predict_segment_risk,
    train_segment_risk_model,
)
from pipeline.evaluate_segment_risk import (
    build_calibration_report,
    build_topk_metrics,
    threshold_sweep,
)
from pipeline.runner import run_local
from tests.fixtures import build_trip_updates_payload, write_static_feed


def test_lightgbm_segment_risk_model_beats_baseline_auc(tmp_path):
    static_zip = tmp_path / "mbta_static_sample.zip"
    write_static_feed(static_zip)
    output = run_local(str(static_zip), build_trip_updates_payload())
    training_frame = build_training_frame(output.current_network)

    artifact = train_segment_risk_model(training_frame)
    predictions = predict_segment_risk(artifact, output.current_network)

    assert artifact.metrics["roc_auc"] > artifact.metrics["baseline_roc_auc"]
    assert artifact.metrics["precision"] >= 0
    assert artifact.metrics["recall"] >= 0
    assert predictions
    assert {"edge_id", "risk_probability", "model_risk_probability", "risk_label"}.issubset(
        predictions[0]
    )


def test_prediction_features_compute_downstream_delay_by_route_order():
    frame = build_prediction_frame(
        [
            {
                "route_id": "A",
                "direction_id": 0,
                "edge_id": "A:1",
                "stop_position": 1,
                "edge_delay_seconds": 5,
                "feed_timestamp": "2026-05-16T13:00:00Z",
            },
            {
                "route_id": "A",
                "direction_id": 0,
                "edge_id": "A:2",
                "stop_position": 2,
                "edge_delay_seconds": 80,
            },
            {
                "route_id": "B",
                "direction_id": 0,
                "edge_id": "B:1",
                "stop_position": 1,
                "edge_delay_seconds": 300,
            },
        ]
    )

    route_a_first = frame[(frame["route_id"] == "A") & (frame["edge_id"] == "A:1")].iloc[0]

    assert route_a_first["downstream_congestion_seconds"] == 80
    assert route_a_first["hour_of_day"] == 9
    assert route_a_first["day_of_week"] == 5


def test_route_risk_propagates_downstream_within_route_direction():
    frame = build_prediction_frame(
        [
            {
                "route_id": "A",
                "direction_id": 0,
                "edge_id": "A:1",
                "stop_position": 1,
                "edge_delay_seconds": 5,
            },
            {
                "route_id": "A",
                "direction_id": 0,
                "edge_id": "A:2",
                "stop_position": 2,
                "edge_delay_seconds": 10,
            },
        ]
    )
    frame["model_risk_probability"] = [0.9, 0.1]
    propagated = _propagate_route_risk(frame)

    assert list(propagated) == [0.9, 0.9]


def test_threshold_sweep_reports_flagged_counts_and_percentages():
    rows = threshold_sweep(
        target=[1, 0, 1, 0],
        scores=[0.9, 0.2, 0.04, 0.01],
    )
    threshold_05 = next(row for row in rows if row["threshold"] == 0.05)

    assert len(rows) == 50
    assert threshold_05["flagged_segment_count"] == 2
    assert threshold_05["flagged_percentage"] == 0.5
    assert threshold_05["precision"] == 0.5


def test_topk_metrics_compare_model_and_persistence_rankings():
    metrics = build_topk_metrics(
        target=[1, 0, 0, 1],
        model_scores=[0.9, 0.8, 0.1, 0.7],
        baseline_scores=[0.1, 0.9, 0.8, 0.7],
    )

    assert metrics["model"]["precision_at_25"] == 0.5
    assert metrics["model"]["precision_at_50"] == 0.5
    assert metrics["model"]["recall_at_100"] == 1.0
    assert metrics["persistence"]["precision_at_50"] == 0.5


def test_calibration_report_includes_brier_and_curve():
    rows = []
    start = pd.Timestamp("2026-05-12T12:00:00Z")
    for index in range(90):
        current_delay = 240 if index % 4 == 0 else 20 + index % 30
        rows.append(
            {
                "feed_timestamp": start + pd.Timedelta(minutes=5 * index),
                "route_id": "A",
                "direction_id": 0,
                "edge_id": "A:1",
                "stop_position": 1,
                "hour_of_day": int((12 + index // 12) % 24),
                "day_of_week": 1,
                "is_weekend": 0,
                "is_peak_period": 0,
                "current_edge_delay_seconds": current_delay,
                "previous_edge_delay_seconds": max(0, current_delay - 10),
                "delay_delta_seconds": 10,
                "rolling_mean_delay_15m": current_delay,
                "rolling_max_delay_30m": current_delay,
                "downstream_delay_score": current_delay,
                "affected_downstream_stops": int(current_delay > 0),
                "target_delay_exceeds_threshold": int(current_delay > 180),
            }
        )
    training_frame = pd.DataFrame(rows)
    artifact = train_segment_risk_model(training_frame, threshold_seconds=180)

    report = build_calibration_report(
        training_frame,
        existing_model=artifact.model,
        threshold_seconds=180,
        embargo_minutes=0,
        bins=5,
    )

    assert {"raw_existing_model", "platt", "isotonic", "persistence"}.issubset(report["brier"])
    assert report["curve"]
