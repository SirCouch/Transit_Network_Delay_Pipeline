.PHONY: test lint local-serving real-serving cloud-serving collect-mbta-static collect-mbta collect-mbta-hour collect-mbta-day collect-mbta-week collect-mbta-two-weeks sync-cloud-snapshots coverage-report decode-mbta decode-mbta-sample build-training-data train-segment-risk evaluate-segment-risk api dashboard pipeline docker-build-api docker-build-dashboard docker-build-pipeline

test:
	python -m pytest

lint:
	python -m ruff check api app pipeline tests

local-serving:
	python -m pipeline.local_fixture_runner --output-dir local_serving

real-serving:
	python -m pipeline.generate_real_serving --stop-updates data/processed/stop_updates.parquet --static-zip data/raw/mbta_static/MBTA_GTFS.zip --model data/ml/segment_risk_model.joblib --output-dir local_serving

cloud-serving:
	python -m pipeline.cloud_serving --bucket transit-network-delay-pipeline-gtfs-raw --static-zip data/raw/mbta_static/MBTA_GTFS.zip --model data/ml/generalization/segment_risk_model.joblib --output-dir local_serving --recent-snapshot-count 24

collect-mbta-static:
	python -m pipeline.collect_mbta_static --output data/raw/mbta_static/MBTA_GTFS.zip

collect-mbta:
	python -m pipeline.collect_mbta_snapshot --output-dir data/raw/mbta_rt

collect-mbta-hour:
	python -m pipeline.collect_mbta_snapshot --output-dir data/raw/mbta_rt --count 12 --interval-seconds 300

collect-mbta-day:
	python -m pipeline.collect_mbta_snapshot --output-dir data/raw/mbta_rt --duration-hours 24 --interval-seconds 300

collect-mbta-week:
	python -m pipeline.collect_mbta_snapshot --output-dir data/raw/mbta_rt --duration-hours 168 --interval-seconds 300

collect-mbta-two-weeks:
	python -m pipeline.collect_mbta_snapshot --output-dir data/raw/mbta_rt --duration-hours 336 --interval-seconds 300

sync-cloud-snapshots:
	gcloud storage rsync --recursive gs://transit-network-delay-pipeline-gtfs-raw/realtime/trip_updates data/raw/mbta_rt_cloud

coverage-report:
	python -m pipeline.data_coverage --stop-updates data/processed/stop_updates.parquet --training data/ml/segment_training.parquet --output data/ml/coverage_report.json

decode-mbta:
	python -m pipeline.decode_mbta_snapshots --input-dir data/raw/mbta_rt --output data/processed/stop_updates.parquet

decode-mbta-sample:
	python -m pipeline.decode_mbta_snapshots --input-dir data/raw/mbta_rt_cloud --output data/processed/stop_updates_sample.parquet --snapshot-stride 3

build-training-data:
	python -m pipeline.build_training_data --input data/processed/stop_updates.parquet --output data/ml/segment_training.parquet --static-zip data/raw/mbta_static/MBTA_GTFS.zip

train-segment-risk:
	python -m pipeline.train_segment_risk --input data/ml/segment_training.parquet --output-dir data/ml

evaluate-segment-risk:
	python -m pipeline.evaluate_segment_risk --input data/ml/segment_training_generalization.parquet --model data/ml/generalization/segment_risk_model.joblib --output-dir data/ml/generalization/evaluation

api:
	$${env:LOCAL_SERVING_DIR='local_serving'}; python -m uvicorn api.main:app --reload

dashboard:
	python -m streamlit run app/streamlit_app.py

pipeline:
	python -m pipeline.runner

docker-build-api:
	docker build -f api/Dockerfile -t transit-api:local .

docker-build-dashboard:
	docker build -f app/Dockerfile -t transit-dashboard:local .

docker-build-pipeline:
	docker build -f pipeline/Dockerfile -t transit-ingest:local .
