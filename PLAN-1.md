# Cloud-Deployed Transit Network Delay Pipeline — Implementation Plan

## 1. Project framing

**Project title (use everywhere — resume, README, repo description):**
Cloud-Deployed Transit Network Delay Pipeline — GCP Data Engineering / Graph Analytics Project

Repo name can be whatever; `transit-delay-pipeline` is fine. "GTFS" goes in the resume bullet body, not in the project title — recruiters know "transit delay," they may not know "GTFS."

**Resume slot:** Replaces *Environmental Kuznets Curve Panel Analysis* on the general DS resume. EKC stays on the research/policy/econometrics variant only.

**What this project proves that the current resume does not:**
- Cloud-native data pipeline with orchestration, ingestion, storage, and serving
- Public-data ingestion and protobuf parsing
- Geospatial data modeling and querying
- Containerized service deployment with scale-to-zero economics
- API development and dashboarding tied to a live data source
- Infrastructure-as-code for reproducible cloud deployment
- One predictive ML layer so the project reads as data science, not pure data engineering

**Primary cloud:** GCP. Rationale: lowest-cost path for scale-to-zero, BigQuery free tier covers portfolio-scale geospatial querying without standing up a database, and the existing resume already shows AWS — adding GCP broadens cloud surface area instead of duplicating it.

**Honesty constraint:** This is a near-real-time micro-batch pipeline, not true streaming. Resume and README must say "near-real-time micro-batch." Refresh cadence is 1–5 minutes, not 30 seconds, for cost reasons.

---

## 2. Architecture

```
GTFS Static (daily) + GTFS Realtime (every 1–5 min)
        ↓
Cloud Scheduler  ──► triggers Cloud Run Jobs
        ↓
Cloud Run Job: ingest + parse + transform (Python, not Spark)
        ↓
Cloud Storage (raw protobuf snapshots, lifecycle-deleted after 14 days)
        ↓
BigQuery (static graph tables + realtime delay state + analytics + serving tables + GEOGRAPHY columns)
        ↓
Cloud Run Service: FastAPI (public, min instances = 0, max instances = 1)
        ↓
Cloud Run Service: Streamlit + streamlit-folium / Leaflet map (public, min instances = 0, max instances = 1)
```

**Local reproducibility:** `docker-compose.yml` brings up the same Python ingestion job, a local Postgres+PostGIS as a BigQuery substitute, FastAPI, and Streamlit. Local mode is for development and demo recording, not the cloud path.

**Map rendering:** Streamlit dashboard uses `streamlit-folium` to embed a Leaflet map. Folium emits Leaflet under the hood; `streamlit-folium` exposes click events back to Streamlit so stop/edge inspection works. No separate frontend service, no React project to maintain. One Cloud Run service for the entire dashboard.

**Repository structure:** Use a monorepo so the production path and proof-of-skill components are easy to review together.

```
transit-delay-pipeline/
├── api/
├── app/
├── docs/
│   ├── architecture.mmd
│   ├── architecture.png
│   ├── cost_controls.md
│   └── metrics.md
├── infra/
│   └── terraform/
├── pipeline/
├── spark_jobs/
├── tests/
│   └── fixtures/
├── docker-compose.yml
├── Makefile
└── README.md
```

Interview framing: *"The production path is pipeline -> BigQuery -> api -> app; spark_jobs is a separate proof-of-concept for distributed transformation, not the deployed path."*

---

## 3. Key technical decisions (carry these forward)

### 3.0 Agency decision: MBTA for Phase 1

Use MBTA for Phase 1 because it provides GTFS Static and GTFS Realtime feeds suitable for standard protobuf parsing. NYC MTA is deferred to v2 because its custom GTFS-RT extensions add parsing complexity that distracts from the core cloud pipeline.

README wording:

> This project uses MBTA feeds for v1 to keep the realtime parsing layer standard-conformant and focus the project on pipeline architecture, graph analytics, cloud deployment, and serving.

### 3.1 TripUpdate is the source of truth, not VehiclePosition

GTFS-RT `TripUpdate` records carry `stop_sequence` and `stop_id`, which join cleanly back to static `stop_times.txt`. `VehiclePosition` would require map-matching raw coordinates to a route, which is a much harder project. Use `VehiclePosition` only as optional enrichment for map markers in a future phase.

### 3.2 Edge weights are computed from predicted arrival/departure, not by adding delay to every edge

The wrong model:
```
W_rt = W_static + Δd
```
This double-counts: a train that is 5 minutes late at every stop would have 5 minutes added to every edge, inflating the whole downstream path.

The correct model:
- **Node delay at stop B** = `predicted_arrival(B) − scheduled_arrival(B)`
- **Realtime edge time A→B** = `predicted_arrival(B) − predicted_departure(A)`
- **Fallback when only delays are available** = `scheduled_edge_time(A→B) + max(0, delay_B − delay_A)`

This is the single most important conceptual point in the build, and the most likely interview question. Document it explicitly in the README.

### 3.3 Cascade scoring is a downstream-delay-exposure heuristic, not a causal bottleneck identifier

The score:
```
bottleneck_score = affected_downstream_stops × avg_downstream_delay_seconds
```

This is a **heuristic ranking of stops/segments by observed downstream delay exposure, not proof of causal root cause.** A stop or edge may rank highly because it sits downstream of the actual problem.

README wording must match: *"This score ranks stops or segments by observed downstream delay exposure, not by proven root cause."*

This framing is interview-defensible. The other framing ("this finds the bottlenecks") is not.

### 3.4 Refresh cadence: configurable, defaults to cost-safe

Use an environment variable to switch modes:

```
REFRESH_MODE=cost_safe   # 5 min cadence — default, used in production
REFRESH_MODE=demo        # 1 min cadence — used during demo recording
```

Cloud Run has a free tier for CPU and memory, but frequent or long-running jobs can still consume billable resources. BigQuery has a free monthly query-processing tier, but careless dashboard queries can scan more than expected. Default to `cost_safe` for unattended operation; switch to `demo` only when actively recording.

### 3.5 Saved-snapshot fallback

Commit one known-good GTFS Static feed and one known-good GTFS-RT TripUpdate protobuf snapshot under `tests/fixtures/`. Use these for:

- Unit and integration tests
- Local development when the live feed is degraded
- README screenshots and demo videos that need to be reproducible

This decouples the repo's reviewability from the live feed's health at any given moment.

---

## 4. Data model

BigQuery datasets and tables. Partition realtime tables by `DATE(feed_timestamp)`. Cluster by `route_id, trip_id, stop_id`.

### `gtfs_static`
- `stops` — `stop_id, stop_name, stop_lat, stop_lon, geom (GEOGRAPHY)`
- `routes` — `route_id, route_short_name, route_long_name, route_type`
- `trips` — `trip_id, route_id, service_id, direction_id, shape_id`
- `stop_times` — `trip_id, stop_id, stop_sequence, arrival_time, departure_time`

### `gtfs_graph`
- `static_edges` — `edge_id, route_id, direction_id, trip_id (or pattern_id), src_stop_id, dst_stop_id, src_stop_sequence, dst_stop_sequence, scheduled_departure_time, scheduled_arrival_time, scheduled_travel_seconds, geom`

  Include `direction_id` and `trip_id`/`pattern_id`. The same `(src, dst)` pair appears on multiple routes/directions.

### `gtfs_rt`
- `trip_updates_raw` — minimally parsed feed snapshots, retained briefly
- `stop_updates` — `feed_timestamp, trip_id, route_id, start_date, stop_id, stop_sequence, arrival_delay_seconds, departure_delay_seconds, predicted_arrival_time, predicted_departure_time, schedule_relationship`
- `edge_delay_state` — `edge_id, feed_timestamp, scheduled_travel_seconds, rt_travel_seconds, edge_delay_seconds, src_delay_seconds, dst_delay_seconds, is_delayed, updated_at`

### `gtfs_analytics`
- `bottlenecks` — `stop_id or edge_id, route_id, feed_timestamp, affected_downstream_stops, cumulative_downstream_delay_seconds, avg_delay_seconds, max_delay_seconds, bottleneck_score`

### `gtfs_serving`
- `current_network` — small current-state table for the public API and dashboard
- `current_bottlenecks` — latest top-N bottleneck ranking for the public API and dashboard
- `current_feed_health` — latest feed timestamp, last successful update, and freshness/degraded-service metadata

The Cloud Run Job performs heavier computation and writes these serving tables. The public API reads from serving tables instead of recomputing network state from raw history on request.

### Geometry construction
```sql
-- stops
ST_GEOGPOINT(stop_lon, stop_lat)

-- edges
ST_MAKELINE(
  ST_GEOGPOINT(src_lon, src_lat),
  ST_GEOGPOINT(dst_lon, dst_lat)
)
```

---

## 5. MVP scope (Phase 1 — ship this first, then stop)

The MVP is **only** the items below. Nothing else ships before this is deployed and running unattended.

1. Parse GTFS Static into BigQuery (`stops`, `routes`, `trips`, `stop_times`)
2. Decode MBTA GTFS-RT TripUpdates
3. Build static stop-to-stop edges (`gtfs_graph.static_edges`)
4. Compute current stop and edge delay state (`gtfs_rt.stop_updates`, `gtfs_rt.edge_delay_state`)
5. Compute the heuristic bottleneck ranking (`gtfs_analytics.bottlenecks`)
6. Write current-state serving tables (`gtfs_serving.current_network`, `gtfs_serving.current_bottlenecks`, `gtfs_serving.current_feed_health`)
7. Serve `/api/v1/network/current` and `/api/v1/network/bottlenecks` through FastAPI on Cloud Run from serving tables
8. Train and evaluate a LightGBM segment delay-risk model from realtime graph features, beating a current-delay-persistence baseline on a held-out time period
9. Serve `GET /api/v1/predictions/segment-risk?route_id=...` through FastAPI
10. Show a Streamlit + streamlit-folium / Leaflet map with current delays, a top-N bottleneck panel, and an edge risk overlay
11. **Terraform** for everything in `infra/terraform/`: Cloud Storage bucket, BigQuery datasets, Cloud Run services and job, Cloud Scheduler, service accounts, IAM bindings
12. Saved-snapshot fixtures under `tests/fixtures/`
13. README with architecture diagram, MBTA feed rationale, edge-weight explanation, bottleneck-heuristic caveat, model metrics, baseline comparison, and reproducible deployment steps

**Explicitly not in the MVP** (these are later upgrades, not MVP blockers):
- PySpark / GraphFrames proof-of-skill jobs
- VehiclePosition map-matching
- Authentication on public endpoints

---

## 6. Build order

Each phase is a working deliverable. Do not advance until the prior phase runs end-to-end.

### Phase 1.1 — Local pipeline, no cloud
- Use MBTA as the v1 agency. NYC MTA is deferred because custom GTFS-RT extensions add protobuf parsing friction outside the MVP goal.
- Parse GTFS Static, build `static_edges` from `stop_times` ordered by `(trip_id, stop_sequence)`
- Decode one GTFS-RT TripUpdate snapshot using `gtfs-realtime-bindings`
- Compute stop and edge delay state for that snapshot
- Persist to local Postgres+PostGIS via `docker-compose`
- Save the parsed feeds as fixtures under `tests/fixtures/`

**Exit criterion:** one snapshot, one delay state table, one validated edge-delay calculation against a known late train.

### Phase 1.2 — BigQuery
- Provision a dedicated GCP project and enable APIs
- Create BigQuery datasets (`gtfs_static`, `gtfs_graph`, `gtfs_rt`, `gtfs_analytics`, `gtfs_serving`)
- Port static-graph builder to write to `gtfs_static.*` and `gtfs_graph.static_edges`
- Port realtime updater to write to `gtfs_rt.stop_updates` and `gtfs_rt.edge_delay_state`
- Write the bottleneck query that produces `gtfs_analytics.bottlenecks`
- Write current-state serving tables for API reads (`gtfs_serving.current_network`, `gtfs_serving.current_bottlenecks`, `gtfs_serving.current_feed_health`)
- Verify partitioning and clustering (check `INFORMATION_SCHEMA.PARTITIONS`)

**Exit criterion:** a query against `gtfs_serving.current_bottlenecks` returns the current top-N bottleneck stops.

### Phase 1.3 — Cloud Run Job + Cloud Scheduler (via Terraform)
- Write Terraform modules for: bucket, BigQuery datasets, Cloud Run Job, Cloud Scheduler trigger, service accounts, IAM bindings
- Containerize the ingestion script
- `terraform apply` provisions everything
- Scheduler triggers job at 5-minute cadence (cost_safe mode)
- Confirm raw protobuf saved to `gs://gtfs-network-raw-{project}/realtime/trip_updates/YYYY-MM-DD/HHMMSS.pb`
- Lifecycle rule: delete realtime snapshots after 14 days
- Bucket region: `us-central1`, `us-east1`, or `us-west1` (free tier eligibility)

**Exit criterion:** `terraform destroy` followed by `terraform apply` reproduces the full deployment from a clean state; pipeline runs unattended for 24 hours.

### Phase 1.4 — FastAPI on Cloud Run (via Terraform)
- MVP endpoints:
  - `GET /api/v1/health`
  - `GET /api/v1/network/current`
  - `GET /api/v1/network/bottlenecks?limit=5`
- Stretch endpoints if time allows (not MVP-blocking):
  - `GET /api/v1/routes/{route_id}/delays`
  - `GET /api/v1/stops/{stop_id}/status`
- Cloud Run service config: public, `min_instances=0, max_instances=1`
- BigQuery client uses application default credentials via Cloud Run service account
- API queries read from `gtfs_serving.*` tables and set `maximum_bytes_billed`
- On BigQuery quota exhaustion, return cached latest state with `data_stale=true` when available; otherwise return a clear `503 Service Unavailable` or `429 Too Many Requests`
- Terraform manages service deployment

**Exit criterion:** the two network endpoints return valid JSON from serving tables; quota exhaustion returns a degraded response instead of an unexplained 500; health and OpenAPI docs render at `/health` and `/docs`.

### Phase 1.5 — Streamlit + Leaflet dashboard (via Terraform)
- `streamlit-folium` Leaflet map showing stops as markers and edges as colored polylines
- Edge color by delay severity (green/yellow/orange/red)
- Top 5 bottlenecks panel with the heuristic caveat shown in the UI
- Route selector
- Last successful feed timestamp + feed health indicator
- Manual refresh button
- Cloud Run service config: public, `min_instances=0, max_instances=1`

**Exit criterion:** dashboard URL loads from cold start in under 15s, shows current network state from BigQuery via the FastAPI service, and displays top-N bottlenecks plus model risk overlay.

### Phase 1.6 — Predictive ML layer (required before deployment)
- Task: predict whether a route segment will exceed a delay threshold in the next update window (e.g., 5–10 minutes ahead)
- Features: current delay, previous delay, route, direction, time of day, day of week, stop position in trip, downstream congestion indicator
- Target: `delay > threshold` in next update window (binary)
- Model: LightGBM
- Training data: backfill from ~2–4 weeks of `gtfs_rt.stop_updates`
- Metrics: precision, recall, ROC-AUC; build a baseline ("predict current delay persists") and beat it
- Serve via new endpoint: `GET /api/v1/predictions/segment-risk?route_id=...`
- Add edge risk overlay to the dashboard

**Exit criterion:** model beats baseline on a held-out time period; predictions are served through FastAPI and visible in dashboard.

**↑ STOP HERE FOR MVP. Deploy only after Phase 1.6 is complete and verified. Update resume with the full MVP bullet set (see §8).**

### Phase 2 — PySpark proof, separately
- `spark_jobs/build_static_graph.py` — same logic as Phase 1.1, in PySpark
- `spark_jobs/update_edge_weights.py` — Spark window functions over `(trip_id, stop_sequence)` for delay propagation
- `spark_jobs/cascade_delay_scoring.py` — GraphFrames for graph representation and subgraph queries; do not claim BFS solves cascade scoring
- README in `spark_jobs/` states this is a parallel implementation for skill demonstration, not the production path
- Optionally run as a one-shot Dataproc Serverless batch for the demo

---

## 7. Evaluation metrics (track these from day one)

These numbers are the interview ammunition. Wire instrumentation in early; don't try to backfill them.

| Area | Metric |
|---|---|
| Pipeline | Average Cloud Run Job runtime (ms) per execution |
| Cost | Average monthly estimated cost (GCP billing export → BigQuery) |
| Data scale | Number of stops, edges, trips, feed snapshots processed |
| Freshness | Median time from feed fetch timestamp to dashboard update |
| API | p50 / p95 response time for `/api/v1/network/bottlenecks` |
| BigQuery | Average bytes scanned per API query |
| Dashboard | Cold-start load time |
| ML layer | ROC-AUC, precision, recall, baseline comparison |

Surface these in:
- A `/metrics` panel in the Streamlit dashboard (or a small admin page)
- The README, updated when numbers stabilize
- A `docs/metrics.md` file with the methodology for each number, so interviewers asking "how did you measure that?" get a real answer

---

## 8. Resume bullets — two versions, do not mix

**After MVP ships (Phase 1.6 complete):**

> **Cloud-Deployed Transit Network Delay Pipeline** — GCP Data Engineering / Graph Analytics Project
> - Built a GCP near-real-time micro-batch pipeline using Cloud Scheduler, Cloud Run Jobs, Cloud Storage, and BigQuery GIS to convert GTFS Static and GTFS Realtime protobuf feeds into a directed transit graph with dynamic edge-delay state.
> - Implemented a downstream delay-exposure ranking across route segments using SQL window functions over scheduled stop sequences, served through FastAPI endpoints and a Streamlit + Leaflet geospatial dashboard.
> - Trained a LightGBM segment delay-risk model from realtime graph features, beat a current-delay-persistence baseline on held-out data, and surfaced predictions as an edge risk overlay in the dashboard.
> - Provisioned all GCP infrastructure with Terraform and containerized ingestion, API, and dashboard services with Docker; deployed to Cloud Run with scale-to-zero configuration.

**Rule:** never put the project on the resume as complete before the model exists, has been evaluated, and is deployed. No mixing planned and built language.

After the MVP swap, the project section on the general DS resume becomes:

1. Cloud-Deployed Transit Network Delay Pipeline
2. College Football SP+ Forecasting & NIL Impact Analysis (capstone)
3. 3D Bin Packing with Reinforcement Learning

---

## 9. Public Demo & Cost Protection

The FastAPI and Streamlit services are public for portfolio review. No shared secret or login is required.

Cost guardrails:
- Cloud Run API: public, `min_instances=0`, `max_instances=1`
- Cloud Run Streamlit dashboard: public, `min_instances=0`, `max_instances=1`
- Cloud Run Job: `REFRESH_MODE=cost_safe` (5 min) by default; monitor runtime
- Public API queries read from small current-state serving tables, not raw history
- API queries set `maximum_bytes_billed`
- BigQuery realtime/history tables are partitioned by feed date and clustered by `route_id, trip_id, stop_id`
- BigQuery custom daily query quotas are set at the project level and, where feasible, user/service-account level
- Cloud Storage lifecycle deletes realtime snapshots after 14 days; static snapshots can persist
- GCP billing alerts are set at $5 during build and $10 once stable
- Do **not** use: Cloud Composer, Cloud SQL, GKE, Dataflow, always-on Dataproc, true streaming

If BigQuery quota is exhausted, the API returns the last cached network state with `data_stale=true`, or returns a clear degraded-service response rather than an unexplained 500.

Example degraded response:

```json
{
  "status": "degraded",
  "data_stale": true,
  "last_successful_update": "2026-05-12T18:45:00Z",
  "message": "Daily BigQuery quota exhausted; returning last cached network state."
}
```

---

## 10. Out of scope (deliberate, defensible v2+ topics)

- VehiclePosition map-matching
- True streaming (Spark Structured Streaming, Pub/Sub)
- Multi-agency federation
- Authentication / multi-tenant access
- Weighted shortest-path routing under realtime conditions
- Historical replay UI

Each is a credible expansion to discuss in interviews without needing to be built.

---

## 11. Resolved Phase 1 decisions

1. **Agency:** Use MBTA for Phase 1. NYC MTA is deferred to v2 because its custom GTFS-RT extensions distract from the core pipeline.
2. **Repo structure:** Use the monorepo layout in §2 with `api/`, `app/`, `docs/`, `infra/terraform/`, `pipeline/`, `spark_jobs/`, and `tests/fixtures/`.
3. **Public endpoint posture:** Keep FastAPI and Streamlit public for recruiter review, with Cloud Run max instances, BigQuery quotas, `maximum_bytes_billed`, and graceful degraded responses for cost protection.
4. **GCP project:** Use a new dedicated GCP project for clean quotas, cost tracking, IAM, and `terraform destroy` safety.
