from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True)
class Stop:
    stop_id: str
    stop_name: str | None
    stop_lat: float | None
    stop_lon: float | None


@dataclass(frozen=True)
class Route:
    route_id: str
    route_short_name: str | None
    route_long_name: str | None
    route_type: int | None


@dataclass(frozen=True)
class Trip:
    trip_id: str
    route_id: str | None
    service_id: str | None
    direction_id: int | None
    shape_id: str | None


@dataclass(frozen=True)
class StopTime:
    trip_id: str
    stop_id: str
    stop_sequence: int
    arrival_time: str | None
    departure_time: str | None


@dataclass(frozen=True)
class StaticEdge:
    edge_id: str
    route_id: str | None
    direction_id: int | None
    trip_id: str
    src_stop_id: str
    dst_stop_id: str
    src_stop_sequence: int
    dst_stop_sequence: int
    scheduled_departure_time: str | None
    scheduled_arrival_time: str | None
    scheduled_travel_seconds: int | None


@dataclass(frozen=True)
class StopUpdate:
    feed_timestamp: datetime
    trip_id: str | None
    route_id: str | None
    start_date: date | None
    stop_id: str | None
    stop_sequence: int | None
    arrival_delay_seconds: int | None
    departure_delay_seconds: int | None
    predicted_arrival_time: datetime | None
    predicted_departure_time: datetime | None
    schedule_relationship: str | None


@dataclass(frozen=True)
class EdgeDelayState:
    edge_id: str
    feed_timestamp: datetime
    route_id: str | None
    trip_id: str
    scheduled_travel_seconds: int | None
    rt_travel_seconds: int | None
    edge_delay_seconds: int | None
    src_delay_seconds: int | None
    dst_delay_seconds: int | None
    is_delayed: bool
    updated_at: datetime


@dataclass(frozen=True)
class Bottleneck:
    feed_timestamp: datetime
    stop_id: str | None
    edge_id: str | None
    route_id: str | None
    affected_downstream_stops: int
    cumulative_downstream_delay_seconds: int
    avg_delay_seconds: float
    max_delay_seconds: int
    bottleneck_score: float


@dataclass(frozen=True)
class FeedHealth:
    generated_at: datetime
    feed_timestamp: datetime | None
    last_successful_update: datetime | None
    status: str
    data_stale: bool
    message: str | None

