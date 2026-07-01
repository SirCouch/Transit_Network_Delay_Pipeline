from __future__ import annotations

import csv
from io import TextIOWrapper
from zipfile import ZipFile

from pipeline.models import Route, Stop, StopTime, Trip


def _optional_float(value: str | None) -> float | None:
    return float(value) if value not in (None, "") else None


def _optional_int(value: str | None) -> int | None:
    return int(value) if value not in (None, "") else None


def _read_csv(zip_file: ZipFile, name: str) -> list[dict[str, str]]:
    with zip_file.open(name) as raw_file:
        text_file = TextIOWrapper(raw_file, encoding="utf-8-sig", newline="")
        return list(csv.DictReader(text_file))


def parse_static_feed(zip_path: str) -> tuple[list[Stop], list[Route], list[Trip], list[StopTime]]:
    with ZipFile(zip_path) as zip_file:
        stops = [
            Stop(
                stop_id=row["stop_id"],
                stop_name=row.get("stop_name"),
                stop_lat=_optional_float(row.get("stop_lat")),
                stop_lon=_optional_float(row.get("stop_lon")),
            )
            for row in _read_csv(zip_file, "stops.txt")
        ]
        routes = [
            Route(
                route_id=row["route_id"],
                route_short_name=row.get("route_short_name"),
                route_long_name=row.get("route_long_name"),
                route_type=_optional_int(row.get("route_type")),
            )
            for row in _read_csv(zip_file, "routes.txt")
        ]
        trips = [
            Trip(
                trip_id=row["trip_id"],
                route_id=row.get("route_id"),
                service_id=row.get("service_id"),
                direction_id=_optional_int(row.get("direction_id")),
                shape_id=row.get("shape_id"),
            )
            for row in _read_csv(zip_file, "trips.txt")
        ]
        stop_times = [
            StopTime(
                trip_id=row["trip_id"],
                stop_id=row["stop_id"],
                stop_sequence=int(row["stop_sequence"]),
                arrival_time=row.get("arrival_time"),
                departure_time=row.get("departure_time"),
            )
            for row in _read_csv(zip_file, "stop_times.txt")
        ]
    return stops, routes, trips, stop_times

