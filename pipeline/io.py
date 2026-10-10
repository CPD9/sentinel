"""Atomic file writes. A reader never sees a half-written file, and a failed write keeps the old one."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def write_bytes_atomic(path: str | Path, data: bytes) -> Path:
    """Temp file in the same directory, flush + fsync, then os.replace (atomic on POSIX)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass
        raise
    return path


def write_json_atomic(path: str | Path, obj: Any, indent: int | None = 2) -> Path:
    """Serialise first (a TypeError leaves nothing behind), then write atomically."""
    data = (json.dumps(obj, ensure_ascii=False, indent=indent) + "\n").encode("utf-8")
    return write_bytes_atomic(path, data)
