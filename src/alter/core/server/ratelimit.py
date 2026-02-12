from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass, field


@dataclass
class RateLimiter:
    max_per_minute: int
    _hits: dict[str, deque[float]] = field(default_factory=dict)

    def allow(self, key: str) -> bool:
        if self.max_per_minute <= 0:
            return True
        now = time.monotonic()
        window_start = now - 60.0
        q = self._hits.get(key)
        if q is None:
            q = deque()
            self._hits[key] = q
        while q and q[0] < window_start:
            q.popleft()
        if len(q) >= self.max_per_minute:
            return False
        q.append(now)
        return True

