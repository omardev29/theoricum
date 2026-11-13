"""A small, polite HTTP client (stdlib only): fixed User-Agent, delay between requests, retries."""

import contextlib
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from pathlib import Path

from theoricum import __version__

USER_AGENT = f"theoricum/{__version__} (practica personal del teórico DGT; +https://github.com/)"
CHUNK = 1 << 20

Progress = Callable[[int, int | None], None]  # bytes so far, total (None if unknown)


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

    def _with_retries[T](
        self,
        url: str,
        read: Callable[[object], T],
        *,
        delay: float | None = None,
        headers: dict[str, str] | None = None,
    ) -> T | None:
        """Open `url` and `read` the response; None on 404/410. Retries transient errors."""
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._wait(delay)
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, **(headers or {})}
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return read(response)
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

    def _open(
        self, url: str, *, delay: float | None = None, headers: dict[str, str] | None = None
    ) -> bytes | None:
        return self._with_retries(
            url, lambda response: response.read(), delay=delay, headers=headers
        )

    def get_text(self, url: str, *, headers: dict[str, str] | None = None) -> str | None:
        body = self._open(url, headers=headers)
        return None if body is None else body.decode("utf-8", errors="replace")

    def exists(self, url: str) -> bool:
        return self._open(url) is not None

    def download(
        self,
        url: str,
        target: Path,
        *,
        delay: float | None = None,
        progress: Progress | None = None,
    ) -> bool:
        """Stream `url` into `target` (through a `.part` file). False if it could not be done."""
        tmp = target.with_name(target.name + ".part")

        def save(response) -> bool:
            length = response.headers.get("Content-Length")
            total = int(length) if length and length.isdigit() else None
            done = 0
            with tmp.open("wb") as out:
                while chunk := response.read(CHUNK):
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, total)
            return done > 0

        try:
            ok = self._with_retries(url, save, delay=delay)
        except ConnectionError, OSError:
            ok = False
        if not ok:
            with contextlib.suppress(OSError):
                tmp.unlink(missing_ok=True)
            return False
        tmp.replace(target)
        return True
