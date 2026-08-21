from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from pipeline.rolling_origin_eval import (
    SnapshotBlob,
    build_summary,
    choose_test_dates,
    parse_snapshot_timestamp,
    select_snapshot_pairs,
)


def test_parse_snapshot_timestamp_from_gcs_name():
    timestamp = parse_snapshot_timestamp(
        "realtime/trip_updates/2026-07-16/121740.pb"
    )

    assert timestamp == datetime(2026, 7, 16, 12, 17, 40, tzinfo=timezone.utc)
    assert parse_snapshot_timestamp("realtime/trip_updates/not-a-snapshot") is None


def test_select_snapshot_pairs_keeps_base_and_horizon_offsets():
    start = datetime(2026, 7, 10, 12, tzinfo=timezone.utc)
    snapshots = [
        SnapshotBlob(name=f"s{index}", timestamp=start + timedelta(minutes=5 * index))
        for index in range(8)
    ]

    selected = select_snapshot_pairs(
        snapshots,
        start=start,
        end=start + timedelta(minutes=40),
        sample_every_minutes=15,
        horizon_minutes=10,
    )

    assert selected == ["s0", "s1", "s2", "s3", "s4", "s5", "s6", "s7"]


def test_choose_test_dates_requires_training_history():
    start = datetime(2026, 7, 1, tzinfo=timezone.utc)
    snapshots = [
        SnapshotBlob(name=f"s{index}", timestamp=start + timedelta(days=index))
        for index in range(8)
    ]

    assert choose_test_dates(snapshots, train_days=3, test_days=3) == [
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
    ]


def test_build_summary_reports_mean_and_sd_for_evaluated_folds():
    summary = build_summary(
        [
            {
                "status": "evaluated",
                "model_pr_auc": 0.2,
                "baseline_pr_auc": 0.1,
                "model_precision_at_50": 0.4,
                "baseline_precision_at_50": 0.2,
                "model_precision_at_100": 0.3,
                "baseline_precision_at_100": 0.1,
                "model_recall_at_100": 0.5,
                "test_positive_rate": 0.01,
            },
            {
                "status": "evaluated",
                "model_pr_auc": 0.4,
                "baseline_pr_auc": 0.2,
                "model_precision_at_50": 0.6,
                "baseline_precision_at_50": 0.3,
                "model_precision_at_100": 0.5,
                "baseline_precision_at_100": 0.2,
                "model_recall_at_100": 0.7,
                "test_positive_rate": 0,
            },
            {"status": "skipped", "message": "empty fold"},
        ],
        parameters={"test_days": 2},
    )

    assert summary["evaluated_fold_count"] == 2
    assert summary["positive_test_fold_count"] == 1
    assert summary["skipped_fold_count"] == 1
    assert round(summary["metrics"]["model_pr_auc"]["mean"], 6) == 0.3
    assert summary["positive_test_metrics"]["model_pr_auc"]["mean"] == 0.2
    assert round(summary["metrics"]["model_precision_at_50"]["sd"], 6) == 0.141421
