from __future__ import annotations

import time
from collections import OrderedDict


class DedupCache:
    def __init__(self, *, ttl_sec: int, max_keys: int) -> None:
        if ttl_sec <= 0:
            raise ValueError("ttl_sec must be > 0")
        if max_keys <= 0:
            raise ValueError("max_keys must be > 0")
        self._ttl_sec = ttl_sec
        self._max_keys = max_keys
        self._seen: OrderedDict[str, float] = OrderedDict()

    def seen_recently(self, key: str) -> bool:
        now = time.time()
        self._prune(now)

        ts = self._seen.get(key)
        if ts is None:
            self._seen[key] = now
            self._enforce_max()
            return False

        # Refresh recency.
        self._seen.move_to_end(key)
        return (now - ts) <= self._ttl_sec

    def _enforce_max(self) -> None:
        while len(self._seen) > self._max_keys:
            self._seen.popitem(last=False)

    def _prune(self, now: float) -> None:
        cutoff = now - self._ttl_sec
        while self._seen:
            _, ts = next(iter(self._seen.items()))
            if ts > cutoff:
                break
            self._seen.popitem(last=False)
