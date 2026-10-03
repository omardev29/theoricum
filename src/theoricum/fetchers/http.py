"""A small, polite HTTP client (stdlib only): fixed User-Agent, delay between requests, retries."""

import time
import urllib.error
import urllib.request
from pathlib import Path

from theoricum import __version__

USER_AGENT = f"theoricum/{__version__} (practica personal del teórico DGT; +https://github.com/)"


class HttpClient:
    def __init__(self, *, delay: float = 1.0, timeout: float = 30.0, retries: int = 3) -> None:
        self.delay = delay
        self.timeout = timeout
        self.retries = retries
        self._last_request = 0.0

    def _wait(self, delay: float | None) -> None:
        pause = (self.delay if delay is None else delay) - (time.monotonic() - self._last_request)
        if pause > 0:
            time.sleep(pause)
        self._last_request = time.monotonic()

    def _open(self, url: str, *, method: str = "GET", delay: float | None = None) -> bytes | None:
        """Return the body, or None on 404. Retries transient errors with backoff."""
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._wait(delay)
            request = urllib.request.Request(url, method=method, headers={"User-Agent": USER_AGENT})
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return response.read() if method == "GET" else b""
            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    return None
                last_error = exc
                if exc.code < 500 and exc.code != 429:
                    break
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                last_error = exc
            time.sleep(2**attempt)
        raise ConnectionError(f"no se pudo descargar {url}: {last_error}")

    def get_text(self, url: str) -> str | None:
        body = self._open(url)
        return None if body is None else body.decode("utf-8", errors="replace")

    def exists(self, url: str) -> bool:
        return self._open(url) is not None

    def download(self, url: str, target: Path, *, delay: float | None = None) -> bool:
        try:
            body = self._open(url, delay=delay)
        except ConnectionError:
            return False
        if not body:
            return False
        tmp = target.with_name(target.name + ".part")
        tmp.write_bytes(body)
        tmp.replace(target)
        return True
