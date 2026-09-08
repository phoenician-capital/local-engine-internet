"""Thread-safe fetch cache — port of Earnings_tracker fetch_cache.py."""
from __future__ import annotations

import threading
import time
from typing import Any, Optional


class FetchCache:
    """Bounded TTL cache. Failures use a shorter TTL (negative caching)."""

    def __init__(
        self,
        max_entries: int = 256,
        ttl_seconds: float = 1800.0,
        failure_ttl_seconds: float = 120.0,
    ):
        self._store: dict[str, tuple[float, Any, bool]] = {}
        self._lock = threading.Lock()
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._failure_ttl = failure_ttl_seconds
        self.hits = 0
        self.misses = 0

    def get(self, url: str) -> Optional[Any]:
        if not url:
            return None
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(url)
            if entry is None:
                self.misses += 1
                return None
            expires_at, value, _ok = entry
            if expires_at < now:
                self._store.pop(url, None)
                self.misses += 1
                return None
            self.hits += 1
            return value

    def has(self, url: str) -> bool:
        if not url:
            return False
        now = time.monotonic()
        with self._lock:
            entry = self._store.get(url)
            if entry is None:
                return False
            if entry[0] < now:
                self._store.pop(url, None)
                return False
            return True

    def set(self, url: str, value: Any, ok: bool = True) -> None:
        if not url:
            return
        now = time.monotonic()
        ttl = self._ttl if ok else self._failure_ttl
        with self._lock:
            if url not in self._store and len(self._store) >= self._max_entries:
                self._evict_locked(now)
            self._store[url] = (now + ttl, value, ok)

    def _evict_locked(self, now: float) -> None:
        expired = [k for k, (exp, _v, _o) in self._store.items() if exp < now]
        for k in expired:
            self._store.pop(k, None)
        if len(self._store) >= self._max_entries and self._store:
            soonest = min(self._store, key=lambda k: self._store[k][0])
            self._store.pop(soonest, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()
            self.hits = 0
            self.misses = 0
