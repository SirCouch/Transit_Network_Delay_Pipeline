from __future__ import annotations

import argparse
import json
import math
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd

from pipeline.config import DEFAULT_MBTA_STATIC_URL, DEFAULT_MBTA_TRIP_UPDATES_URL, TRANSIT_TIMEZONE
from pipeline.gtfs_rt import parse_trip_updates
from pipeline.gtfs_static import parse_static_feed
from pipeline.http import fetch_bytes


STOP_UPDATE_COLUMNS = [
    "feed_timestamp",
    "snapshot_path",
    "trip_id",
    "route_id",
    "start_date",
    "stop_id",
    "stop_sequence",
    "arrival_delay_seconds",
    "departure_delay_seconds",
    "best_delay_seconds",
    "predicted_arrival_time",
    "predicted_departure_time",
    "schedule_relationship",
]

TRAINING_COLUMNS = [
    "feed_timestamp",
    "route_id",
    "trip_id",
    "edge_id",
    "direction_id",
    "src_stop_id",
    "dst_stop_id",
    "hour_of_day",
    "day_of_week",
    "is_weekend",
    "is_peak_period",
    "stop_position",
    "current_edge_delay_seconds",
    "previous_edge_delay_seconds",
    "delay_delta_seconds",
    "rolling_mean_delay_15m",
    "rolling_max_delay_30m",
    "downstream_delay_score",
    "affected_downstream_stops",
    "current_delay_seconds",
    "previous_delay_seconds",
    "downstream_congestion_seconds",
    "future_delay_seconds",
    "target_delay_exceeds_threshold",
]


def collect_trip_updates_snapshot(
    output_dir: str | Path = "data/raw/mbta_rt",
    url: str = DEFAULT_MBTA_TRIP_UPDATES_URL,
    fetched_at: datetime | None = None,
) -> Path:
    payload = fetch_bytes(url)
    timestamp = _feed_timestamp(payload) or fetched_at or datetime.now(tz=timezone.utc)
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    snapshot_path = target / f"trip_updates_{_compact_timestamp(timestamp)}.pb"
    snapshot_path.write_bytes(payload)
    metadata = {
        "source_url": url,
        "feed_timestamp": timestamp.isoformat(),
        "fetched_at": (fetched_at or datetime.now(tz=timezone.utc)).isoformat(),
        "bytes": len(payload),
    }
    snapshot_path.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return snapshot_path


def collect_static_feed(
    output_path: str | Path = "data/raw/mbta_static/MBTA_GTFS.zip",
    url: str = DEFAULT_MBTA_STATIC_URL,
) -> Path:
    payload = fetch_bytes(url)
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(payload)
    metadata = {
        "source_url": url,
        "fetched_at": datetime.now(tz=timezone.utc).isoformat(),
        "bytes": len(payload),
    }
    target.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    return target


def decode_snapshot_file(path: str | Path) -> list[dict[str, Any]]:
    snapshot_path = Path(path)
    updates = parse_trip_updates(snapshot_path.read_bytes())
    rows: list[dict[str, Any]] = []
    for update in updates:
        best_delay = update.arrival_delay_seconds
        if best_delay is None:
            best_delay = update.departure_delay_seconds
        rows.append(
            {
                "feed_timestamp": update.feed_timestamp,
                "snapshot_path": str(snapshot_path),
                "trip_id": update.trip_id,
                "route_id": update.route_id,
                "start_date": update.start_date,
                "stop_id": update.stop_id,
                "stop_sequence": update.stop_sequence,
                "arrival_delay_seconds": update.arrival_delay_seconds,
                "departure_delay_seconds": update.departure_delay_seconds,
                "best_delay_seconds": best_delay,
                "predicted_arrival_time": update.predicted_arrival_time,
                "predicted_departure_time": update.predicted_departure_time,
                "schedule_relationship": update.schedule_relationship,
            }
        )
    return rows


def decode_snapshot_dir(
    input_dir: str | Path,
    output_path: str | Path,
    max_snapshots: int | None = None,
    snapshot_stride: int = 1,
    sample_every_minutes: int | None = None,
    include_offsets_minutes: list[int] | None = None,
) -> pd.DataFrame:
    snapshots = list_snapshot_paths(
        input_dir,
        max_snapshots=max_snapshots,
        snapshot_stride=snapshot_stride,
        sample_every_minutes=sample_every_minutes,
        include_offsets_minutes=include_offsets_minutes,
    )
    rows: list[dict[str, Any]] = []
    for snapshot in snapshots:
        rows.extend(decode_snapshot_file(snapshot))
    frame = pd.DataFrame(rows, columns=STOP_UPDATE_COLUMNS)
    write_frame(frame, output_path)
    return frame


def list_snapshot_paths(
    input_dir: str | Path,
    max_snapshots: int | None = None,
    snapshot_stride: int = 1,
    sample_every_minutes: int | None = None,
    include_offsets_minutes: list[int] | None = None,
) -> list[Path]:
    if snapshot_stride < 1:
        raise ValueError("snapshot_stride must be >= 1")
    snapshots = sorted(Path(input_dir).rglob("*.pb"))
    if sample_every_minutes is not None:
        snapshots = _sample_snapshot_paths_by_time(
            snapshots,
            sample_every_minutes=sample_every_minutes,
            include_offsets_minutes=include_offsets_minutes or [0],
        )
    snapshots = snapshots[::snapshot_stride]
    if max_snapshots is not None:
        snapshots = snapshots[:max_snapshots]
    return snapshots


def _sample_snapshot_paths_by_time(
    snapshots: list[Path],
    sample_every_minutes: int,
    include_offsets_minutes: list[int],
) -> list[Path]:
    if sample_every_minutes < 1:
        raise ValueError("sample_every_minutes must be >= 1")
    timestamped = [
        (timestamp, path)
        for path in snapshots
        if (timestamp := _snapshot_timestamp_from_path(path)) is not None
    ]
    if not timestamped:
        return snapshots

    selected: dict[Path, None] = {}
    next_base_time: datetime | None = None
    for timestamp, path in timestamped:
        if next_base_time is not None and timestamp < next_base_time:
            continue
        for offset_minutes in include_offsets_minutes:
            target_time = timestamp + timedelta(minutes=offset_minutes)
            matched = _first_snapshot_at_or_after(timestamped, target_time)
            if matched is not None:
                selected[matched] = None
        next_base_time = timestamp + timedelta(minutes=sample_every_minutes)
    return sorted(selected)


def _first_snapshot_at_or_after(
    timestamped: list[tuple[datetime, Path]],
    target_time: datetime,
) -> Path | None:
    for timestamp, path in timestamped:
        if timestamp >= target_time:
            return path
    return None


def _snapshot_timestamp_from_path(path: Path) -> datetime | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})[\\/](\d{2})(\d{2})(\d{2})\.pb$", str(path))
    if not match:
        return None
    date_part, hour, minute, second = match.groups()
    return datetime.fromisoformat(f"{date_part}T{hour}:{minute}:{second}+00:00")


def build_segment_training_frame(
    stop_updates: pd.DataFrame,
    horizon_minutes: int = 10,
    threshold_seconds: int = 180,
    static_zip_path: str | Path | None = None,
) -> pd.DataFrame:
    if static_zip_path:
        stop_updates = enrich_stop_updates_with_static(stop_updates, static_zip_path)
    edge_states = add_edge_history_features(build_edge_state_frame(stop_updates))
    if edge_states.empty:
        return pd.DataFrame(columns=TRAINING_COLUMNS)

    examples: list[dict[str, Any]] = []
    horizon = timedelta(minutes=horizon_minutes)
    grouped = edge_states.sort_values(["edge_id", "feed_timestamp"]).groupby("edge_id")
    for _edge_id, group in grouped:
        records = group.to_dict("records")
        for index, current in enumerate(records):
            future = _first_future_record(records, index, horizon)
            if future is None:
                continue
            previous = records[index - 1] if index > 0 else current
            feed_timestamp = current["feed_timestamp"]
            local_hour, local_day = _local_temporal_features(feed_timestamp)
            current_delay = int(current["current_edge_delay_seconds"])
            previous_delay = int(previous["current_edge_delay_seconds"])
            examples.append(
                {
                    "feed_timestamp": feed_timestamp,
                    "route_id": str(current.get("route_id") or "unknown"),
                    "trip_id": current.get("trip_id"),
                    "edge_id": current["edge_id"],
                    "direction_id": str(current.get("direction_id") or "unknown"),
                    "src_stop_id": current.get("src_stop_id"),
                    "dst_stop_id": current.get("dst_stop_id"),
                    "hour_of_day": local_hour,
                    "day_of_week": local_day,
                    "is_weekend": int(local_day >= 5),
                    "is_peak_period": int(_is_peak_period(local_hour)),
                    "stop_position": int(current["stop_position"]),
                    "current_edge_delay_seconds": current_delay,
                    "previous_edge_delay_seconds": int(current["previous_edge_delay_seconds"]),
                    "delay_delta_seconds": int(current["delay_delta_seconds"]),
                    "rolling_mean_delay_15m": float(current["rolling_mean_delay_15m"]),
                    "rolling_max_delay_30m": int(current["rolling_max_delay_30m"]),
                    "downstream_delay_score": int(current["downstream_delay_score"]),
                    "affected_downstream_stops": int(current["affected_downstream_stops"]),
                    "current_delay_seconds": current_delay,
                    "previous_delay_seconds": previous_delay,
                    "downstream_congestion_seconds": int(
                        current["downstream_congestion_seconds"]
                    ),
                    "future_delay_seconds": int(future["edge_delay_seconds"]),
                    "target_delay_exceeds_threshold": int(
                        future["edge_delay_seconds"] > threshold_seconds
                    ),
                }
            )
    return pd.DataFrame(examples, columns=TRAINING_COLUMNS)


def add_edge_history_features(edge_states: pd.DataFrame) -> pd.DataFrame:
    if edge_states.empty:
        return edge_states

    frame = edge_states.copy()
    frame["feed_timestamp"] = pd.to_datetime(frame["feed_timestamp"], utc=True)
    frame["edge_delay_seconds"] = frame["edge_delay_seconds"].astype(int)
    frame["current_edge_delay_seconds"] = frame["edge_delay_seconds"]
    frame["previous_edge_delay_seconds"] = frame["edge_delay_seconds"]
    frame["delay_delta_seconds"] = 0
    frame["rolling_mean_delay_15m"] = frame["edge_delay_seconds"].astype(float)
    frame["rolling_max_delay_30m"] = frame["edge_delay_seconds"]

    for _edge_id, group in frame.sort_values("feed_timestamp").groupby("edge_id", sort=False):
        ordered = group.sort_values("feed_timestamp")
        delays = ordered["edge_delay_seconds"].astype(int)
        previous = delays.shift(1).fillna(delays).astype(int)
        indexed_delays = ordered.set_index("feed_timestamp")["edge_delay_seconds"].astype(float)
        frame.loc[ordered.index, "previous_edge_delay_seconds"] = previous.to_numpy()
        frame.loc[ordered.index, "delay_delta_seconds"] = (delays - previous).to_numpy()
        frame.loc[ordered.index, "rolling_mean_delay_15m"] = (
            indexed_delays.rolling("15min", min_periods=1).mean().to_numpy()
        )
        frame.loc[ordered.index, "rolling_max_delay_30m"] = (
            indexed_delays.rolling("30min", min_periods=1).max().astype(int).to_numpy()
        )
    return frame


def build_edge_state_frame(stop_updates: pd.DataFrame) -> pd.DataFrame:
    if stop_updates.empty:
        return pd.DataFrame()

    frame = stop_updates.copy()
    frame["feed_timestamp"] = pd.to_datetime(frame["feed_timestamp"], utc=True)
    frame = frame.dropna(subset=["feed_timestamp", "trip_id", "stop_sequence", "best_delay_seconds"])
    if frame.empty:
        return pd.DataFrame()
    frame["stop_sequence"] = frame["stop_sequence"].astype(int)
    frame["best_delay_seconds"] = frame["best_delay_seconds"].astype(int)

    rows: list[dict[str, Any]] = []
    group_columns = ["feed_timestamp", "trip_id"]
    for (_feed_timestamp, _trip_id), group in frame.groupby(group_columns):
        ordered = group.sort_values("stop_sequence").to_dict("records")
        trip_edges: list[dict[str, Any]] = []
        for src, dst in zip(ordered, ordered[1:]):
            edge_delay = max(0, int(dst["best_delay_seconds"]) - int(src["best_delay_seconds"]))
            trip_edges.append(
                {
                    "feed_timestamp": src["feed_timestamp"],
                    "route_id": src.get("route_id") or dst.get("route_id"),
                    "trip_id": src.get("trip_id"),
                    "edge_id": (
                        f"{src.get('route_id') or 'unknown'}:"
                        f"{src.get('stop_id') or src.get('stop_sequence')}:"
                        f"{dst.get('stop_id') or dst.get('stop_sequence')}"
                    ),
                    "direction_id": src.get("direction_id") or dst.get("direction_id") or "unknown",
                    "src_stop_id": src.get("stop_id"),
                    "dst_stop_id": dst.get("stop_id"),
                    "stop_position": int(src["stop_sequence"]),
                    "edge_delay_seconds": edge_delay,
                }
            )
        for index, edge in enumerate(trip_edges):
            downstream_edges = trip_edges[index:]
            downstream_delays = [item["edge_delay_seconds"] for item in downstream_edges]
            edge["downstream_congestion_seconds"] = max(
                downstream_delays
            )
            edge["downstream_delay_score"] = sum(downstream_delays)
            edge["affected_downstream_stops"] = sum(1 for delay in downstream_delays if delay > 0)
            rows.append(edge)
    return pd.DataFrame(rows)


def enrich_stop_updates_with_static(
    stop_updates: pd.DataFrame,
    static_zip_path: str | Path,
) -> pd.DataFrame:
    _stops, _routes, trips, stop_times = parse_static_feed(str(static_zip_path))
    trips_by_id = {trip.trip_id: trip for trip in trips}
    stop_times_by_key = {
        (stop_time.trip_id, int(stop_time.stop_sequence)): stop_time for stop_time in stop_times
    }

    frame = stop_updates.copy()
    frame["feed_timestamp"] = pd.to_datetime(frame["feed_timestamp"], utc=True)
    frame["predicted_arrival_time"] = pd.to_datetime(
        frame["predicted_arrival_time"], utc=True, errors="coerce"
    )
    frame["predicted_departure_time"] = pd.to_datetime(
        frame["predicted_departure_time"], utc=True, errors="coerce"
    )
    rows: list[dict[str, Any]] = []
    for row in frame.to_dict("records"):
        trip_id = row.get("trip_id")
        stop_sequence = row.get("stop_sequence")
        if pd.isna(trip_id) or pd.isna(stop_sequence):
            rows.append(row)
            continue

        trip = trips_by_id.get(str(trip_id))
        stop_time = stop_times_by_key.get((str(trip_id), int(stop_sequence)))
        if trip and not row.get("route_id"):
            row["route_id"] = trip.route_id
        row["direction_id"] = trip.direction_id if trip else None
        if stop_time is None:
            rows.append(row)
            continue

        service_date = _service_date(row.get("start_date"), row.get("feed_timestamp"))
        arrival_delay = _delay_from_prediction(
            row.get("predicted_arrival_time"),
            service_date,
            stop_time.arrival_time,
        )
        departure_delay = _delay_from_prediction(
            row.get("predicted_departure_time"),
            service_date,
            stop_time.departure_time,
        )
        if pd.isna(row.get("arrival_delay_seconds")) and arrival_delay is not None:
            row["arrival_delay_seconds"] = arrival_delay
        if pd.isna(row.get("departure_delay_seconds")) and departure_delay is not None:
            row["departure_delay_seconds"] = departure_delay
        row["best_delay_seconds"] = _first_non_null(
            row.get("arrival_delay_seconds"),
            row.get("departure_delay_seconds"),
            row.get("best_delay_seconds"),
        )
        rows.append(row)
    return pd.DataFrame(rows)


def read_frame(path: str | Path) -> pd.DataFrame:
    source = Path(path)
    if source.suffix == ".parquet":
        return pd.read_parquet(source)
    if source.suffix == ".jsonl":
        return pd.read_json(source, lines=True)
    return pd.read_csv(source)


def write_frame(frame: pd.DataFrame, path: str | Path) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.suffix == ".parquet":
        frame.to_parquet(target, index=False)
    elif target.suffix == ".jsonl":
        frame.to_json(target, orient="records", lines=True, date_format="iso")
    else:
        frame.to_csv(target, index=False)


def collect_main() -> None:
    parser = argparse.ArgumentParser(description="Fetch one MBTA TripUpdates protobuf snapshot.")
    parser.add_argument("--output-dir", default="data/raw/mbta_rt")
    parser.add_argument("--url", default=DEFAULT_MBTA_TRIP_UPDATES_URL)
    parser.add_argument("--count", type=int, default=1)
    parser.add_argument("--duration-hours", type=float)
    parser.add_argument("--interval-seconds", type=int, default=300)
    args = parser.parse_args()
    count = args.count
    if args.duration_hours:
        count = max(1, math.ceil((args.duration_hours * 3600) / args.interval_seconds))
    for index in range(count):
        path = collect_trip_updates_snapshot(args.output_dir, args.url)
        print(f"Wrote {path}")
        if index < count - 1:
            time.sleep(args.interval_seconds)


def collect_static_main() -> None:
    parser = argparse.ArgumentParser(description="Fetch the current MBTA GTFS Static zip.")
    parser.add_argument("--output", default="data/raw/mbta_static/MBTA_GTFS.zip")
    parser.add_argument("--url", default=DEFAULT_MBTA_STATIC_URL)
    args = parser.parse_args()
    path = collect_static_feed(args.output, args.url)
    print(f"Wrote {path}")


def decode_main() -> None:
    parser = argparse.ArgumentParser(description="Decode raw TripUpdates snapshots to tabular rows.")
    parser.add_argument("--input-dir", default="data/raw/mbta_rt")
    parser.add_argument("--output", default="data/processed/stop_updates.parquet")
    parser.add_argument(
        "--max-snapshots",
        type=int,
        help="Optional cap for bounded local model experiments.",
    )
    parser.add_argument(
        "--snapshot-stride",
        type=int,
        default=1,
        help="Decode every Nth snapshot after recursive sorting.",
    )
    parser.add_argument(
        "--sample-every-minutes",
        type=int,
        help="Keep one base snapshot every N minutes before applying stride/max caps.",
    )
    parser.add_argument(
        "--include-offset-minutes",
        type=int,
        action="append",
        help="For each sampled base snapshot, also keep the first snapshot at or after this offset.",
    )
    args = parser.parse_args()
    frame = decode_snapshot_dir(
        args.input_dir,
        args.output,
        max_snapshots=args.max_snapshots,
        snapshot_stride=args.snapshot_stride,
        sample_every_minutes=args.sample_every_minutes,
        include_offsets_minutes=args.include_offset_minutes,
    )
    print(f"Wrote {len(frame)} stop updates to {Path(args.output).resolve()}")


def build_training_main() -> None:
    parser = argparse.ArgumentParser(description="Build segment-risk ML examples from stop updates.")
    parser.add_argument("--input", default="data/processed/stop_updates.parquet")
    parser.add_argument("--output", default="data/ml/segment_training.parquet")
    parser.add_argument("--static-zip")
    parser.add_argument("--horizon-minutes", type=int, default=10)
    parser.add_argument("--threshold-seconds", type=int, default=180)
    args = parser.parse_args()
    stop_updates = read_frame(args.input)
    training = build_segment_training_frame(
        stop_updates,
        horizon_minutes=args.horizon_minutes,
        threshold_seconds=args.threshold_seconds,
        static_zip_path=args.static_zip,
    )
    write_frame(training, args.output)
    print(f"Wrote {len(training)} training examples to {Path(args.output).resolve()}")


def _feed_timestamp(payload: bytes) -> datetime | None:
    updates = parse_trip_updates(payload)
    return updates[0].feed_timestamp if updates else None


def _compact_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _local_temporal_features(value: Any) -> tuple[int, int]:
    timestamp = pd.to_datetime(value, utc=True)
    local_timestamp = timestamp.tz_convert(ZoneInfo(TRANSIT_TIMEZONE))
    return int(local_timestamp.hour), int(local_timestamp.dayofweek)


def _is_peak_period(hour: int) -> bool:
    return hour in {7, 8, 16, 17, 18}


def _first_future_record(
    records: list[dict[str, Any]],
    index: int,
    horizon: timedelta,
) -> dict[str, Any] | None:
    current_time = records[index]["feed_timestamp"]
    max_time = current_time + horizon
    for future in records[index + 1 :]:
        if current_time < future["feed_timestamp"] <= max_time:
            return future
        if future["feed_timestamp"] > max_time:
            return None
    return None


def _service_date(value: Any, feed_timestamp: Any) -> datetime:
    if value and not pd.isna(value):
        parsed = pd.to_datetime(value)
        return datetime(parsed.year, parsed.month, parsed.day, tzinfo=timezone.utc)
    timestamp = pd.to_datetime(feed_timestamp, utc=True)
    return datetime(timestamp.year, timestamp.month, timestamp.day, tzinfo=timezone.utc)


def _delay_from_prediction(
    predicted_time: Any,
    service_date: datetime,
    scheduled_time: str | None,
) -> int | None:
    if predicted_time is None or pd.isna(predicted_time) or not scheduled_time:
        return None
    scheduled = _scheduled_datetime(service_date, scheduled_time)
    predicted = pd.to_datetime(predicted_time, utc=True).to_pydatetime()
    return int((predicted - scheduled).total_seconds())


def _scheduled_datetime(service_date: datetime, gtfs_time: str) -> datetime:
    hours, minutes, seconds = [int(part) for part in gtfs_time.split(":")]
    return service_date + timedelta(hours=hours, minutes=minutes, seconds=seconds)


def _first_non_null(*values: Any) -> int | None:
    for value in values:
        if value is not None and not pd.isna(value):
            return int(value)
    return None
