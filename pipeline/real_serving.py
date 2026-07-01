from __future__ import annotations

import argparse
import csv
import json
import shutil
from datetime import datetime, timezone
from io import TextIOWrapper
from pathlib import Path
from typing import Any
from zipfile import ZipFile

import pandas as pd

from pipeline.backfill import (
    add_edge_history_features,
    build_edge_state_frame,
    enrich_stop_updates_with_static,
    read_frame,
)
from pipeline.gtfs_static import parse_static_feed
from pipeline.ml import (
    METRICS_FILENAME,
    MODEL_FILENAME,
    PREDICTIONS_FILENAME,
    load_segment_risk_artifact,
    predict_segment_risk,
)


def write_real_serving_outputs(
    stop_updates_path: str | Path,
    static_zip_path: str | Path,
    model_path: str | Path,
    output_dir: str | Path = "local_serving",
    max_network_rows: int = 5000,
) -> dict[str, int]:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    stop_updates = read_frame(stop_updates_path)
    enriched = enrich_stop_updates_with_static(stop_updates, static_zip_path)
    edge_states = add_edge_history_features(build_edge_state_frame(enriched))
    if edge_states.empty:
        raise ValueError("No real edge states could be built from decoded stop updates")

    latest_timestamp = edge_states["feed_timestamp"].max()
    latest_edges = edge_states[edge_states["feed_timestamp"] == latest_timestamp].copy()
    display_edges = _prepare_display_edges(latest_edges, static_zip_path)
    network_rows = _build_current_network_rows(display_edges, max_network_rows)
    bottleneck_rows = _build_current_bottleneck_rows(display_edges)
    health_row = _build_feed_health_row(latest_timestamp, len(network_rows))

    artifact = load_segment_risk_artifact(model_path)
    prediction_rows = predict_segment_risk(artifact, network_rows)

    _write_json(output_path / "current_network.json", network_rows)
    _write_json(output_path / "current_bottlenecks.json", bottleneck_rows)
    _write_json(output_path / "current_feed_health.json", health_row)
    _write_json(output_path / PREDICTIONS_FILENAME, prediction_rows)
    _write_json(output_path / METRICS_FILENAME, artifact.metrics)
    shutil.copy2(model_path, output_path / MODEL_FILENAME)

    return {
        "network_rows": len(network_rows),
        "bottleneck_rows": len(bottleneck_rows),
        "prediction_rows": len(prediction_rows),
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate local serving JSON from real MBTA backfill and trained model."
    )
    parser.add_argument("--stop-updates", default="data/processed/stop_updates.parquet")
    parser.add_argument("--static-zip", default="data/raw/mbta_static/MBTA_GTFS.zip")
    parser.add_argument("--model", default="data/ml/segment_risk_model.joblib")
    parser.add_argument("--output-dir", default="local_serving")
    parser.add_argument("--max-network-rows", type=int, default=5000)
    args = parser.parse_args()

    counts = write_real_serving_outputs(
        stop_updates_path=args.stop_updates,
        static_zip_path=args.static_zip,
        model_path=args.model,
        output_dir=args.output_dir,
        max_network_rows=args.max_network_rows,
    )
    print(json.dumps(counts, indent=2))


def _build_current_network_rows(
    latest_edges: pd.DataFrame,
    max_network_rows: int,
) -> list[dict[str, Any]]:
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    grouped = (
        latest_edges.groupby(
            [
                "route_id",
                "edge_id",
                "direction_id",
                "src_stop_id",
                "dst_stop_id",
                "src_stop_name",
                "dst_stop_name",
                "src_stop_lat",
                "src_stop_lon",
                "dst_stop_lat",
                "dst_stop_lon",
                "stop_position",
                "route_name",
                "route_type",
                "mode",
            ],
            dropna=False,
        )
        .agg(
            feed_timestamp=("feed_timestamp", "max"),
            edge_delay_seconds=("edge_delay_seconds", "max"),
            previous_edge_delay_seconds=("previous_edge_delay_seconds", "max"),
            delay_delta_seconds=("delay_delta_seconds", "max"),
            rolling_mean_delay_15m=("rolling_mean_delay_15m", "mean"),
            rolling_max_delay_30m=("rolling_max_delay_30m", "max"),
            downstream_delay_score=("downstream_delay_score", "max"),
            affected_downstream_stops=("affected_downstream_stops", "max"),
            avg_edge_delay_seconds=("edge_delay_seconds", "mean"),
            trip_count=("trip_id", "nunique"),
        )
        .reset_index()
        .sort_values(["edge_delay_seconds", "trip_count"], ascending=False)
    )
    if max_network_rows > 0:
        grouped = _limit_network_rows(grouped, max_network_rows)

    rows: list[dict[str, Any]] = []
    for row in grouped.to_dict("records"):
        rows.append(
            {
                "generated_at": generated_at,
                "feed_timestamp": _iso(row["feed_timestamp"]),
                "route_id": _string_or_none(row["route_id"]),
                "route_name": _string_or_none(row["route_name"]),
                "route_type": None if pd.isna(row["route_type"]) else int(row["route_type"]),
                "mode": _string_or_none(row["mode"]),
                "trip_id": None,
                "edge_id": _string_or_none(row["edge_id"]),
                "direction_id": _string_or_none(row["direction_id"]),
                "src_stop_id": _string_or_none(row["src_stop_id"]),
                "dst_stop_id": _string_or_none(row["dst_stop_id"]),
                "src_stop_name": _string_or_none(row["src_stop_name"]),
                "dst_stop_name": _string_or_none(row["dst_stop_name"]),
                "src_stop_sequence": int(row["stop_position"]),
                "dst_stop_sequence": int(row["stop_position"]) + 1,
                "stop_position": int(row["stop_position"]),
                "scheduled_travel_seconds": None,
                "rt_travel_seconds": None,
                "edge_delay_seconds": int(row["edge_delay_seconds"]),
                "previous_edge_delay_seconds": int(row["previous_edge_delay_seconds"]),
                "delay_delta_seconds": int(row["delay_delta_seconds"]),
                "rolling_mean_delay_15m": round(float(row["rolling_mean_delay_15m"]), 2),
                "rolling_max_delay_30m": int(row["rolling_max_delay_30m"]),
                "downstream_delay_score": int(row["downstream_delay_score"]),
                "affected_downstream_stops": int(row["affected_downstream_stops"]),
                "avg_edge_delay_seconds": round(float(row["avg_edge_delay_seconds"]), 2),
                "src_delay_seconds": None,
                "dst_delay_seconds": int(row["edge_delay_seconds"]),
                "is_delayed": int(row["edge_delay_seconds"]) > 60,
                "trip_count": int(row["trip_count"]),
                "data_stale": False,
                "src_stop_lat": _float_or_none(row["src_stop_lat"]),
                "src_stop_lon": _float_or_none(row["src_stop_lon"]),
                "dst_stop_lat": _float_or_none(row["dst_stop_lat"]),
                "dst_stop_lon": _float_or_none(row["dst_stop_lon"]),
            }
        )
    return rows


def _build_current_bottleneck_rows(latest_edges: pd.DataFrame) -> list[dict[str, Any]]:
    positive = latest_edges[latest_edges["edge_delay_seconds"] > 0].copy()
    if positive.empty:
        return []
    grouped = (
        positive.groupby(["route_id", "edge_id"], dropna=False)
        .agg(
            feed_timestamp=("feed_timestamp", "max"),
            affected_downstream_stops=("trip_id", "nunique"),
            cumulative_downstream_delay_seconds=("edge_delay_seconds", "sum"),
            avg_delay_seconds=("edge_delay_seconds", "mean"),
            max_delay_seconds=("edge_delay_seconds", "max"),
        )
        .reset_index()
    )
    grouped["bottleneck_score"] = (
        grouped["affected_downstream_stops"] * grouped["avg_delay_seconds"]
    )
    grouped = grouped.sort_values("bottleneck_score", ascending=False).head(100)

    generated_at = datetime.now(tz=timezone.utc).isoformat()
    rows: list[dict[str, Any]] = []
    for rank, row in enumerate(grouped.to_dict("records"), start=1):
        rows.append(
            {
                "generated_at": generated_at,
                "feed_timestamp": _iso(row["feed_timestamp"]),
                "rank": rank,
                "stop_id": None,
                "edge_id": _string_or_none(row["edge_id"]),
                "route_id": _string_or_none(row["route_id"]),
                "affected_downstream_stops": int(row["affected_downstream_stops"]),
                "cumulative_downstream_delay_seconds": int(
                    row["cumulative_downstream_delay_seconds"]
                ),
                "avg_delay_seconds": round(float(row["avg_delay_seconds"]), 2),
                "max_delay_seconds": int(row["max_delay_seconds"]),
                "bottleneck_score": round(float(row["bottleneck_score"]), 2),
                "data_stale": False,
            }
        )
    return rows


def _prepare_display_edges(latest_edges: pd.DataFrame, static_zip_path: str | Path) -> pd.DataFrame:
    _stops, routes, _trips, _stop_times = parse_static_feed(str(static_zip_path))
    routes_by_id = {route.route_id: route for route in routes}
    display_stops = _display_stop_lookup(static_zip_path)

    rows: list[dict[str, Any]] = []
    for row in latest_edges.to_dict("records"):
        src = display_stops.get(str(row.get("src_stop_id")), {})
        dst = display_stops.get(str(row.get("dst_stop_id")), {})
        src_stop_id = src.get("stop_id") or row.get("src_stop_id")
        dst_stop_id = dst.get("stop_id") or row.get("dst_stop_id")
        if not src_stop_id or not dst_stop_id or src_stop_id == dst_stop_id:
            continue
        route = routes_by_id.get(str(row.get("route_id")))
        route_type = route.route_type if route else None
        prepared = dict(row)
        prepared.update(
            {
                "route_name": _route_name(row.get("route_id"), route),
                "route_type": route_type,
                "mode": _route_mode(route_type),
                "src_stop_id": src_stop_id,
                "dst_stop_id": dst_stop_id,
                "src_stop_name": src.get("stop_name") or src_stop_id,
                "dst_stop_name": dst.get("stop_name") or dst_stop_id,
                "src_stop_lat": src.get("stop_lat"),
                "src_stop_lon": src.get("stop_lon"),
                "dst_stop_lat": dst.get("stop_lat"),
                "dst_stop_lon": dst.get("stop_lon"),
                "edge_id": f"{row.get('route_id') or 'unknown'}:{src_stop_id}:{dst_stop_id}",
            }
        )
        rows.append(prepared)
    return pd.DataFrame(rows)


def _display_stop_lookup(static_zip_path: str | Path) -> dict[str, dict[str, Any]]:
    stop_rows: dict[str, dict[str, str]] = {}
    with ZipFile(static_zip_path) as zip_file:
        with zip_file.open("stops.txt") as raw_file:
            text_file = TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
            for row in csv.DictReader(text_file):
                stop_rows[row["stop_id"]] = row

    lookup: dict[str, dict[str, Any]] = {}
    for stop_id, row in stop_rows.items():
        parent_id = row.get("parent_station") or stop_id
        display = stop_rows.get(parent_id, row)
        lookup[stop_id] = {
            "stop_id": display.get("stop_id") or parent_id,
            "stop_name": display.get("stop_name") or row.get("stop_name") or parent_id,
            "stop_lat": _optional_float(display.get("stop_lat") or row.get("stop_lat")),
            "stop_lon": _optional_float(display.get("stop_lon") or row.get("stop_lon")),
        }
    return lookup


def _limit_network_rows(grouped: pd.DataFrame, max_network_rows: int) -> pd.DataFrame:
    rail_modes = {"Subway", "Light rail"}
    rail = grouped[grouped["mode"].isin(rail_modes)].sort_values(
        ["route_name", "direction_id", "stop_position"]
    )
    other = grouped[~grouped["mode"].isin(rail_modes)].sort_values(
        ["edge_delay_seconds", "trip_count"], ascending=False
    )
    if len(rail) >= max_network_rows:
        return rail.head(max_network_rows)

    seed = pd.concat([rail, other.head(max_network_rows - len(rail))], ignore_index=True)
    selected_routes = set(seed["route_id"].dropna())
    complete_routes = grouped[grouped["route_id"].isin(selected_routes)].copy()
    if len(complete_routes) <= max_network_rows:
        remaining = max_network_rows - len(complete_routes)
        extra = grouped[~grouped["route_id"].isin(selected_routes)].sort_values(
            ["edge_delay_seconds", "trip_count"], ascending=False
        )
        complete_routes = pd.concat([complete_routes, extra.head(remaining)], ignore_index=True)
    return complete_routes.sort_values(
        ["mode", "route_name", "direction_id", "stop_position", "edge_delay_seconds"],
        ascending=[True, True, True, True, False],
    )


def _build_feed_health_row(latest_timestamp: pd.Timestamp, network_row_count: int) -> dict[str, Any]:
    generated_at = datetime.now(tz=timezone.utc).isoformat()
    return {
        "generated_at": generated_at,
        "feed_timestamp": _iso(latest_timestamp),
        "last_successful_update": _iso(latest_timestamp),
        "status": "ok" if network_row_count else "degraded",
        "data_stale": False,
        "message": f"Serving latest real MBTA snapshot with {network_row_count} network rows.",
    }


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _iso(value: Any) -> str:
    return pd.to_datetime(value, utc=True).isoformat()


def _string_or_none(value: Any) -> str | None:
    if value is None or pd.isna(value):
        return None
    return str(value)


def _float_or_none(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    return float(value)


def _optional_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def _route_name(route_id: Any, route: Any) -> str:
    if route is None:
        return str(route_id)
    short_name = route.route_short_name
    long_name = route.route_long_name
    if short_name and long_name and short_name != long_name:
        return f"{short_name} - {long_name}"
    return long_name or short_name or str(route_id)


def _route_mode(route_type: int | None) -> str:
    return {
        0: "Light rail",
        1: "Subway",
        2: "Commuter rail",
        3: "Bus",
        4: "Ferry",
        5: "Cable tram",
        6: "Aerial lift",
        7: "Funicular",
        11: "Trolleybus",
        12: "Monorail",
    }.get(route_type, "Unknown")


if __name__ == "__main__":
    main()
