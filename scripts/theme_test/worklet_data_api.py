"""Local stub of the prod `worklet_data_api` package — FOR TESTING ONLY.

The real package lives in production. This stub provides just enough (Worklet + WorkletState) for the
theme generation handler/mapper to import and run in a test harness. The smoke script puts this
folder on sys.path so `from worklet_data_api import Worklet` resolves here instead of prod.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, List, Optional


class WorkletState(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class Worklet:
    """Minimal stand-in for the prod Worklet envelope (the fields the mapper reads/writes)."""

    def __init__(
        self,
        id: Optional[str] = None,
        source_id: Optional[str] = None,
        parent_worklet_id: Optional[str] = None,
        worklet_type: Any = None,
        state: Any = None,
        properties: Optional[List[Any]] = None,
    ) -> None:
        self.id = id
        self.source_id = source_id
        self.parent_worklet_id = parent_worklet_id
        self.worklet_type = worklet_type
        self.state = state
        self.properties = properties if properties is not None else []

    def __repr__(self) -> str:
        return (
            f"<Worklet id={self.id} source_id={self.source_id} "
            f"type={self.worklet_type} props={len(self.properties)}>"
        )
