from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone

from pipeline.models import Bottleneck, EdgeDelayState, StaticEdge, StopTime, StopUpdate, Trip


def seconds_since_midnight(value: str | None) -> int | None:
    if not value:
        return None
    hours, minutes, seconds = [int(part) for part in value.split(":")]
    return hours * 3600 + minutes * 60 + seconds


def build_static_edges(stop_times: list[StopTime], trips: list[Trip]) -> list[StaticEdge]:
    trips_by_id = {trip.trip_id: trip for trip in trips}
    times_by_trip: dict[str, list[StopTime]] = defaultdict(list)
    for stop_time in stop_times:
        times_by_trip[stop_time.trip_id].append(stop_time)

    edges: list[StaticEdge] = []
    for trip_id, trip_stop_times in times_by_trip.items():
        ordered = sorted(trip_stop_times, key=lambda item: item.stop_sequence)
        trip = trips_by_id.get(trip_id)
        for src, dst in zip(ordered, ordered[1:]):
            src_departure = seconds_since_midnight(src.departure_time or src.arrival_time)
            dst_arrival = seconds_since_midnight(dst.arrival_time or dst.departure_time)
            scheduled_travel = (
                dst_arrival - src_departure
                if src_departure is not None and dst_arrival is not None
                else None
            )
            edge_id = f"{trip_id}:{src.stop_sequence}:{dst.stop_sequence}"
            edges.append(
                StaticEdge(
                    edge_id=edge_id,
                    route_id=trip.route_id if trip else None,
                    direction_id=trip.direction_id if trip else None,
                    trip_id=trip_id,
                    src_stop_id=src.stop_id,
                    dst_stop_id=dst.stop_id,
                    src_stop_sequence=src.stop_sequence,
                    dst_stop_sequence=dst.stop_sequence,
                    scheduled_departure_time=src.departure_time,
                    scheduled_arrival_time=dst.arrival_time,
                    scheduled_travel_seconds=scheduled_travel,
                )
            )
    return edges


def compute_edge_delay_state(
    static_edges: list[StaticEdge], stop_updates: list[StopUpdate]
) -> list[EdgeDelayState]:
    updates_by_trip_sequence = {
        (update.trip_id, update.stop_sequence): update
        for update in stop_updates
        if update.trip_id and update.stop_sequence is not None
    }
    now = datetime.now(tz=timezone.utc)
    states: list[EdgeDelayState] = []

    for edge in static_edges:
        src = updates_by_trip_sequence.get((edge.trip_id, edge.src_stop_sequence))
        dst = updates_by_trip_sequence.get((edge.trip_id, edge.dst_stop_sequence))
        if not src and not dst:
            continue

        rt_travel = None
        if src and dst and src.predicted_departure_time and dst.predicted_arrival_time:
            rt_travel = int(
                (dst.predicted_arrival_time - src.predicted_departure_time).total_seconds()
            )

        src_delay = _best_delay(src) if src else None
        dst_delay = _best_delay(dst) if dst else None
        edge_delay = _edge_delay(edge.scheduled_travel_seconds, rt_travel, src_delay, dst_delay)

        states.append(
            EdgeDelayState(
                edge_id=edge.edge_id,
                feed_timestamp=(dst or src).feed_timestamp,
                route_id=edge.route_id,
                trip_id=edge.trip_id,
                scheduled_travel_seconds=edge.scheduled_travel_seconds,
                rt_travel_seconds=rt_travel,
                edge_delay_seconds=edge_delay,
                src_delay_seconds=src_delay,
                dst_delay_seconds=dst_delay,
                is_delayed=(edge_delay or 0) > 60,
                updated_at=now,
            )
        )
    return states


def rank_bottlenecks(edge_states: list[EdgeDelayState]) -> list[Bottleneck]:
    by_edge: dict[str, list[EdgeDelayState]] = defaultdict(list)
    for state in edge_states:
        if state.edge_delay_seconds and state.edge_delay_seconds > 0:
            by_edge[state.edge_id].append(state)

    bottlenecks: list[Bottleneck] = []
    for edge_id, states in by_edge.items():
        delays = [state.edge_delay_seconds or 0 for state in states]
        cumulative = sum(delays)
        avg_delay = cumulative / len(delays)
        affected = len(states)
        representative = states[0]
        bottlenecks.append(
            Bottleneck(
                feed_timestamp=representative.feed_timestamp,
                stop_id=None,
                edge_id=edge_id,
                route_id=representative.route_id,
                affected_downstream_stops=affected,
                cumulative_downstream_delay_seconds=cumulative,
                avg_delay_seconds=avg_delay,
                max_delay_seconds=max(delays),
                bottleneck_score=affected * avg_delay,
            )
        )
    return sorted(bottlenecks, key=lambda item: item.bottleneck_score, reverse=True)


def _best_delay(update: StopUpdate | None) -> int | None:
    if update is None:
        return None
    if update.arrival_delay_seconds is not None:
        return update.arrival_delay_seconds
    return update.departure_delay_seconds


def _edge_delay(
    scheduled_travel: int | None,
    rt_travel: int | None,
    src_delay: int | None,
    dst_delay: int | None,
) -> int | None:
    if rt_travel is not None and scheduled_travel is not None:
        return rt_travel - scheduled_travel
    if scheduled_travel is not None and src_delay is not None and dst_delay is not None:
        return max(0, dst_delay - src_delay)
    if dst_delay is not None:
        return max(0, dst_delay)
    return None

