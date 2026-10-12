"""Helpers shared by the ingestion modules."""
from __future__ import annotations

import hashlib
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=None)
def _digest(path: str, size: int, mtime: float) -> str:
    sha = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            sha.update(block)
    return sha.hexdigest()[:16]


def file_digest(path: Path) -> str:
    """Short content hash of a source file. Cached responses are keyed on it, not on rendered
    pixels, so a replay works on a machine whose JPEG encoder produces different bytes."""
    stat = path.stat()
    return _digest(str(path), stat.st_size, stat.st_mtime)
