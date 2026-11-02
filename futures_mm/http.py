from __future__ import annotations

import logging
import time

import requests

log = logging.getLogger(__name__)


class Http:
    """requests.Session with retries, backoff on 429/5xx and a minimum gap between calls."""

    def __init__(self, base: str, min_gap_s: float = 0.1, timeout: float = 15.0):
        self.base = base.rstrip("/")
        self.s = requests.Session()
        self.s.headers["User-Agent"] = "futures-mm-research/0.1"
        self.min_gap_s = min_gap_s
        self.timeout = timeout
        self._last = 0.0

    def _request(self, method: str, path: str, **kw):
        url = path if path.startswith("http") else f"{self.base}/{path.lstrip('/')}"
        for attempt in range(5):
            wait = self.min_gap_s - (time.monotonic() - self._last)
            if wait > 0:
                time.sleep(wait)
            self._last = time.monotonic()
            try:
                r = self.s.request(method, url, timeout=self.timeout, **kw)
            except requests.RequestException as e:
                log.warning("%s %s failed (%s), retry %d", method, url, e, attempt + 1)
                time.sleep(2**attempt)
                continue
            if r.status_code == 429 or r.status_code >= 500:
                log.warning("%s %s -> %d, retry %d", method, url, r.status_code, attempt + 1)
                time.sleep(2**attempt)
                continue
            r.raise_for_status()
            return r
        raise RuntimeError(f"giving up on {method} {url}")

    def get(self, path: str, **params):
        return self._request("GET", path, params=params).json()

    def get_raw(self, path: str, **params) -> requests.Response:
        return self._request("GET", path, params=params)

    def post(self, path: str, json):
        return self._request("POST", path, json=json).json()
