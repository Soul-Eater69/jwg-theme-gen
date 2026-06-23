"""Theme generation tuning config.

Knobs the handler reads but that are not prompt/model content (which live in user_config.yaml).
Injected into the handler with sensible defaults; tests and callers can override. The LLM retry
policy is the shared ``RetryConfig`` (so other generation modules reuse the same one).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from jwg_app.infrastructure.external.retry_config import RetryConfig

__all__ = ["RetryConfig", "ThemeGenerationConfig"]


@dataclass(frozen=True)
class ThemeGenerationConfig:
    """Top-level tuning config for theme generation."""

    retry: RetryConfig = field(default_factory=RetryConfig)
