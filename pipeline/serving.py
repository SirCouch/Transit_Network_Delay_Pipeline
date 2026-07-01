from __future__ import annotations

from datetime import datetime, timezone

from pipeline.models import Bottleneck, EdgeDelayState, FeedHealth, StaticEdge, Stop


def build_current_network_rows(
    edge_states: list[EdgeDelayState],
    static_edges: list[StaticEdge],
    stops: list[Stop],
    data_stale: bool = False,
) -> list[dict[str, object]]:
    edges_by_id = {edge.edge_id: edge for edge in static_edges}
    stops_by_id = {stop.stop_id: stop for stop in stops}
    rows: list[dict[str, object]] = []
    generated_at = datetime.now(tz=timezone.utc).isoformat()

    for state in edge_states:
        edge = edges_by_id.get(state.edge_id)
        src_stop = stops_by_id.get(edge.src_stop_id) if edge else None
        dst_stop = stops_by_id.get(edge.dst_stop_id) if edge else None
        rows.append(
            {
                "generated_at": generated_at,
                "feed_timestamp": state.feed_timestamp.isoformat(),
                "route_id": state.route_id,
                "trip_id": state.trip_id,
                "edge_id": state.edge_id,
                "direction_id": edge.direction_id if edge else None,
                "src_stop_id": edge.src_stop_id if edge else None,
                "dst_stop_id": edge.dst_stop_id if edge else None,
                "src_stop_sequence": edge.src_stop_sequence if edge else None,
                "dst_stop_sequence": edge.dst_stop_sequence if edge else None,
                "stop_position": edge.src_stop_sequence if edge else None,
                "scheduled_travel_seconds": state.scheduled_travel_seconds,
                "rt_travel_seconds": state.rt_travel_seconds,
                "edge_delay_seconds": state.edge_delay_seconds,
                "src_delay_seconds": state.src_delay_seconds,
                "dst_delay_seconds": state.dst_delay_seconds,
                "is_delayed": state.is_delayed,
                "data_stale": data_stale,
                "src_stop_lat": src_stop.stop_lat if src_stop else None,
                "src_stop_lon": src_stop.stop_lon if src_stop else None,
                "dst_stop_lat": dst_stop.stop_lat if dst_stop else None,
                "dst_stop_lon": dst_stop.stop_lon if dst_stop else None,
            }
        )
    return rows


def build_current_bottleneck_rows(
    bottlenecks: list[Bottleneck], data_stale: bool = False
) -> list[dict[str, object]]:
    generated_at = datetime.now(tz=timezone.utc).isoformat()
    return [
        {
            "generated_at": generated_at,
            "feed_timestamp": bottleneck.feed_timestamp.isoformat(),
            "rank": rank,
            "stop_id": bottleneck.stop_id,
            "edge_id": bottleneck.edge_id,
            "route_id": bottleneck.route_id,
            "affected_downstream_stops": bottleneck.affected_downstream_stops,
            "avg_delay_seconds": bottleneck.avg_delay_seconds,
            "max_delay_seconds": bottleneck.max_delay_seconds,
            "bottleneck_score": bottleneck.bottleneck_score,
            "data_stale": data_stale,
        }
        for rank, bottleneck in enumerate(bottlenecks, start=1)
    ]


def build_feed_health_row(
    edge_states: list[EdgeDelayState],
    status: str = "ok",
    data_stale: bool = False,
    message: str | None = None,
) -> dict[str, object]:
    latest_feed_timestamp = max(
        (state.feed_timestamp for state in edge_states),
        default=None,
    )
    health = FeedHealth(
        generated_at=datetime.now(tz=timezone.utc),
        feed_timestamp=latest_feed_timestamp,
        last_successful_update=latest_feed_timestamp,
        status=status,
        data_stale=data_stale,
        message=message,
    )
    return {
        "generated_at": health.generated_at.isoformat(),
        "feed_timestamp": health.feed_timestamp.isoformat() if health.feed_timestamp else None,
        "last_successful_update": (
            health.last_successful_update.isoformat()
            if health.last_successful_update
            else None
        ),
        "status": health.status,
        "data_stale": health.data_stale,
        "message": health.message,
    }
