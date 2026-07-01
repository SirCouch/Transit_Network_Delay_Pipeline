from __future__ import annotations

import httpx


def fetch_bytes(url: str, timeout_seconds: float = 30.0) -> bytes:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content

