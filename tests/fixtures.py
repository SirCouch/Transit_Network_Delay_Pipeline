from __future__ import annotations

from pipeline.sample_fixtures import (
    build_sample_trip_updates_payload,
    write_sample_static_feed,
)


def write_static_feed(path) -> None:
    write_sample_static_feed(path)


def build_trip_updates_payload(*args, **kwargs) -> bytes:
    return build_sample_trip_updates_payload(*args, **kwargs)
