from __future__ import annotations

import math
import os
from datetime import datetime
from html import escape
from typing import Any

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st


API_BASE_URL = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

SEVERITY_ORDER = ["green", "yellow", "orange", "red", "gray"]
SEVERITY_LABELS = {
    "green": "On time",
    "yellow": "Minor delay",
    "orange": "Moderate delay",
    "red": "Major delay",
    "gray": "No live data",
}
SEVERITY_COLORS = {
    "green": [40, 155, 91, 210],
    "yellow": [236, 190, 75, 220],
    "orange": [226, 121, 58, 230],
    "red": [200, 55, 62, 235],
    "gray": [135, 145, 158, 145],
}
MAP_MODE_CURRENT_DELAY = "Current Delay"
MAP_MODE_PREDICTED_RISK = "Predicted Risk"
RISK_LABELS = {
    "low": "Low risk",
    "medium": "Medium risk",
    "high": "High risk",
    "unknown": "No prediction",
}
RISK_COLORS = {
    "low": [42, 139, 92, 210],
    "medium": [229, 151, 45, 225],
    "high": [190, 49, 68, 235],
    "unknown": [135, 145, 158, 145],
}
RISK_OVERLAY_COLOR = [210, 34, 50, 220]
RISK_TOP_K = 50
PREDICTION_HORIZON_MINUTES = 10
MODE_ROUTE_HINTS = {
    "Blue": "Subway",
    "Boat": "Ferry",
    "CR": "Commuter rail",
    "Green": "Subway",
    "Mattapan": "Subway",
    "Orange": "Subway",
    "Red": "Subway",
}
GTFS_ROUTE_TYPE_MODES = {
    0: "Light rail",
    1: "Subway",
    2: "Commuter rail",
    3: "Bus",
    4: "Ferry",
    5: "Cable tram",
    6: "Aerial lift",
    7: "Funicular",
    11: "Trolleybus",
    12: "Monorail",
}


def main() -> None:
    st.set_page_config(page_title="Transit Delay Monitor", layout="wide")
    _inject_styles()

    health = _get_json("/api/v1/health")
    network = _get_json("/api/v1/network/current")
    bottlenecks = _get_json("/api/v1/network/bottlenecks?limit=10")
    segment_risk = _get_json("/api/v1/predictions/segment-risk")

    edges = network.get("edges", [])
    bottleneck_rows = bottlenecks.get("bottlenecks", [])
    risk_rows = segment_risk.get("predictions", [])

    segment_frame = _prepare_segment_frame(edges, bottleneck_rows, risk_rows)
    stop_frame = _prepare_stop_frame(segment_frame, bottleneck_rows)

    st.title("Transit Delay Monitor")
    header_cols = st.columns([1, 1, 1])
    header_cols[0].caption(f"Feed health: {network.get('status', health.get('status', 'unknown'))}")
    header_cols[1].caption(
        f"Last updated: {_format_timestamp(network.get('last_successful_update'))}"
    )
    header_cols[2].caption("Data stale" if network.get("data_stale") else "Live feed current")

    if network.get("message"):
        st.warning(network["message"])

    filtered_segments, map_mode = _render_filters(segment_frame)
    filtered_stops = _filter_stops_for_segments(stop_frame, filtered_segments)

    selected = _selected_map_object(st.session_state.get("delay_map"))
    selected_route_id = selected.get("route_id") if selected else None
    selected_stop_id = selected.get("stop_id") if selected else None
    filtered_segments = _apply_map_mode_styles(filtered_segments, map_mode)
    filtered_segments = _apply_selection_styles(filtered_segments, selected_route_id)
    filtered_stops = _apply_stop_selection_styles(filtered_stops, selected_stop_id)

    _render_kpis(filtered_segments, filtered_stops, network)

    map_col, detail_col = st.columns([2.4, 1], gap="large")
    with map_col:
        _render_map(filtered_segments, filtered_stops, map_mode)

    selected = _selected_map_object(st.session_state.get("delay_map")) or selected
    with detail_col:
        _render_detail_panel(selected, filtered_segments, filtered_stops, bottleneck_rows, network)


def _render_filters(segment_frame: pd.DataFrame) -> tuple[pd.DataFrame, str]:
    filtered = segment_frame.copy()

    with st.sidebar:
        st.header("Filters")
        map_mode = st.radio(
            "Map mode",
            [MAP_MODE_CURRENT_DELAY, MAP_MODE_PREDICTED_RISK],
            horizontal=True,
        )
        route_options = {"All routes": None}
        if not segment_frame.empty:
            route_labels = (
                segment_frame[["route_id", "route_name"]]
                .drop_duplicates()
                .sort_values(["route_name", "route_id"])
            )
            route_options.update(
                {
                    f"{row.route_name} ({row.route_id})": row.route_id
                    for row in route_labels.itertuples()
                }
            )

        selected_route = st.selectbox("Route", list(route_options))
        selected_route_id = route_options[selected_route]
        if selected_route_id:
            filtered = filtered[filtered["route_id"] == selected_route_id]

        available_modes = sorted(segment_frame["mode"].dropna().unique()) if not segment_frame.empty else []
        selected_modes = st.multiselect("Mode", available_modes, default=available_modes)
        if selected_modes:
            filtered = filtered[filtered["mode"].isin(selected_modes)]

        severity_labels = [SEVERITY_LABELS[name] for name in SEVERITY_ORDER]
        selected_labels = st.multiselect("Severity", severity_labels, default=severity_labels)
        selected_severities = {
            severity
            for severity, label in SEVERITY_LABELS.items()
            if label in selected_labels
        }
        if selected_severities:
            filtered = filtered[filtered["delay_severity"].isin(selected_severities)]

        st.divider()
        st.caption("Refresh: manual")
        st.caption(f"API: {API_BASE_URL}")
        _render_legend(map_mode)

    return filtered.reset_index(drop=True), map_mode


def _render_kpis(
    segment_frame: pd.DataFrame,
    stop_frame: pd.DataFrame,
    network: dict[str, Any],
) -> None:
    delayed_segments = segment_frame[segment_frame["delay_seconds"] > 60]
    delayed_routes = delayed_segments["route_id"].nunique() if not delayed_segments.empty else 0
    worst_route = _worst_route_label(segment_frame)
    worst_stop = _worst_stop_label(stop_frame)
    avg_delay = _average_delay_label(segment_frame)

    _render_kpi_grid(
        [
            ("Last feed update", _format_timestamp(network.get("last_successful_update"))),
            ("Delayed routes", str(delayed_routes)),
            ("Delayed segments", str(len(delayed_segments))),
            ("Worst route", worst_route),
            ("Worst stop", worst_stop),
            ("Avg network delay", avg_delay),
        ]
    )


def _render_kpi_grid(cards: list[tuple[str, str]]) -> None:
    card_html = "".join(
        (
            "<div class='kpi-card'>"
            f"<div class='kpi-label'>{escape(label)}</div>"
            f"<div class='kpi-value'>{escape(value)}</div>"
            "</div>"
        )
        for label, value in cards
    )
    st.markdown(f"<div class='kpi-grid'>{card_html}</div>", unsafe_allow_html=True)


def _render_map(segment_frame: pd.DataFrame, stop_frame: pd.DataFrame, map_mode: str) -> None:
    if segment_frame.empty and stop_frame.empty:
        st.info("No current network rows are available yet.")
        return

    risk_overlay_rows = (
        _risk_overlay_rows(segment_frame)
        if map_mode == MAP_MODE_PREDICTED_RISK
        else []
    )
    layers = [
        pdk.Layer(
            "PathLayer",
            id="predicted-risk-overlay",
            data=risk_overlay_rows,
            get_path="path",
            get_color="risk_overlay_color",
            get_width="risk_overlay_width",
            width_units="pixels",
            rounded=True,
            pickable=True,
            auto_highlight=True,
            highlight_color=[255, 255, 255, 90],
        ),
        pdk.Layer(
            "PathLayer",
            id="segments",
            data=segment_frame.to_dict("records"),
            get_path="path",
            get_color="color",
            get_width="line_width",
            width_units="pixels",
            rounded=True,
            pickable=True,
            auto_highlight=True,
            highlight_color=[255, 255, 255, 90],
        ),
        pdk.Layer(
            "ScatterplotLayer",
            id="stops",
            data=stop_frame.to_dict("records"),
            get_position="[lon, lat]",
            get_fill_color="color",
            get_radius="radius_meters",
            radius_min_pixels=3,
            radius_max_pixels=9,
            stroked=True,
            get_line_color=[255, 255, 255, 190],
            get_line_width=1,
            pickable=True,
            auto_highlight=True,
        ),
    ]
    deck = pdk.Deck(
        map_style="light",
        initial_view_state=_initial_view_state(segment_frame, stop_frame),
        layers=layers,
        tooltip={
            "html": (
                "<b>{tooltip_title}</b><br/>"
                "{tooltip_line_1}<br/>"
                "{tooltip_line_2}<br/>"
                "{tooltip_line_3}<br/>"
                "{tooltip_line_4}<br/>"
                "{tooltip_line_5}<br/>"
                "{tooltip_line_6}<br/>"
                "{tooltip_line_7}"
            ),
            "style": {
                "backgroundColor": "#111827",
                "color": "#f9fafb",
                "fontFamily": "Inter, sans-serif",
                "fontSize": "12px",
            },
        },
    )
    st.pydeck_chart(deck, height=620, on_select="rerun", selection_mode="single-object", key="delay_map")


def _render_detail_panel(
    selected: dict[str, Any] | None,
    segment_frame: pd.DataFrame,
    stop_frame: pd.DataFrame,
    bottleneck_rows: list[dict[str, Any]],
    network: dict[str, Any],
) -> None:
    st.subheader("Network Detail")
    if selected and selected.get("stop_id"):
        _render_stop_detail(selected, segment_frame, stop_frame)
    elif selected and selected.get("edge_id"):
        _render_segment_detail(selected, segment_frame)
    else:
        _render_default_detail(segment_frame, bottleneck_rows, network)


def _render_default_detail(
    segment_frame: pd.DataFrame,
    bottleneck_rows: list[dict[str, Any]],
    network: dict[str, Any],
) -> None:
    st.caption("Network overview")
    if bottleneck_rows:
        bottleneck_frame = _bottleneck_display_frame(bottleneck_rows, segment_frame)
        bottleneck_frame["avg_delay"] = bottleneck_frame["avg_delay_seconds"].map(_format_seconds)
        st.dataframe(
            _rename_columns(
                bottleneck_frame[
                    ["rank", "route_name", "segment_name", "affected_downstream_stops", "avg_delay"]
                ].head(5)
            ),
            width="stretch",
            hide_index=True,
        )
    else:
        st.info("No bottleneck rows are available yet.")

    st.caption("Top delayed routes")
    delayed_routes = _top_delayed_routes(segment_frame)
    if delayed_routes.empty:
        st.info("No delayed route rows match the active filters.")
    else:
        st.dataframe(_rename_columns(delayed_routes.head(5)), width="stretch", hide_index=True)

    st.caption(f"Feed freshness: {_format_timestamp(network.get('last_successful_update'))}")
    _render_legend(MAP_MODE_CURRENT_DELAY)


def _render_segment_detail(selected: dict[str, Any], segment_frame: pd.DataFrame) -> None:
    edge_id = selected.get("edge_id")
    route_id = selected.get("route_id")
    selected_rows = segment_frame[segment_frame["edge_id"] == edge_id]
    segment = selected_rows.iloc[0].to_dict() if not selected_rows.empty else selected
    route_segments = segment_frame[segment_frame["route_id"] == route_id].sort_values(
        "delay_seconds",
        ascending=False,
    )

    st.caption("Selected segment")
    st.metric("Route", f"{segment.get('route_name', route_id)}")
    st.metric("Current segment delay", _format_seconds(segment.get("delay_seconds")))
    st.metric("Predicted risk", _format_probability(segment.get("risk_probability")))
    st.metric("Downstream exposure", _format_metric(segment.get("downstream_delay_score")))
    st.metric("Affected downstream stops", _format_metric(segment.get("affected_downstream_stops")))
    st.write(f"{segment.get('src_stop_name', 'Unknown')} -> {segment.get('dst_stop_name', 'Unknown')}")
    st.caption(f"Updated: {_format_timestamp(segment.get('last_updated'))}")

    if not route_segments.empty:
        route_table = route_segments[
            [
                "segment_name",
                "delay_label",
                "status_label",
                "affected_downstream_stops",
                "downstream_delay_score",
            ]
        ].head(8)
        st.dataframe(_rename_columns(route_table), width="stretch", hide_index=True)


def _render_stop_detail(
    selected: dict[str, Any],
    segment_frame: pd.DataFrame,
    stop_frame: pd.DataFrame,
) -> None:
    stop_id = selected.get("stop_id")
    selected_rows = stop_frame[stop_frame["stop_id"] == stop_id]
    stop = selected_rows.iloc[0].to_dict() if not selected_rows.empty else selected
    related = segment_frame[
        (segment_frame["src_stop_id"] == stop_id) | (segment_frame["dst_stop_id"] == stop_id)
    ].sort_values("delay_seconds", ascending=False)

    st.caption("Selected stop")
    st.metric("Stop", f"{stop.get('stop_name', stop_id)}")
    st.metric("Observed stop delay", _format_seconds(stop.get("avg_arrival_delay_seconds")))
    st.metric("Downstream segment exposure", _format_metric(stop.get("downstream_delay_score")))
    st.write(f"Routes: {', '.join(stop.get('routes', [])) or 'n/a'}")
    st.caption(f"Stop ID: {stop_id}")

    if not related.empty:
        stop_table = related[
            ["route_name", "segment_name", "delay_label", "status_label"]
        ].head(8)
        st.dataframe(_rename_columns(stop_table), width="stretch", hide_index=True)


def _render_legend(map_mode: str) -> None:
    st.caption("Current delay")
    legend_items = [(severity, SEVERITY_LABELS[severity]) for severity in SEVERITY_ORDER]
    legend_cols = st.columns(5)

    for col, (key, label) in zip(legend_cols, legend_items, strict=True):
        rgb = SEVERITY_COLORS[key][:3]
        col.markdown(
            (
                f"<span class='legend-swatch' "
                f"style='background: rgb({rgb[0]}, {rgb[1]}, {rgb[2]});'></span>"
                f"{label}"
            ),
            unsafe_allow_html=True,
        )
    if map_mode == MAP_MODE_PREDICTED_RISK:
        st.caption("Predicted risk overlay")
        st.markdown(
            (
                "<span class='legend-dash'></span>"
                f"Top {RISK_TOP_K} predicted severe-delay risk"
            ),
            unsafe_allow_html=True,
        )


def _bottleneck_display_frame(
    bottlenecks: list[dict[str, Any]],
    segment_frame: pd.DataFrame,
) -> pd.DataFrame:
    frame = pd.DataFrame(bottlenecks)
    if frame.empty:
        return frame

    segment_lookup = {}
    if not segment_frame.empty:
        segment_lookup = {
            row.edge_id: {
                "route_name": row.route_name,
                "segment_name": row.segment_name,
            }
            for row in segment_frame[["edge_id", "route_name", "segment_name"]]
            .drop_duplicates("edge_id")
            .itertuples()
        }

    frame["route_name"] = frame.apply(
        lambda row: segment_lookup.get(row.get("edge_id"), {}).get(
            "route_name", row.get("route_name") or row.get("route_id")
        ),
        axis=1,
    )
    frame["segment_name"] = frame.apply(
        lambda row: segment_lookup.get(row.get("edge_id"), {}).get(
            "segment_name", row.get("segment_name") or row.get("edge_id")
        ),
        axis=1,
    )
    return frame


def _rename_columns(frame: pd.DataFrame) -> pd.DataFrame:
    return frame.rename(
        columns={
            "rank": "Rank",
            "route_id": "Route ID",
            "route_name": "Route",
            "edge_id": "Segment ID",
            "segment_name": "Segment",
            "affected_downstream_stops": "Affected trips",
            "avg_delay": "Average delay",
            "avg_delay_seconds": "Average delay",
            "delay_label": "Current delay",
            "status_label": "Status",
            "downstream_delay_score": "Downstream score",
            "delayed_segments": "Delayed segments",
            "worst_delay": "Worst delay",
        }
    )


def _prepare_segment_frame(
    edges: list[dict[str, Any]],
    bottlenecks: list[dict[str, Any]] | None = None,
    risks: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    bottlenecks_by_edge = {row.get("edge_id"): row for row in bottlenecks or []}
    risks_by_edge = {row.get("edge_id"): row for row in risks or []}
    rows: list[dict[str, Any]] = []
    for edge in edges:
        path = _edge_path(edge)
        if not path:
            continue

        risk = risks_by_edge.get(edge.get("edge_id"), {})
        bottleneck = bottlenecks_by_edge.get(edge.get("edge_id"), {})
        delay_seconds = _coalesce_number(
            edge.get("delay_seconds"),
            edge.get("edge_delay_seconds"),
            risk.get("current_delay_seconds"),
        )
        scheduled_seconds = _optional_number(edge.get("scheduled_travel_seconds"))
        current_seconds = _optional_number(
            edge.get("current_travel_seconds"),
            edge.get("rt_travel_seconds"),
        )
        severity = str(edge.get("delay_severity") or _delay_severity(delay_seconds))
        risk_probability = _risk_probability(risk.get("risk_probability"))
        risk_level = _risk_level(risk_probability)
        threshold_seconds = _optional_number(risk.get("threshold_seconds")) or 180
        route_id = str(edge.get("route_id") or "Unknown")
        src_name = str(edge.get("src_stop_name") or edge.get("src_stop_id") or "Unknown")
        dst_name = str(edge.get("dst_stop_name") or edge.get("dst_stop_id") or "Unknown")
        last_updated = edge.get("last_updated") or edge.get("feed_timestamp") or edge.get("generated_at")
        status_label = SEVERITY_LABELS.get(severity, severity.title())
        segment_name = f"{src_name} -> {dst_name}"

        rows.append(
            {
                **edge,
                "path": path,
                "route_id": route_id,
                "route_name": str(edge.get("route_name") or route_id),
                "mode": _mode_for_edge(edge),
                "direction_label": _direction_label(edge.get("direction"), edge.get("direction_id")),
                "src_stop_name": src_name,
                "dst_stop_name": dst_name,
                "segment_name": segment_name,
                "scheduled_travel_seconds": scheduled_seconds,
                "current_travel_seconds": current_seconds,
                "delay_seconds": delay_seconds,
                "delay_label": _format_seconds(delay_seconds),
                "delay_severity": severity,
                "status_label": status_label,
                "last_updated": last_updated,
                "downstream_delay_score": _coalesce_number(
                    edge.get("downstream_delay_score"),
                    bottleneck.get("bottleneck_score"),
                    risk.get("downstream_congestion_seconds"),
                ),
                "affected_downstream_stops": _coalesce_number(
                    edge.get("affected_downstream_stops"),
                    bottleneck.get("affected_downstream_stops"),
                    0,
                ),
                "risk_probability": risk_probability,
                "risk_label": RISK_LABELS[risk_level],
                "risk_rank": None,
                "risk_overlay": "",
                "threshold_seconds": threshold_seconds,
                "line_width": 5 if severity in {"orange", "red"} else 3,
                "color": SEVERITY_COLORS.get(severity, SEVERITY_COLORS["gray"]),
                "tooltip_title": f"Route: {edge.get('route_name') or route_id}",
                "tooltip_line_1": _tooltip_direction_line(
                    edge.get("direction"),
                    edge.get("direction_id"),
                ),
                "tooltip_line_2": f"Segment: {segment_name}",
                "tooltip_line_3": _tooltip_metric_line(
                    "Current delay",
                    delay_seconds,
                    _format_signed_seconds,
                ),
                "tooltip_line_4": f"Predicted {PREDICTION_HORIZON_MINUTES}-min risk: {_format_probability_decimal(risk_probability)}",
                "tooltip_line_5": "",
                "tooltip_line_6": "",
                "tooltip_line_7": f"Target: delay >= {_format_seconds(threshold_seconds)} within {PREDICTION_HORIZON_MINUTES} min",
                "travel_tooltip_line_1": _tooltip_metric_line(
                    "Scheduled travel",
                    scheduled_seconds,
                    _format_seconds,
                ),
                "travel_tooltip_line_2": _tooltip_metric_line(
                    "Current travel",
                    current_seconds,
                    _format_seconds,
                ),
            }
        )

    frame = pd.DataFrame(rows)
    if frame.empty:
        return frame
    return _add_risk_ranks(frame)


def _add_risk_ranks(frame: pd.DataFrame) -> pd.DataFrame:
    ranked = frame.copy()
    ranked["risk_rank"] = None
    ranked["risk_overlay"] = ""
    valid_risk = ranked[ranked["risk_probability"].map(lambda value: _risk_probability(value) is not None)]
    if valid_risk.empty:
        return ranked

    ordered_indices = valid_risk.sort_values(
        ["risk_probability", "delay_seconds"],
        ascending=False,
    ).index
    for rank, index in enumerate(ordered_indices, start=1):
        ranked.at[index, "risk_rank"] = rank
        overlay_label = f"Top {RISK_TOP_K}" if rank <= RISK_TOP_K else "Not top 50"
        ranked.at[index, "risk_overlay"] = overlay_label
        ranked.at[index, "tooltip_line_5"] = (
            f"Risk rank: #{rank} of all segments"
        )
        ranked.at[index, "tooltip_line_6"] = f"Risk overlay: {overlay_label}"
    return ranked


def _prepare_stop_frame(
    segment_frame: pd.DataFrame,
    bottlenecks: list[dict[str, Any]] | None = None,
) -> pd.DataFrame:
    if segment_frame.empty:
        return pd.DataFrame()

    bottleneck_by_stop: dict[str, float] = {}
    for row in bottlenecks or []:
        stop_id = row.get("stop_id")
        if stop_id:
            bottleneck_by_stop[str(stop_id)] = max(
                bottleneck_by_stop.get(str(stop_id), 0.0),
                _coalesce_number(row.get("bottleneck_score"), 0),
            )

    stop_rows: dict[str, dict[str, Any]] = {}
    for edge in segment_frame.to_dict("records"):
        _collect_stop(
            stop_rows,
            edge,
            stop_id=edge.get("src_stop_id"),
            stop_name=edge.get("src_stop_name"),
            lat=edge.get("src_stop_lat"),
            lon=edge.get("src_stop_lon"),
            delay=edge.get("src_delay_seconds"),
            incoming=False,
        )
        _collect_stop(
            stop_rows,
            edge,
            stop_id=edge.get("dst_stop_id"),
            stop_name=edge.get("dst_stop_name"),
            lat=edge.get("dst_stop_lat"),
            lon=edge.get("dst_stop_lon"),
            delay=edge.get("dst_delay_seconds"),
            incoming=True,
        )

    rows: list[dict[str, Any]] = []
    for stop in stop_rows.values():
        delays = stop.pop("arrival_delays")
        avg_delay = sum(delays) / len(delays) if delays else 0.0
        exposure = max(stop.pop("exposures") or [0.0])
        stop_id = str(stop["stop_id"])
        exposure = max(exposure, bottleneck_by_stop.get(stop_id, 0.0))
        routes = sorted(stop.pop("routes"))
        severity = _delay_severity(avg_delay)
        color = _stop_color(severity)
        radius = _stop_radius(exposure)

        rows.append(
            {
                **stop,
                "routes": routes,
                "avg_arrival_delay_seconds": avg_delay,
                "downstream_delay_score": exposure,
                "delay_severity": severity,
                "color": color,
                "radius_meters": radius,
                "tooltip_title": f"Stop: {stop['stop_name']}",
                "tooltip_line_1": f"Stop ID: {stop_id}",
                "tooltip_line_2": f"Routes: {', '.join(routes) or 'n/a'}",
                "tooltip_line_3": f"Observed stop delay: {_format_seconds(avg_delay)}",
                "tooltip_line_4": f"Downstream segment exposure: {_format_metric(exposure)}",
                "tooltip_line_5": f"Incoming delayed segments: {stop['incoming_delayed_segments']}",
                "tooltip_line_6": f"Outgoing delayed segments: {stop['outgoing_delayed_segments']}",
                "tooltip_line_7": "",
            }
        )

    return pd.DataFrame(rows)


def _collect_stop(
    stop_rows: dict[str, dict[str, Any]],
    edge: dict[str, Any],
    *,
    stop_id: object,
    stop_name: object,
    lat: object,
    lon: object,
    delay: object,
    incoming: bool,
) -> None:
    if not stop_id or not _is_number(lat) or not _is_number(lon):
        return

    key = str(stop_id)
    stop = stop_rows.setdefault(
        key,
        {
            "stop_id": key,
            "stop_name": str(stop_name or key),
            "lat": float(lat),
            "lon": float(lon),
            "routes": set(),
            "arrival_delays": [],
            "exposures": [],
            "incoming_delayed_segments": 0,
            "outgoing_delayed_segments": 0,
        },
    )
    stop["routes"].add(str(edge.get("route_name") or edge.get("route_id") or "Unknown"))
    stop["arrival_delays"].append(_coalesce_number(delay, edge.get("delay_seconds"), 0))
    stop["exposures"].append(_coalesce_number(edge.get("downstream_delay_score"), 0))
    if edge.get("delay_seconds", 0) > 60:
        key_name = "incoming_delayed_segments" if incoming else "outgoing_delayed_segments"
        stop[key_name] += 1


def _filter_stops_for_segments(stop_frame: pd.DataFrame, segment_frame: pd.DataFrame) -> pd.DataFrame:
    if stop_frame.empty or segment_frame.empty:
        return stop_frame

    visible_stop_ids = set(segment_frame["src_stop_id"].dropna()) | set(
        segment_frame["dst_stop_id"].dropna()
    )
    return stop_frame[stop_frame["stop_id"].isin(visible_stop_ids)].reset_index(drop=True)


def _apply_selection_styles(
    segment_frame: pd.DataFrame,
    selected_route_id: object | None,
) -> pd.DataFrame:
    if segment_frame.empty or not selected_route_id:
        return segment_frame

    styled = segment_frame.copy()
    for index, row in styled.iterrows():
        base_color = list(row.get("color") or SEVERITY_COLORS["gray"])
        if row["route_id"] == selected_route_id:
            base_color[3] = 255
            styled.at[index, "line_width"] = 8
        else:
            base_color[3] = 65
            styled.at[index, "line_width"] = 2
        styled.at[index, "color"] = base_color
    return styled


def _apply_map_mode_styles(segment_frame: pd.DataFrame, map_mode: str) -> pd.DataFrame:
    if segment_frame.empty:
        return segment_frame

    styled = segment_frame.copy()
    for index, row in styled.iterrows():
        severity = str(row.get("delay_severity") or "gray")
        styled.at[index, "color"] = SEVERITY_COLORS.get(
            severity, SEVERITY_COLORS["gray"]
        ).copy()
        styled.at[index, "line_width"] = 5 if severity in {"orange", "red"} else 3
        styled.at[index, "status_label"] = SEVERITY_LABELS.get(severity, severity.title())
    return styled


def _risk_overlay_rows(segment_frame: pd.DataFrame) -> list[dict[str, Any]]:
    if segment_frame.empty or "risk_rank" not in segment_frame.columns:
        return []

    overlay_segments = segment_frame[
        segment_frame["risk_rank"].map(lambda value: _is_number(value) and value <= RISK_TOP_K)
    ]
    rows: list[dict[str, Any]] = []
    for segment in overlay_segments.to_dict("records"):
        for dash_index, dash_path in enumerate(_dashed_paths(segment["path"])):
            rows.append(
                {
                    **segment,
                    "path": dash_path,
                    "risk_overlay_color": RISK_OVERLAY_COLOR,
                    "risk_overlay_width": max(8, int(segment.get("line_width") or 5) + 4),
                    "dash_index": dash_index,
                }
            )
    return rows


def _dashed_paths(path: list[list[float]]) -> list[list[list[float]]]:
    dashes: list[list[list[float]]] = []
    for start, end in zip(path, path[1:]):
        start_lon, start_lat = start
        end_lon, end_lat = end
        distance = math.hypot(end_lon - start_lon, end_lat - start_lat)
        pieces = max(4, min(18, math.ceil(distance / 0.003)))
        for piece in range(0, pieces, 2):
            start_fraction = piece / pieces
            end_fraction = min((piece + 1) / pieces, 1.0)
            dashes.append(
                [
                    _interpolate_point(start, end, start_fraction),
                    _interpolate_point(start, end, end_fraction),
                ]
            )
    return dashes or [path]


def _interpolate_point(
    start: list[float],
    end: list[float],
    fraction: float,
) -> list[float]:
    return [
        start[0] + ((end[0] - start[0]) * fraction),
        start[1] + ((end[1] - start[1]) * fraction),
    ]


def _apply_stop_selection_styles(
    stop_frame: pd.DataFrame,
    selected_stop_id: object | None,
) -> pd.DataFrame:
    if stop_frame.empty or not selected_stop_id:
        return stop_frame

    styled = stop_frame.copy()
    for index, row in styled.iterrows():
        if row["stop_id"] == selected_stop_id:
            styled.at[index, "radius_meters"] = 170
            styled.at[index, "color"] = [220, 68, 68, 245]
    return styled


def _edge_path(edge: dict[str, Any]) -> list[list[float]] | None:
    geometry = edge.get("geometry")
    if isinstance(geometry, list) and len(geometry) >= 2:
        path = []
        for point in geometry:
            if isinstance(point, list | tuple) and len(point) >= 2:
                lon, lat = point[0], point[1]
                if _is_number(lat) and _is_number(lon):
                    path.append([float(lon), float(lat)])
        if len(path) >= 2:
            return path

    src_lat = edge.get("src_stop_lat")
    src_lon = edge.get("src_stop_lon")
    dst_lat = edge.get("dst_stop_lat")
    dst_lon = edge.get("dst_stop_lon")
    if all(_is_number(value) for value in [src_lat, src_lon, dst_lat, dst_lon]):
        return [[float(src_lon), float(src_lat)], [float(dst_lon), float(dst_lat)]]
    return None


def _initial_view_state(segment_frame: pd.DataFrame, stop_frame: pd.DataFrame) -> pdk.ViewState:
    points: list[list[float]] = []
    if not segment_frame.empty:
        for path in segment_frame["path"]:
            points.extend(path)
    if not stop_frame.empty:
        points.extend(stop_frame[["lon", "lat"]].values.tolist())

    if not points:
        return pdk.ViewState(latitude=42.3601, longitude=-71.0589, zoom=10, pitch=0)

    lons = [point[0] for point in points]
    lats = [point[1] for point in points]
    lon_span = max(lons) - min(lons)
    lat_span = max(lats) - min(lats)
    max_span = max(lon_span, lat_span)
    zoom = 10
    if max_span > 0.35:
        zoom = 9
    elif max_span > 0.18:
        zoom = 9.5
    elif max_span > 0.08:
        zoom = 10
    elif max_span > 0.03:
        zoom = 10.5
    return pdk.ViewState(
        latitude=sum(lats) / len(lats),
        longitude=sum(lons) / len(lons),
        zoom=zoom,
        pitch=0,
    )


def _delay_severity(delay_seconds: object) -> str:
    if not _is_number(delay_seconds):
        return "gray"
    delay = float(delay_seconds)
    if delay <= 60:
        return "green"
    if delay <= 180:
        return "yellow"
    if delay <= 420:
        return "orange"
    return "red"


def _risk_probability(value: object) -> float | None:
    if not _is_number(value):
        return None
    return max(0.0, min(1.0, float(value)))


def _risk_level(value: object) -> str:
    probability = _risk_probability(value)
    if probability is None:
        return "unknown"
    if probability >= 0.75:
        return "high"
    if probability >= 0.5:
        return "medium"
    return "low"


def _stop_color(severity: str) -> list[int]:
    if severity == "gray":
        return [135, 145, 158, 145]
    if severity == "green":
        return [63, 118, 169, 175]
    return SEVERITY_COLORS.get(severity, SEVERITY_COLORS["gray"])


def _stop_radius(exposure: object) -> int:
    value = _coalesce_number(exposure, 0)
    if value >= 1200:
        return 90
    if value >= 600:
        return 75
    if value >= 180:
        return 60
    return 45


def _mode_for_edge(edge: dict[str, Any]) -> str:
    explicit = edge.get("mode") or edge.get("route_mode") or edge.get("route_type")
    if explicit:
        if isinstance(explicit, int | float) and not isinstance(explicit, bool):
            return GTFS_ROUTE_TYPE_MODES.get(int(explicit), "Unknown")
        return str(explicit).title()
    route_id = str(edge.get("route_id") or "")
    for route_hint, mode in MODE_ROUTE_HINTS.items():
        if route_id.startswith(route_hint):
            return mode
    return "Unknown"


def _direction_label(direction: object, direction_id: object) -> str:
    if direction:
        return str(direction)
    return "n/a"


def _tooltip_direction_line(direction: object, direction_id: object) -> str:
    label = _direction_label(direction, direction_id)
    return f"Direction: {label}" if label != "n/a" else ""


def _selected_map_object(raw_state: object) -> dict[str, Any] | None:
    state = _as_dict(raw_state)
    selection = _as_dict(state.get("selection")) if state else {}
    objects = selection.get("objects") if selection else state.get("objects")
    if not objects:
        return None

    if isinstance(objects, list):
        first = objects[0] if objects else None
        return dict(first) if isinstance(first, dict) else None

    if isinstance(objects, dict):
        for layer_id, layer_objects in objects.items():
            if isinstance(layer_objects, list) and layer_objects:
                selected = dict(layer_objects[0])
                selected["layer_id"] = layer_id
                return selected
            if isinstance(layer_objects, dict):
                selected = dict(layer_objects)
                selected["layer_id"] = layer_id
                return selected
    return None


def _as_dict(value: object) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if hasattr(value, "to_dict"):
        return value.to_dict()
    if hasattr(value, "__dict__"):
        return dict(value.__dict__)
    return {}


def _top_delayed_routes(segment_frame: pd.DataFrame) -> pd.DataFrame:
    if segment_frame.empty:
        return pd.DataFrame()
    delayed = segment_frame[segment_frame["delay_seconds"] > 60]
    if delayed.empty:
        return pd.DataFrame()

    grouped = (
        delayed.groupby(["route_id", "route_name"], as_index=False)
        .agg(
            avg_delay_seconds=("delay_seconds", "mean"),
            worst_delay_seconds=("delay_seconds", "max"),
            delayed_segments=("edge_id", "nunique"),
        )
        .sort_values(["avg_delay_seconds", "worst_delay_seconds"], ascending=False)
    )
    grouped["avg_delay"] = grouped["avg_delay_seconds"].map(_format_seconds)
    grouped["worst_delay"] = grouped["worst_delay_seconds"].map(_format_seconds)
    return grouped[["route_name", "avg_delay", "worst_delay", "delayed_segments"]]


def _worst_route_label(segment_frame: pd.DataFrame) -> str:
    top = _top_delayed_routes(segment_frame)
    if top.empty:
        return "n/a"
    return str(top.iloc[0]["route_name"])


def _worst_stop_label(stop_frame: pd.DataFrame) -> str:
    if stop_frame.empty:
        return "n/a"
    ranked = stop_frame.sort_values(
        ["downstream_delay_score", "avg_arrival_delay_seconds"],
        ascending=False,
    )
    return str(ranked.iloc[0]["stop_name"])


def _average_delay_label(segment_frame: pd.DataFrame) -> str:
    if segment_frame.empty:
        return "n/a"
    positive = segment_frame[segment_frame["delay_seconds"] > 0]
    if positive.empty:
        return "0 min"
    return _format_seconds(float(positive["delay_seconds"].mean()))


def _get_json(path: str) -> dict[str, Any]:
    url = f"{API_BASE_URL}{path}"
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as exc:
        return {
            "status": "degraded",
            "data_stale": True,
            "message": f"Could not reach API at {url}: {exc}",
        }


def _coalesce_number(*values: object) -> float:
    for value in values:
        if _is_number(value):
            return float(value)
    return 0.0


def _optional_number(*values: object) -> float | None:
    for value in values:
        if _is_number(value):
            return float(value)
    return None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool) and math.isfinite(value)


def _format_metric(value: object) -> str:
    if isinstance(value, int | float):
        return f"{value:.3f}" if not float(value).is_integer() else str(int(value))
    return "n/a"


def _format_probability(value: object) -> str:
    probability = _risk_probability(value)
    if probability is None:
        return "n/a"
    return f"{probability:.0%}"


def _format_probability_decimal(value: object) -> str:
    probability = _risk_probability(value)
    if probability is None:
        return "n/a"
    return f"{probability:.2f}"


def _tooltip_metric_line(label: str, value: object, formatter) -> str:
    if not _is_number(value):
        return ""
    return f"{label}: {formatter(value)}"


def _format_seconds(value: object) -> str:
    if not _is_number(value):
        return "n/a"
    minutes = float(value) / 60
    if abs(minutes) < 10:
        return f"{minutes:.1f} min"
    return f"{minutes:.0f} min"


def _format_signed_seconds(value: object) -> str:
    if not _is_number(value):
        return "n/a"
    sign = "+" if float(value) >= 0 else "-"
    return f"{sign}{_format_seconds(abs(float(value)))}"


def _format_timestamp(value: object) -> str:
    if not value:
        return "n/a"
    if isinstance(value, datetime):
        return value.strftime("%-I:%M %p") if os.name != "nt" else value.strftime("%#I:%M %p")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.strftime("%-I:%M %p") if os.name != "nt" else parsed.strftime("%#I:%M %p")
        except ValueError:
            return value
    return str(value)


def _inject_styles() -> None:
    st.markdown(
        """
        <style>
        .block-container {
            max-width: none;
            padding: 1.2rem clamp(0.75rem, 2vw, 2rem) 1.2rem;
        }
        h1 {
            line-height: 1.05;
            margin-bottom: 0.35rem;
        }
        [data-testid="stHorizontalBlock"] {
            gap: clamp(0.75rem, 1.4vw, 1.5rem);
        }
        .kpi-grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(132px, 1fr));
            gap: 0.65rem;
            margin: 0.7rem 0 1rem;
        }
        .kpi-card {
            background: #f8fafc;
            border: 1px solid #e5e7eb;
            border-radius: 8px;
            min-height: 76px;
            padding: 0.72rem 0.78rem;
            display: flex;
            flex-direction: column;
            justify-content: space-between;
            overflow: hidden;
        }
        .kpi-label {
            color: #64748b;
            font-size: clamp(0.68rem, 0.78vw, 0.78rem);
            line-height: 1.15;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
        }
        .kpi-value {
            color: #0f172a;
            font-size: clamp(1rem, 1.55vw, 1.35rem);
            font-weight: 650;
            line-height: 1.15;
            overflow-wrap: anywhere;
        }
        [data-testid="stDeckGlJsonChart"] {
            height: clamp(430px, 62vh, 760px) !important;
            min-height: 430px;
        }
        [data-testid="stDeckGlJsonChart"] iframe,
        [data-testid="stDeckGlJsonChart"] canvas {
            height: 100% !important;
            min-height: 100% !important;
        }
        .legend-swatch {
            display: inline-block;
            width: 0.72rem;
            height: 0.72rem;
            border-radius: 999px;
            margin-right: 0.35rem;
            vertical-align: -0.05rem;
        }
        .legend-dash {
            display: inline-block;
            width: 1.5rem;
            height: 0;
            border-top: 3px dashed #d22232;
            margin-right: 0.45rem;
            vertical-align: 0.18rem;
        }
        @media (min-aspect-ratio: 16 / 9) {
            [data-testid="stDeckGlJsonChart"] {
                height: clamp(500px, 68vh, 840px) !important;
            }
            .kpi-grid {
                grid-template-columns: repeat(6, minmax(120px, 1fr));
            }
        }
        @media (max-aspect-ratio: 4 / 3) {
            [data-testid="stDeckGlJsonChart"] {
                height: clamp(390px, 54vh, 650px) !important;
            }
        }
        @media (max-width: 920px) {
            .block-container {
                padding-left: 0.7rem;
                padding-right: 0.7rem;
            }
            [data-testid="stHorizontalBlock"] {
                flex-wrap: wrap;
            }
            [data-testid="stHorizontalBlock"] > div {
                min-width: min(100%, 18rem);
            }
            [data-testid="stDeckGlJsonChart"] {
                height: clamp(350px, 52vh, 560px) !important;
                min-height: 350px;
            }
            .kpi-grid {
                grid-template-columns: repeat(2, minmax(0, 1fr));
            }
        }
        @media (max-width: 520px) {
            .block-container {
                padding-top: 0.75rem;
            }
            .kpi-grid {
                grid-template-columns: 1fr;
            }
            .kpi-card {
                min-height: 62px;
            }
            [data-testid="stDeckGlJsonChart"] {
                height: clamp(320px, 50vh, 480px) !important;
                min-height: 320px;
            }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


if __name__ == "__main__":
    main()
