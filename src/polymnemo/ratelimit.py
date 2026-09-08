"""Rate limiting — one global (per-process) token bucket via pyrate-limiter.

Deliberately simple: *not* per-user. It caps this instance's overall intake to
protect it from overload (embedding is CPU-bound). In-memory and per-process —
under Cloud Run's multiple instances each caps its own intake, which is what
protects each instance, so no shared state / database is needed.

Disabled by default: ``build_context`` sets ``AppContext.rate_limiter`` to
``None`` unless ``POLYMNEMO_RATELIMIT_ENABLED`` is set.
"""

from __future__ import annotations

from pyrate_limiter import BucketFullException, Duration, Limiter, Rate


class RateLimitError(Exception):
    """Raised when the global rate limit is exceeded."""


class GlobalRateLimiter:
    """One token bucket shared by all callers on this process."""

    _KEY = "global"

    def __init__(self, per_min: int) -> None:
        self._limiter = Limiter(Rate(per_min, Duration.MINUTE))

    def check(self, cost: int = 1) -> None:
        """Consume ``cost`` tokens; raise :class:`RateLimitError` if over the
        limit. ``cost`` (an int weight) lets embed-heavy tools count for more."""
        try:
            self._limiter.try_acquire(self._KEY, weight=cost)
        except BucketFullException as exc:
            raise RateLimitError("rate limit exceeded — please slow down.") from exc
