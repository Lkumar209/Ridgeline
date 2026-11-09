"""Download-once file cache under `data/cache/` (gitignored)."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

TIMEOUT_S = 120.0
# Transient failures (dropped connections, timeouts, 429 and 5xx) are retried with exponential
# backoff: waits of 2, 4 and 8 s across 4 attempts. Other 4xx responses, such as a 403 from a
# proxy blocking the domain, fail at once so the blocked domain is reported, not retried.
ATTEMPTS = 4
BACKOFF_S = 2.0


def _retryable(error: Exception) -> bool:
    if isinstance(error, httpx.HTTPStatusError):
        status = error.response.status_code
        return status == 429 or status >= 500
    return isinstance(error, httpx.TransportError)


def download(
    url: str,
    dest: Path,
    client: httpx.Client,
    *,
    force: bool = False,
    attempts: int = ATTEMPTS,
    sleep: Callable[[float], None] = time.sleep,
) -> Path:
    """Fetch `url` to `dest` unless it already exists. Writes atomically via a temp file."""
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, attempts + 1):
        log.info("downloading %s", url)
        try:
            with client.stream("GET", url, timeout=TIMEOUT_S) as response:
                response.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in response.iter_bytes():
                        f.write(chunk)
        except (httpx.HTTPStatusError, httpx.TransportError) as e:
            tmp.unlink(missing_ok=True)
            if attempt == attempts or not _retryable(e):
                raise
            wait = BACKOFF_S * 2 ** (attempt - 1)
            log.warning(
                "download failed (%s); retry %d/%d in %.0fs", e, attempt, attempts - 1, wait
            )
            sleep(wait)
            continue
        tmp.replace(dest)
        return dest
    raise AssertionError("unreachable")  # pragma: no cover
