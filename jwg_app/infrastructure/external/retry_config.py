"""Retry policy for LLM gateway calls — shared across generation modules.

A small, bounded, non-exponential retry for transient gateway failures (rate limit / 5xx / timeout):
a fixed delay plus jitter keeps worst-case latency predictable and within the API request budget.
Any LLM-calling service (theme, value stream, stage generation) can reuse this — it is not
theme-specific.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet


@dataclass(frozen=True)
class RetryConfig:
    """Retry policy for transient LLM gateway failures (rate limit / 5xx / timeout)."""

    enabled: bool = True
    max_attempts: int = 3  # total attempts per call (1 = no retry)
    delay_seconds: float = 1.0  # base delay between attempts; a small jitter is added
    # Only clearly-transient statuses. 500 is excluded: the gateway folds real bugs (bad payload,
    # config) into 500, so retrying it just burns attempts - fail fast and surface the error.
    retryable_status: FrozenSet[int] = frozenset({429, 502, 503, 504})

    def attempts(self) -> int:
        """Total attempts to make: ``max_attempts`` when enabled, else a single attempt."""
        return self.max_attempts if self.enabled else 1
