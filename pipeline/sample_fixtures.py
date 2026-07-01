from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile


def write_sample_static_feed(path: str | Path) -> None:
    with ZipFile(path, "w") as feed:
        feed.writestr(
            "stops.txt",
            "stop_id,stop_name,stop_lat,stop_lon\n"
            "A,Alpha,42.0,-71.0\n"
            "B,Beta,42.1,-71.1\n"
            "C,Gamma,42.2,-71.2\n",
        )
        feed.writestr(
            "routes.txt",
            "route_id,route_short_name,route_long_name,route_type\nR,Red,Red Line,1\n",
        )
        feed.writestr(
            "trips.txt",
            "route_id,service_id,trip_id,direction_id,shape_id\nR,WEEK,T1,0,shape-a\n",
        )
        feed.writestr(
            "stop_times.txt",
            "trip_id,arrival_time,departure_time,stop_id,stop_sequence\n"
            "T1,08:00:00,08:01:00,A,1\n"
            "T1,08:05:00,08:06:00,B,2\n"
            "T1,08:10:00,08:11:00,C,3\n",
        )


def build_sample_trip_updates_payload(
    feed_timestamp: datetime | None = None,
    stop_delays: tuple[int, int, int] = (60, 180, 240),
) -> bytes:
    from google.transit import gtfs_realtime_pb2

    timestamp = feed_timestamp or datetime(2026, 5, 12, 12, tzinfo=timezone.utc)
    feed = gtfs_realtime_pb2.FeedMessage()
    feed.header.gtfs_realtime_version = "2.0"
    feed.header.timestamp = int(timestamp.timestamp())

    entity = feed.entity.add()
    entity.id = "entity-1"
    trip_update = entity.trip_update
    trip_update.trip.trip_id = "T1"
    trip_update.trip.route_id = "R"
    trip_update.trip.start_date = "20260512"

    first = trip_update.stop_time_update.add()
    first.stop_sequence = 1
    first.stop_id = "A"
    first.arrival.delay = stop_delays[0]
    first.departure.delay = stop_delays[0]
    first.departure.time = int(timestamp.timestamp()) + 60

    second = trip_update.stop_time_update.add()
    second.stop_sequence = 2
    second.stop_id = "B"
    second.arrival.delay = stop_delays[1]
    second.arrival.time = int(timestamp.timestamp()) + 480
    second.departure.delay = stop_delays[1]
    second.departure.time = int(timestamp.timestamp()) + 540

    third = trip_update.stop_time_update.add()
    third.stop_sequence = 3
    third.stop_id = "C"
    third.arrival.delay = stop_delays[2]
    third.arrival.time = int(timestamp.timestamp()) + 900

    return feed.SerializeToString()
