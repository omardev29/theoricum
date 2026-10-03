"""Resolve image references to raw bytes.

Refs are stored relative to the questions folder so that moving it never breaks anything:
  file:<path>             a regular file inside questions/
  apkg:<path>!<member>    a media member inside an Anki package (zstd-compressed or not)
"""

import threading
import zipfile
from pathlib import Path

ZSTD_MAGIC = b"\x28\xb5\x2f\xfd"


class MediaError(Exception):
    pass


class MediaResolver:
    def __init__(self, questions_dir: Path) -> None:
        self.questions_dir = questions_dir.resolve()
        self._zips: dict[Path, tuple[int, zipfile.ZipFile]] = {}
        self._lock = threading.Lock()

    def read(self, ref: str) -> bytes:
        kind, _, rest = ref.partition(":")
        if kind == "file":
            return self._inside(rest).read_bytes()
        if kind == "apkg":
            path, _, member = rest.rpartition("!")
            if not path or not member:
                raise MediaError(f"referencia de imagen no válida: {ref}")
            data = self._read_member(self._inside(path), member)
            if data[:4] == ZSTD_MAGIC:
                from compression import zstd

                data = zstd.decompress(data)
            return data
        raise MediaError(f"tipo de referencia de imagen desconocido: {ref}")

    def path_for(self, ref: str) -> Path | None:
        """Filesystem path of a `file:` ref (None for refs that live inside archives)."""
        kind, _, rest = ref.partition(":")
        return self._inside(rest) if kind == "file" else None

    def close(self) -> None:
        with self._lock:
            for _, zf in self._zips.values():
                zf.close()
            self._zips.clear()

    def _inside(self, rel: str) -> Path:
        path = (self.questions_dir / rel).resolve()
        if not path.is_relative_to(self.questions_dir):
            raise MediaError(f"la imagen sale de la carpeta de preguntas: {rel}")
        return path

    def _read_member(self, path: Path, member: str) -> bytes:
        with self._lock:
            mtime = path.stat().st_mtime_ns
            cached = self._zips.get(path)
            if cached is None or cached[0] != mtime:
                if cached is not None:
                    cached[1].close()
                cached = (mtime, zipfile.ZipFile(path))
                self._zips[path] = cached
            try:
                return cached[1].read(member)
            except KeyError as exc:
                raise MediaError(f"no existe «{member}» en {path.name}") from exc
