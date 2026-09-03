"""
Tests for cache_utils.py TTLCache in-memory cache.

Markers:
  @pytest.mark.unit    — pure Python logic, no I/O
"""

from __future__ import annotations

import time

import pytest
from processes.cache_utils import TTLCache

# ---------------------------------------------------------------------------
# TestTTLCache
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTTLCache:
    def setup_method(self) -> None:
        self.cache: TTLCache[str] = TTLCache(ttl=3600)

    def test_miss_returns_none(self) -> None:
        assert self.cache.get("nonexistent") is None

    def test_set_then_get_returns_value(self) -> None:
        self.cache.set("key1", "value1")
        assert self.cache.get("key1") == "value1"

    def test_overwrite_updates_value(self) -> None:
        self.cache.set("key1", "old")
        self.cache.set("key1", "new")
        assert self.cache.get("key1") == "new"

    def test_clear_empties_all_entries(self) -> None:
        self.cache.set("a", "1")
        self.cache.set("b", "2")
        self.cache.clear()
        assert self.cache.get("a") is None
        assert self.cache.get("b") is None

    def test_expired_entry_returns_none(self, monkeypatch) -> None:
        self.cache.set("expiring", "data")
        monkeypatch.setattr(self.cache, "_ttl", 0)
        time.sleep(0.01)
        assert self.cache.get("expiring") is None

    def test_not_expired_entry_still_returned(self) -> None:
        self.cache.set("fresh", "data")
        assert self.cache.get("fresh") == "data"

    def test_different_keys_independent(self) -> None:
        self.cache.set("k1", "v1")
        self.cache.set("k2", "v2")
        assert self.cache.get("k1") == "v1"
        assert self.cache.get("k2") == "v2"

    def test_generic_type_int(self) -> None:
        int_cache: TTLCache[int] = TTLCache(ttl=3600)
        int_cache.set("count", 42)
        assert int_cache.get("count") == 42

    def test_generic_type_dict(self) -> None:
        dict_cache: TTLCache[dict] = TTLCache(ttl=3600)
        payload = {"result": [1, 2, 3]}
        dict_cache.set("payload", payload)
        assert dict_cache.get("payload") == payload

    def test_expired_entry_removed_from_store(self, monkeypatch) -> None:
        self.cache.set("stale", "old")
        monkeypatch.setattr(self.cache, "_ttl", 0)
        time.sleep(0.01)
        self.cache.get("stale")
        assert "stale" not in self.cache._store
