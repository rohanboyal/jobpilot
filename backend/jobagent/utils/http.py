"""Shared HTTP client that says who it is (JobPilot, not a browser), retries on 429/5xx, and paces itself politely."""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

UA = "JobPilot/0.1 (personal job-search tool; +https://github.com/rohanboyal/jobpilot)"

DEFAULT_HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def make_client(timeout: float = 30.0, **kw: Any) -> httpx.Client:
    headers = {**DEFAULT_HEADERS, **kw.pop("headers", {})}
    return httpx.Client(timeout=timeout, follow_redirects=True, headers=headers, **kw)


class HttpError(RuntimeError):
    def __init__(self, status: int, url: str, body: str = ""):
        super().__init__(f"HTTP {status} for {url}")
        self.status = status
        self.url = url
        self.body = body


def get(client: httpx.Client, url: str, *, params: dict | None = None, retries: int = 3,
        backoff: float = 1.5, headers: dict | None = None) -> httpx.Response:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = client.get(url, params=params, headers=headers)
            if r.status_code == 404:
                raise HttpError(404, str(r.url), r.text[:300])
            if r.status_code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                wait = backoff * (2**attempt) + random.uniform(0, 0.8)
                ra = r.headers.get("Retry-After")
                if ra and ra.isdigit():
                    wait = max(wait, float(ra))
                time.sleep(min(wait, 20))
                continue
            if r.status_code >= 400:
                raise HttpError(r.status_code, str(r.url), r.text[:300])
            return r
        except (httpx.TransportError, httpx.TimeoutException) as e:
            last = e
            time.sleep(backoff * (attempt + 1))
    raise RuntimeError(f"request failed for {url}: {last}")


def get_json(client: httpx.Client, url: str, **kw: Any) -> Any:
    r = get(client, url, **kw)
    try:
        return r.json()
    except ValueError as e:
        raise RuntimeError(f"non-JSON response from {url}: {r.text[:120]!r}") from e


def polite_sleep(base: float = 0.6, jitter: float = 0.6) -> None:
    time.sleep(base + random.uniform(0, jitter))
