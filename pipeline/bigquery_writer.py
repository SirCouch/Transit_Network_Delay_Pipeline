from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Iterable


class BigQueryWriter:
    def __init__(self, project_id: str):
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise RuntimeError("google-cloud-bigquery is required for BigQuery writes") from exc
        self._client = bigquery.Client(project=project_id)

    def append_rows(self, table_ref: str, rows: Iterable[object]) -> None:
        payload = [_as_row(row) for row in rows]
        if not payload:
            return
        errors = self._client.insert_rows_json(table_ref, payload)
        if errors:
            raise RuntimeError(f"BigQuery insert failed for {table_ref}: {errors}")

    def replace_rows(self, table_ref: str, rows: Iterable[object]) -> None:
        payload = [_as_row(row) for row in rows]
        try:
            from google.cloud import bigquery
        except ImportError as exc:
            raise RuntimeError("google-cloud-bigquery is required for BigQuery writes") from exc
        job_config = bigquery.LoadJobConfig(
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            autodetect=False,
        )
        job = self._client.load_table_from_json(payload, table_ref, job_config=job_config)
        job.result()


def _as_row(row: object) -> dict[str, object]:
    if is_dataclass(row):
        return asdict(row)
    if isinstance(row, dict):
        return row
    raise TypeError(f"Unsupported BigQuery row type: {type(row)!r}")
