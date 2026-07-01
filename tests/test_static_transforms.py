from __future__ import annotations

from datetime import datetime, timezone
from pipeline.gtfs_static import parse_static_feed
from pipeline.models import StopUpdate
from pipeline.transforms import build_static_edges, compute_edge_delay_state, rank_bottlenecks
from tests.fixtures import write_static_feed


def test_static_feed_builds_ordered_edges(tmp_path):
    feed_path = tmp_path / "static.zip"
    write_static_feed(feed_path)

    _stops, _routes, trips, stop_times = parse_static_feed(str(feed_path))
    edges = build_static_edges(stop_times, trips)

    assert len(edges) == 2
    assert edges[0].edge_id == "T1:1:2"
    assert edges[0].scheduled_travel_seconds == 240


def test_edge_delay_uses_predicted_arrival_minus_predicted_departure():
    feed_time = datetime(2026, 5, 12, 12, tzinfo=timezone.utc)
    stop_updates = [
        StopUpdate(
            feed_timestamp=feed_time,
            trip_id="T1",
            route_id="R",
            start_date=None,
            stop_id="A",
            stop_sequence=1,
            arrival_delay_seconds=60,
            departure_delay_seconds=60,
            predicted_arrival_time=None,
            predicted_departure_time=datetime(2026, 5, 12, 12, 1, tzinfo=timezone.utc),
            schedule_relationship=None,
        ),
        StopUpdate(
            feed_timestamp=feed_time,
            trip_id="T1",
            route_id="R",
            start_date=None,
            stop_id="B",
            stop_sequence=2,
            arrival_delay_seconds=180,
            departure_delay_seconds=180,
            predicted_arrival_time=datetime(2026, 5, 12, 12, 8, tzinfo=timezone.utc),
            predicted_departure_time=None,
            schedule_relationship=None,
        ),
    ]
    _stops, _routes, trips, stop_times = _minimal_static()
    edges = build_static_edges(stop_times, trips)

    states = compute_edge_delay_state(edges, stop_updates)
    bottlenecks = rank_bottlenecks(states)

    assert states[0].rt_travel_seconds == 420
    assert states[0].edge_delay_seconds == 180
    assert states[0].is_delayed is True
    assert bottlenecks[0].bottleneck_score == 180.0


def _minimal_static():
    from pipeline.models import Route, Stop, StopTime, Trip

    return (
        [
            Stop("A", "Alpha", 42.0, -71.0),
            Stop("B", "Beta", 42.1, -71.1),
        ],
        [Route("R", "Red", "Red Line", 1)],
        [Trip("T1", "R", "WEEK", 0, "shape-a")],
        [
            StopTime("T1", "A", 1, "08:00:00", "08:01:00"),
            StopTime("T1", "B", 2, "08:05:00", "08:06:00"),
        ],
    )
