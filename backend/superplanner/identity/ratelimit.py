"""Per-token request rate limit (M5-DESIGN 3.3: 600 requests / minute). In-process fixed windows per API replica
(16.WP-S: the auth buckets of M2 live in PostgreSQL; a DB write per bearer request would cost the AP1 budget)."""

from __future__ import annotations

import threading
import time

from ..api.errors import ApiError

_lock = threading.Lock()
_windows: dict[str, tuple[int, int]] = {}


def token_hit(ctx: object, token_id: str, now: float | None = None) -> None:
    limit = int(getattr(getattr(ctx, "settings", None), "token_rate_per_minute", 600))
    minute = int((now if now is not None else time.time()) // 60)
    with _lock:
        win, n = _windows.get(token_id, (minute, 0))
        if win != minute:
            win, n = minute, 0
        n += 1
        _windows[token_id] = (win, n)
        if len(_windows) > 50_000:
            for k in [k for k, (w, _n) in _windows.items() if w != minute]:
                _windows.pop(k, None)
    if n > limit:
        raise ApiError(429, "RATE_LIMITED", "Too many requests for this API token; slow down.", {},
                       headers={"Retry-After": str(60 - int((now or time.time()) % 60))})
