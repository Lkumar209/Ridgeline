"""Downloads retry transient failures with backoff and fail at once on other errors."""

from pathlib import Path

import httpx
import pytest

from ridgeline.data.cache import download

URL = "https://example.test/file.parquet"


def _client(outcomes: list[int | Exception]) -> tuple[httpx.Client, list[int]]:
    """A client whose successive requests return these statuses or raise these errors."""
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        outcome = outcomes[len(calls) - 1]
        if isinstance(outcome, Exception):
            raise outcome
        return httpx.Response(outcome, content=b"data" if outcome == 200 else b"")

    return httpx.Client(transport=httpx.MockTransport(handler)), calls


def test_transient_failures_are_retried_with_backoff(tmp_path: Path) -> None:
    client, calls = _client([httpx.ConnectError("reset"), 503, 429, 200])
    waits: list[float] = []
    dest = download(URL, tmp_path / "f.parquet", client, sleep=waits.append)
    assert dest.read_bytes() == b"data"
    assert len(calls) == 4
    assert waits == [2.0, 4.0, 8.0]
    assert not (tmp_path / "f.parquet.part").exists()


def test_gives_up_after_the_last_attempt(tmp_path: Path) -> None:
    client, calls = _client([500, 500, 500, 500])
    waits: list[float] = []
    with pytest.raises(httpx.HTTPStatusError):
        download(URL, tmp_path / "f.parquet", client, sleep=waits.append)
    assert len(calls) == 4
    assert len(waits) == 3
    assert not (tmp_path / "f.parquet").exists()


@pytest.mark.parametrize("status", [403, 404])
def test_client_errors_are_not_retried(tmp_path: Path, status: int) -> None:
    """A 403 from a blocking proxy must surface at once, naming the URL, not be retried."""
    client, calls = _client([status, 200])
    waits: list[float] = []
    with pytest.raises(httpx.HTTPStatusError, match=r"example\.test"):
        download(URL, tmp_path / "f.parquet", client, sleep=waits.append)
    assert len(calls) == 1
    assert waits == []


def test_cached_file_is_not_downloaded_again(tmp_path: Path) -> None:
    dest = tmp_path / "f.parquet"
    dest.write_bytes(b"cached")
    client, calls = _client([500])
    assert download(URL, dest, client).read_bytes() == b"cached"
    assert calls == []
