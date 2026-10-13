"""Tiny TTL cache: in-memory first, JSON on disk second, so restarts and upstream outages are survivable."""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

from app.config import settings

_memory: dict[str, tuple[float, Any]] = {}


def _path(key: str) -> Path:
    digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:20]
    return settings.cache_dir / f"{digest}.json"


def get(key: str, ttl_s: float, *, allow_stale: bool = False) -> Any | None:
    now = time.time()
    hit = _memory.get(key)
    if hit and (allow_stale or now - hit[0] < ttl_s):
        return hit[1]
    path = _path(key)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            stamp = float(payload.get("_ts", 0))
            if allow_stale or now - stamp < ttl_s:
                _memory[key] = (stamp, payload["value"])
                return payload["value"]
        except (ValueError, KeyError, OSError):
            return None
    return None


def put(key: str, value: Any) -> None:
    now = time.time()
    _memory[key] = (now, value)
    try:
        _path(key).write_text(json.dumps({"_ts": now, "value": value}), encoding="utf-8")
    except OSError:
        pass


def age_s(key: str) -> float | None:
    hit = _memory.get(key)
    if hit:
        return time.time() - hit[0]
    path = _path(key)
    if path.exists():
        try:
            return time.time() - float(json.loads(path.read_text(encoding="utf-8")).get("_ts", 0))
        except (ValueError, OSError):
            return None
    return None
