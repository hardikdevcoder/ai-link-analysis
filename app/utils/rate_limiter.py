"""Tiny in-memory rate limiter to protect a public deployment.

Two limits:
  1. per IP address, per minute (stops one person hammering the API)
  2. whole server, per day (stops a surprise API bill)

In-memory means it resets when the server restarts and is not shared between
several server copies. A production setup would use Redis instead.
"""
import time
from collections import defaultdict, deque
from datetime import date
from typing import Deque, Dict, Optional


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int):
        self.per_minute = per_minute
        self.per_day = per_day
        self._hits = defaultdict(deque)          # type: Dict[str, Deque[float]]
        self._day = date.today()
        self._day_count = 0

    def check(self, key: str) -> Optional[str]:
        """Return None if allowed (and count it), or a message explaining why not."""
        now = time.time()

        today = date.today()
        if today != self._day:
            self._day, self._day_count = today, 0
        if self._day_count >= self.per_day:
            return "Daily analysis limit reached. Please try again tomorrow."

        window = self._hits[key]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= self.per_minute:
            return "Too many requests. Please wait a minute and try again."

        window.append(now)
        self._day_count += 1
        return None

    def reset(self) -> None:
        self._hits.clear()
        self._day_count = 0