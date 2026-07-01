from __future__ import annotations

import json

from pipeline.local_fixture_runner import main


def test_local_fixture_runner_writes_serving_files(tmp_path, monkeypatch):
    output_dir = tmp_path / "local_serving"
    monkeypatch.setattr(
        "sys.argv",
        ["local_fixture_runner", "--output-dir", str(output_dir)],
    )

    main()

    expected = {
        "current_network.json",
        "current_bottlenecks.json",
        "current_feed_health.json",
    }
    names = {path.name for path in output_dir.iterdir()}
    assert expected.issubset(names)
    assert "segment_risk.json" in names
    assert "model_metrics.json" in names
    assert "segment_risk_model.joblib" in names
    assert json.loads((output_dir / "current_network.json").read_text(encoding="utf-8"))
    assert json.loads((output_dir / "current_bottlenecks.json").read_text(encoding="utf-8"))
    assert (
        json.loads((output_dir / "current_feed_health.json").read_text(encoding="utf-8"))[
            "status"
        ]
        == "ok"
    )
    metrics = json.loads((output_dir / "model_metrics.json").read_text(encoding="utf-8"))
    assert metrics["roc_auc"] > metrics["baseline_roc_auc"]
