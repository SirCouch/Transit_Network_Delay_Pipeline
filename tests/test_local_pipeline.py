from __future__ import annotations

from pipeline.gtfs_rt import parse_trip_updates
from pipeline.runner import run_local
from tests.fixtures import build_trip_updates_payload, write_static_feed


def test_trip_updates_decode_from_real_protobuf_payload():
    updates = parse_trip_updates(build_trip_updates_payload())

    assert len(updates) == 3
    assert updates[0].trip_id == "T1"
    assert updates[0].route_id == "R"
    assert updates[0].stop_sequence == 1
    assert updates[1].arrival_delay_seconds == 180
    assert updates[2].stop_id == "C"


def test_local_pipeline_produces_serving_table_shapes(tmp_path):
    static_zip = tmp_path / "mbta_static_sample.zip"
    write_static_feed(static_zip)

    output = run_local(str(static_zip), build_trip_updates_payload())

    assert output.current_network
    assert output.current_bottlenecks
    assert output.current_feed_health["status"] == "ok"
    assert {
        "generated_at",
        "feed_timestamp",
        "route_id",
        "trip_id",
        "edge_id",
        "edge_delay_seconds",
        "data_stale",
    }.issubset(output.current_network[0])
    assert {
        "rank",
        "edge_id",
        "route_id",
        "bottleneck_score",
        "data_stale",
    }.issubset(output.current_bottlenecks[0])

