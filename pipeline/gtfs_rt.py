from __future__ import annotations

from datetime import date, datetime, timezone

from pipeline.models import StopUpdate


def parse_trip_updates(payload: bytes) -> list[StopUpdate]:
    try:
        from google.transit import gtfs_realtime_pb2
    except ImportError as exc:
        raise RuntimeError(
            "gtfs-realtime-bindings is required to parse GTFS-RT protobuf payloads"
        ) from exc

    feed = gtfs_realtime_pb2.FeedMessage()
    feed.ParseFromString(payload)
    feed_timestamp = datetime.fromtimestamp(feed.header.timestamp, tz=timezone.utc)
    updates: list[StopUpdate] = []

    for entity in feed.entity:
        if not entity.HasField("trip_update"):
            continue
        trip_update = entity.trip_update
        trip = trip_update.trip
        start_date = _parse_start_date(trip.start_date)
        route_id = trip.route_id or None
        trip_id = trip.trip_id or None
        for stop_time_update in trip_update.stop_time_update:
            updates.append(
                StopUpdate(
                    feed_timestamp=feed_timestamp,
                    trip_id=trip_id,
                    route_id=route_id,
                    start_date=start_date,
                    stop_id=stop_time_update.stop_id or None,
                    stop_sequence=(
                        stop_time_update.stop_sequence
                        if stop_time_update.HasField("stop_sequence")
                        else None
                    ),
                    arrival_delay_seconds=_event_delay(stop_time_update, "arrival"),
                    departure_delay_seconds=_event_delay(stop_time_update, "departure"),
                    predicted_arrival_time=_event_time(stop_time_update, "arrival"),
                    predicted_departure_time=_event_time(stop_time_update, "departure"),
                    schedule_relationship=_schedule_relationship_name(stop_time_update),
                )
            )
    return updates


def _parse_start_date(value: str) -> date | None:
    if not value:
        return None
    return datetime.strptime(value, "%Y%m%d").date()


def _event_delay(stop_time_update: object, field_name: str) -> int | None:
    if not stop_time_update.HasField(field_name):
        return None
    event = getattr(stop_time_update, field_name)
    return event.delay if event.HasField("delay") else None


def _event_time(stop_time_update: object, field_name: str) -> datetime | None:
    if not stop_time_update.HasField(field_name):
        return None
    event = getattr(stop_time_update, field_name)
    return (
        datetime.fromtimestamp(event.time, tz=timezone.utc)
        if event.HasField("time")
        else None
    )


def _schedule_relationship_name(stop_time_update: object) -> str | None:
    if not stop_time_update.HasField("schedule_relationship"):
        return None
    descriptor = stop_time_update.DESCRIPTOR.fields_by_name["schedule_relationship"]
    return descriptor.enum_type.values_by_number[
        stop_time_update.schedule_relationship
    ].name

