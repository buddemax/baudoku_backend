import time
from typing import Protocol


class RateLimitExceededError(Exception):
    """Raised when an action exceeds its configured request quota."""


class RateLimiterProtocol(Protocol):
    def check(self, key: str) -> None:
        """Record one request for the key or raise if the quota is exhausted."""


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int) -> None:
        self._limit = limit
        self._window_seconds = window_seconds
        self._events: dict[str, tuple[float, ...]] = {}

    def check(self, key: str) -> None:
        if self._limit <= 0:
            return

        now = time.monotonic()
        oldest_allowed = now - self._window_seconds
        recent_events = tuple(
            event_time
            for event_time in self._events.get(key, ())
            if event_time >= oldest_allowed
        )
        if len(recent_events) >= self._limit:
            self._events = {**self._events, key: recent_events}
            raise RateLimitExceededError

        self._events = {**self._events, key: (*recent_events, now)}
