from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from pipeline.backfill import read_frame
from pipeline.config import TRANSIT_TIMEZONE


PERIODS = {
    "overnight": range(0, 6),
    "morning_peak": range(6, 10),
    "midday": range(10, 15),
    "evening_peak": range(15, 19),
    "night": range(19, 24),
}


def build_coverage_report(
    stop_updates_path: str | Path,
    training_path: str | Path | None = None,
) -> dict[str, Any]:
    stop_updates = read_frame(stop_updates_path)
    stop_updates["feed_timestamp"] = pd.to_datetime(stop_updates["feed_timestamp"], utc=True)
    timestamps = stop_updates["feed_timestamp"].dropna().drop_duplicates().sort_values()
    local_timestamps = _to_local(timestamps)
    report: dict[str, Any] = {
        "stop_updates": {
            "rows": int(len(stop_updates)),
            "snapshots": int(len(timestamps)),
            "start": _iso_or_none(timestamps.min() if len(timestamps) else None),
            "end": _iso_or_none(timestamps.max() if len(timestamps) else None),
            "timezone": TRANSIT_TIMEZONE,
            "unique_service_dates": (
                int(local_timestamps.dt.date.nunique()) if len(local_timestamps) else 0
            ),
            "weekday_names": (
                _counts(local_timestamps.dt.day_name()) if len(local_timestamps) else {}
            ),
            "hour_coverage": _counts(local_timestamps.dt.hour) if len(local_timestamps) else {},
            "period_coverage": _period_counts(local_timestamps) if len(local_timestamps) else {},
            "routes": int(stop_updates["route_id"].nunique()),
            "trips": int(stop_updates["trip_id"].nunique()),
        }
    }

    if training_path and Path(training_path).exists():
        training = read_frame(training_path)
        if not training.empty:
            training["feed_timestamp"] = pd.to_datetime(training["feed_timestamp"], utc=True)
            local_training_timestamps = _to_local(training["feed_timestamp"])
            report["training"] = {
                "rows": int(len(training)),
                "routes": int(training["route_id"].nunique()),
                "segments": int(training["edge_id"].nunique()),
                "positive_targets": int(training["target_delay_exceeds_threshold"].sum()),
                "negative_targets": int(
                    len(training) - training["target_delay_exceeds_threshold"].sum()
                ),
                "timezone": TRANSIT_TIMEZONE,
                "weekday_names": _counts(local_training_timestamps.dt.day_name()),
                "hour_coverage": _counts(local_training_timestamps.dt.hour),
                "period_coverage": _period_counts(local_training_timestamps),
            }
        else:
            report["training"] = {"rows": 0}

    report["recommendation"] = _recommendation(report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Report time/day coverage for MBTA backfill and training data."
    )
    parser.add_argument("--stop-updates", default="data/processed/stop_updates.parquet")
    parser.add_argument("--training", default="data/ml/segment_training.parquet")
    parser.add_argument("--output")
    args = parser.parse_args()

    report = build_coverage_report(args.stop_updates, args.training)
    body = json.dumps(report, indent=2)
    if args.output:
        Path(args.output).parent.mkdir(parents=True, exist_ok=True)
        Path(args.output).write_text(body, encoding="utf-8")
    print(body)


def _counts(series: pd.Series) -> dict[str, int]:
    return {str(key): int(value) for key, value in series.value_counts().sort_index().items()}


def _period_counts(timestamps: pd.Series) -> dict[str, int]:
    hours = pd.to_datetime(timestamps).dt.hour
    return {
        name: int(hours.isin(list(hour_range)).sum())
        for name, hour_range in PERIODS.items()
    }


def _to_local(timestamps: pd.Series) -> pd.Series:
    return pd.to_datetime(timestamps, utc=True).dt.tz_convert(ZoneInfo(TRANSIT_TIMEZONE))


def _recommendation(report: dict[str, Any]) -> str:
    stop_updates = report["stop_updates"]
    unique_days = stop_updates["unique_service_dates"]
    periods = stop_updates["period_coverage"]
    covered_periods = sum(1 for count in periods.values() if count > 0)
    weekdays = set(stop_updates["weekday_names"])
    has_weekend = bool(weekdays & {"Saturday", "Sunday"})
    has_weekday = bool(weekdays - {"Saturday", "Sunday"})
    if unique_days < 7 or covered_periods < 4 or not (has_weekday and has_weekend):
        return (
            "Collect more snapshots across weekdays, weekends, morning peak, midday, "
            "evening peak, night, and overnight before treating model metrics as reliable."
        )
    if unique_days < 14:
        return "Usable for pipeline validation; collect 2-4 weeks for portfolio-grade evaluation."
    return "Coverage is broad enough for a credible first model evaluation."


def _iso_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return pd.to_datetime(value, utc=True).isoformat()


if __name__ == "__main__":
    main()
