from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from pipeline.ml import (
    write_segment_risk_serving_outputs,
)
from pipeline.runner import run_local, write_local_serving_output
from pipeline.sample_fixtures import (
    build_sample_trip_updates_payload,
    write_sample_static_feed,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate local serving-table JSON files from sample MBTA-shaped fixtures."
    )
    parser.add_argument(
        "--output-dir",
        default="local_serving",
        help="Directory for current_network.json, current_bottlenecks.json, and current_feed_health.json.",
    )
    args = parser.parse_args()

    with TemporaryDirectory() as tmpdir:
        static_zip = Path(tmpdir) / "mbta_static_sample.zip"
        write_sample_static_feed(static_zip)
        output = run_local(str(static_zip), build_sample_trip_updates_payload())
        write_local_serving_output(output, args.output_dir)
        write_segment_risk_serving_outputs(output.current_network, args.output_dir)

    print(f"Wrote local serving files to {Path(args.output_dir).resolve()}")


if __name__ == "__main__":
    main()
