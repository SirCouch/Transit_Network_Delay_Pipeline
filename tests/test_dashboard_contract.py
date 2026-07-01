from __future__ import annotations

from app import streamlit_app


def test_dashboard_fetches_from_api_base_url(monkeypatch):
    requested_urls: list[str] = []

    class Response:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {"status": "ok"}

    def fake_get(url: str, timeout: int):
        requested_urls.append(url)
        assert timeout == 10
        return Response()

    monkeypatch.setattr(streamlit_app.requests, "get", fake_get)
    monkeypatch.setattr(streamlit_app, "API_BASE_URL", "http://api.local")

    assert streamlit_app._get_json("/api/v1/health") == {"status": "ok"}
    assert requested_urls == ["http://api.local/api/v1/health"]


def test_metric_formatter_handles_missing_and_numeric_values():
    assert streamlit_app._format_metric(None) == "n/a"
    assert streamlit_app._format_metric(0.91234) == "0.912"


def test_table_column_names_are_human_readable():
    frame = streamlit_app._rename_columns(
        streamlit_app.pd.DataFrame(
            [
                {
                    "rank": 1,
                    "route_name": "1 - Harvard Square - Nubian Station",
                    "segment_name": "Central -> Kendall",
                    "affected_downstream_stops": 3,
                    "avg_delay": "4 min",
                }
            ]
        )
    )

    assert list(frame.columns) == [
        "Rank",
        "Route",
        "Segment",
        "Affected trips",
        "Average delay",
    ]


def test_responsive_dashboard_styles_are_installed(monkeypatch):
    rendered: list[str] = []

    def fake_markdown(body: str, unsafe_allow_html: bool):
        rendered.append(body)
        assert unsafe_allow_html is True

    monkeypatch.setattr(streamlit_app.st, "markdown", fake_markdown)

    streamlit_app._inject_styles()

    css = rendered[0]
    assert ".kpi-grid" in css
    assert ".legend-dash" in css
    assert "repeat(auto-fit" in css
    assert "[data-testid=\"stDeckGlJsonChart\"]" in css
    assert "@media (min-aspect-ratio: 16 / 9)" in css
    assert "@media (max-width: 520px)" in css


def test_delay_severity_thresholds_match_dashboard_legend():
    assert streamlit_app._delay_severity(None) == "gray"
    assert streamlit_app._delay_severity(60) == "green"
    assert streamlit_app._delay_severity(180) == "yellow"
    assert streamlit_app._delay_severity(420) == "orange"
    assert streamlit_app._delay_severity(421) == "red"


def test_segment_frame_builds_map_ready_paths_and_tooltips():
    frame = streamlit_app._prepare_segment_frame(
        [
            {
                "route_id": "Red",
                "edge_id": "red:1:2",
                "direction_id": 0,
                "src_stop_id": "place-pktrm",
                "src_stop_name": "Park Street",
                "src_stop_lat": 42.3564,
                "src_stop_lon": -71.0624,
                "dst_stop_id": "place-dwnxg",
                "dst_stop_name": "Downtown Crossing",
                "dst_stop_lat": 42.3555,
                "dst_stop_lon": -71.0603,
                "scheduled_travel_seconds": 140,
                "rt_travel_seconds": 366,
                "edge_delay_seconds": 226,
                "feed_timestamp": "2026-05-14T14:42:00Z",
            }
        ],
        bottlenecks=[
            {
                "edge_id": "red:1:2",
                "affected_downstream_stops": 4,
                "bottleneck_score": 842,
            }
        ],
        risks=[{"edge_id": "red:1:2", "risk_probability": 0.82, "threshold_seconds": 180}],
    )

    assert frame.iloc[0]["path"] == [[-71.0624, 42.3564], [-71.0603, 42.3555]]
    assert frame.iloc[0]["delay_severity"] == "orange"
    assert frame.iloc[0]["status_label"] == "Moderate delay"
    assert frame.iloc[0]["affected_downstream_stops"] == 4
    assert "Park Street -> Downtown Crossing" in frame.iloc[0]["tooltip_line_2"]
    assert frame.iloc[0]["risk_probability"] == 0.82
    assert frame.iloc[0]["tooltip_line_4"] == "Predicted 10-min risk: 0.82"
    assert frame.iloc[0]["tooltip_line_5"] == "Risk rank: #1 of all segments"
    assert frame.iloc[0]["tooltip_line_6"] == "Risk overlay: Top 50"
    assert frame.iloc[0]["tooltip_line_7"] == "Target: delay >= 3.0 min within 10 min"


def test_missing_travel_times_are_omitted_from_segment_tooltip():
    frame = streamlit_app._prepare_segment_frame(
        [
            {
                "route_id": "Red",
                "edge_id": "red:1:2",
                "src_stop_id": "A",
                "src_stop_name": "A Stop",
                "src_stop_lat": 42.0,
                "src_stop_lon": -71.0,
                "dst_stop_id": "B",
                "dst_stop_name": "B Stop",
                "dst_stop_lat": 42.1,
                "dst_stop_lon": -71.1,
                "edge_delay_seconds": 120,
            }
        ]
    )

    assert frame.iloc[0]["travel_tooltip_line_1"] == ""
    assert frame.iloc[0]["travel_tooltip_line_2"] == ""


def test_predicted_risk_map_mode_keeps_current_delay_colors():
    frame = streamlit_app._prepare_segment_frame(
        [
            {
                "route_id": "Red",
                "edge_id": "red:1:2",
                "src_stop_id": "A",
                "src_stop_name": "A Stop",
                "src_stop_lat": 42.0,
                "src_stop_lon": -71.0,
                "dst_stop_id": "B",
                "dst_stop_name": "B Stop",
                "dst_stop_lat": 42.1,
                "dst_stop_lon": -71.1,
                "edge_delay_seconds": 0,
            }
        ],
        risks=[{"edge_id": "red:1:2", "risk_probability": 0.8}],
    )

    styled = streamlit_app._apply_map_mode_styles(
        frame,
        streamlit_app.MAP_MODE_PREDICTED_RISK,
    )

    assert styled.iloc[0]["color"] == streamlit_app.SEVERITY_COLORS["green"]
    assert styled.iloc[0]["status_label"] == "On time"
    assert styled.iloc[0]["line_width"] == 3


def test_predicted_risk_overlay_uses_top_50_dashed_segments_only():
    edges = []
    risks = []
    for index in range(55):
        edge_id = f"red:{index}:{index + 1}"
        edges.append(
            {
                "route_id": "Red",
                "edge_id": edge_id,
                "src_stop_id": f"A{index}",
                "src_stop_name": f"A Stop {index}",
                "src_stop_lat": 42.0 + index * 0.001,
                "src_stop_lon": -71.0,
                "dst_stop_id": f"B{index}",
                "dst_stop_name": f"B Stop {index}",
                "dst_stop_lat": 42.001 + index * 0.001,
                "dst_stop_lon": -71.001,
                "edge_delay_seconds": 0,
            }
        )
        risks.append({"edge_id": edge_id, "risk_probability": 1 - (index * 0.01)})

    frame = streamlit_app._prepare_segment_frame(edges, risks=risks)
    overlay = streamlit_app._risk_overlay_rows(frame)

    assert frame[frame["risk_overlay"] == "Top 50"]["edge_id"].nunique() == 50
    assert {row["edge_id"] for row in overlay} == set(
        frame[frame["risk_overlay"] == "Top 50"]["edge_id"]
    )
    assert all(row["risk_overlay_color"] == streamlit_app.RISK_OVERLAY_COLOR for row in overlay)


def test_stop_frame_aggregates_routes_and_delayed_segment_counts():
    segments = streamlit_app._prepare_segment_frame(
        [
            {
                "route_id": "Red",
                "route_name": "Red Line",
                "edge_id": "red:1:2",
                "src_stop_id": "A",
                "src_stop_name": "A Stop",
                "src_stop_lat": 42.0,
                "src_stop_lon": -71.0,
                "dst_stop_id": "B",
                "dst_stop_name": "B Stop",
                "dst_stop_lat": 42.1,
                "dst_stop_lon": -71.1,
                "edge_delay_seconds": 240,
                "src_delay_seconds": 60,
                "dst_delay_seconds": 240,
            }
        ],
        bottlenecks=[{"edge_id": "red:1:2", "bottleneck_score": 500}],
    )

    stops = streamlit_app._prepare_stop_frame(segments)
    b_stop = stops[stops["stop_id"] == "B"].iloc[0]

    assert b_stop["routes"] == ["Red Line"]
    assert b_stop["incoming_delayed_segments"] == 1
    assert b_stop["avg_arrival_delay_seconds"] == 240


def test_stop_color_represents_observed_stop_delay_not_downstream_exposure():
    segments = streamlit_app._prepare_segment_frame(
        [
            {
                "route_id": "Red",
                "edge_id": "red:1:2",
                "src_stop_id": "A",
                "src_stop_name": "A Stop",
                "src_stop_lat": 42.0,
                "src_stop_lon": -71.0,
                "dst_stop_id": "B",
                "dst_stop_name": "B Stop",
                "dst_stop_lat": 42.1,
                "dst_stop_lon": -71.1,
                "edge_delay_seconds": 500,
                "src_delay_seconds": 0,
                "dst_delay_seconds": 0,
            }
        ],
        bottlenecks=[{"edge_id": "red:1:2", "bottleneck_score": 1500}],
    )

    stops = streamlit_app._prepare_stop_frame(segments)
    b_stop = stops[stops["stop_id"] == "B"].iloc[0]

    assert b_stop["avg_arrival_delay_seconds"] == 0
    assert b_stop["delay_severity"] == "green"
    assert b_stop["color"] == [63, 118, 169, 175]
    assert b_stop["radius_meters"] == 90
    assert "Observed stop delay" in b_stop["tooltip_line_3"]


def test_mode_labels_use_gtfs_route_type_values():
    assert streamlit_app._mode_for_edge({"route_type": 3}) == "Bus"
    assert streamlit_app._mode_for_edge({"route_type": 2}) == "Commuter rail"
    assert streamlit_app._mode_for_edge({"route_id": "Boat-F4"}) == "Ferry"


def test_unknown_direction_is_not_displayed_as_direction_number():
    assert streamlit_app._direction_label(None, 0) == "n/a"
    assert streamlit_app._tooltip_direction_line(None, 0) == ""


def test_initial_map_view_keeps_sparse_feeds_zoomed_out():
    segments = streamlit_app._prepare_segment_frame(
        [
            {
                "route_id": "Red",
                "edge_id": "red:1:2",
                "src_stop_id": "place-pktrm",
                "src_stop_name": "Park Street",
                "src_stop_lat": 42.3564,
                "src_stop_lon": -71.0624,
                "dst_stop_id": "place-dwnxg",
                "dst_stop_name": "Downtown Crossing",
                "dst_stop_lat": 42.3555,
                "dst_stop_lon": -71.0603,
                "edge_delay_seconds": 226,
            }
        ]
    )
    stops = streamlit_app._prepare_stop_frame(segments)

    view_state = streamlit_app._initial_view_state(segments, stops)

    assert view_state.zoom == 10


def test_selected_map_object_handles_streamlit_selection_shape():
    selected = streamlit_app._selected_map_object(
        {
            "selection": {
                "objects": {
                    "segments": [
                        {
                            "edge_id": "red:1:2",
                            "route_id": "Red",
                        }
                    ]
                }
            }
        }
    )

    assert selected == {
        "edge_id": "red:1:2",
        "route_id": "Red",
        "layer_id": "segments",
    }
