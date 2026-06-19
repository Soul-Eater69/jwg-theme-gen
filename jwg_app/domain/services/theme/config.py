"""Theme generation tuning config.

Knobs the handler reads but that are not prompt/model content (which live in user_config.yaml).
Injected into the handler with sensible defaults; tests and callers can override.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import FrozenSet


@dataclass(frozen=True)
class RetryConfig:
    """Retry policy for transient LLM gateway failures (rate limit / 5xx / timeout).

    Bounded and non-exponential: a small fixed delay (plus jitter) keeps worst-case latency
    predictable across the 4+N calls and within the API request time budget.
    """

    enabled: bool = True
    max_attempts: int = 3  # total attempts per call (1 = no retry)
    delay_seconds: float = 1.0  # base delay between attempts; a small jitter is added
    retryable_status: FrozenSet[int] = frozenset({429, 500, 502, 503, 504})

    def attempts(self) -> int:
        """Total attempts to make: ``max_attempts`` when enabled, else a single attempt."""
        return self.max_attempts if self.enabled else 1


@dataclass(frozen=True)
class ThemeGenerationConfig:
    """Top-level tuning config for theme generation."""

    retry: RetryConfig = field(default_factory=RetryConfig)
