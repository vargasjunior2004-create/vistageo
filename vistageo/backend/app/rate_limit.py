import os
import threading
import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def clear(self) -> None:
        with self._lock:
            self._hits.clear()

    def hit(self, key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._hits[key]
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(window_seconds - (now - bucket[0]) + 0.999))
                return False, retry_after
            bucket.append(now)
            return True, 0


limiter = RateLimiter()


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        return default
    return value if value > 0 else default


def login_rate_limits() -> tuple[int, int, int, int]:
    ip_limit = _env_int("LOGIN_RATE_LIMIT_IP", 20)
    ip_window = _env_int("LOGIN_RATE_LIMIT_IP_WINDOW_SECONDS", 300)
    account_limit = _env_int("LOGIN_RATE_LIMIT_ACCOUNT", 10)
    account_window = _env_int("LOGIN_RATE_LIMIT_ACCOUNT_WINDOW_SECONDS", 300)
    return ip_limit, ip_window, account_limit, account_window
