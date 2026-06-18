"""Abstraction for the platform LLM client the handler depends on (DIP).

The handler needs exactly one capability — a structured-output chat completion — so the
Protocol declares only that (ISP). The concrete ``PlatformRestClient`` already satisfies it
via ``agenerate``; tests inject a fake.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, Tuple, Type

from pydantic import BaseModel


class PlatformClient(Protocol):
    async def agenerate(
        self,
        *,
        message: List[Dict[str, str]],
        output_function: Optional[Type[BaseModel]] = None,
        model_params: Optional[Dict[str, Any]] = None,
        trace_id: Optional[str] = None,
        bearer_token: Optional[str] = None,
    ) -> Tuple[Any, Optional[str], int]:
        """Return ``(payload, error, status)``. With ``output_function`` set, ``payload`` is the
        parsed JSON object validated against that schema; otherwise it is the text response."""
        ...
