"""Download-once file cache under `data/cache/` (gitignored)."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

TIMEOUT_S = 120.0


def download(url: str, dest: Path, client: httpx.Client, *, force: bool = False) -> Path:
    """Fetch `url` to `dest` unless it already exists. Writes atomically via a temp file."""
    if dest.exists() and not force:
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    log.info("downloading %s", url)
    with client.stream("GET", url, timeout=TIMEOUT_S) as response:
        response.raise_for_status()
        with tmp.open("wb") as f:
            for chunk in response.iter_bytes():
                f.write(chunk)
    tmp.replace(dest)
    return dest
