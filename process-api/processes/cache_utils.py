"""Shared in-memory TTL cache used by all PAVICS and MSC backends."""

from __future__ import annotations

import threading
import time
from typing import Dict, Generic, Optional, Tuple, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    """In-memory cache with per-entry TTL eviction on read."""

    def __init__(self, ttl: int) -> None:
        self._ttl = ttl
        self._store: Dict[str, Tuple[float, T]] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[T]:
        with self._lock:
            entry = self._store.get(key)
            if entry is None:
                return None
            timestamp, value = entry
            if time.monotonic() - timestamp > self._ttl:
                del self._store[key]
                return None
            return value

    def set(self, key: str, value: T) -> None:
        with self._lock:
            self._store[key] = (time.monotonic(), value)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
