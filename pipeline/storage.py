from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path


def trip_update_snapshot_name(feed_timestamp: datetime | None = None) -> str:
    timestamp = feed_timestamp or datetime.now(tz=timezone.utc)
    return timestamp.strftime("realtime/trip_updates/%Y-%m-%d/%H%M%S.pb")


def upload_bytes(bucket_name: str, blob_name: str, payload: bytes) -> str:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for GCS uploads") from exc
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_string(payload, content_type="application/octet-stream")
    return f"gs://{bucket_name}/{blob_name}"


def upload_file(bucket_name: str, blob_name: str, source_path: str | Path) -> str:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for GCS uploads") from exc
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)
    blob.upload_from_filename(str(source_path))
    return f"gs://{bucket_name}/{blob_name}"


def list_recent_blobs(
    bucket_name: str,
    prefix: str = "realtime/trip_updates/",
    limit: int = 24,
) -> list[str]:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for GCS reads") from exc
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blobs = sorted(
        bucket.list_blobs(prefix=prefix),
        key=lambda blob: blob.name,
        reverse=True,
    )
    return [blob.name for blob in blobs[:limit]]


def download_blobs(
    bucket_name: str,
    blob_names: list[str],
    output_dir: str | Path,
) -> list[Path]:
    try:
        from google.cloud import storage
    except ImportError as exc:
        raise RuntimeError("google-cloud-storage is required for GCS reads") from exc
    client = storage.Client()
    bucket = client.bucket(bucket_name)
    target = Path(output_dir)
    paths: list[Path] = []
    for blob_name in blob_names:
        local_path = target / blob_name
        local_path.parent.mkdir(parents=True, exist_ok=True)
        bucket.blob(blob_name).download_to_filename(local_path)
        paths.append(local_path)
    return paths
