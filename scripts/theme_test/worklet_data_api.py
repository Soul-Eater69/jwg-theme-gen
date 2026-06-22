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


class _Property:
    """A worklet property: {propertyName, propertyValue} once dumped."""

    def __init__(self, property_name: str, property_value: Any) -> None:
        self.property_name = property_name
        self.property_value = property_value


def _name(prop: Any) -> Any:
    if isinstance(prop, dict):
        return prop.get("propertyName", prop.get("property_name"))
    return getattr(prop, "property_name", None)


def _value(prop: Any) -> Any:
    if isinstance(prop, dict):
        return prop.get("propertyValue", prop.get("property_value"))
    return getattr(prop, "property_value", None)


class Worklet:
    """Minimal stand-in for the prod Worklet envelope (the fields + property API the mapper uses)."""

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

    def get_property_value(self, name: str) -> Any:
        for p in self.properties:
            if _name(p) == name:
                return _value(p)
        return None

    def upsert_property(self, *, name: str, value: Any) -> None:
        for p in self.properties:
            if _name(p) == name:
                if isinstance(p, dict):
                    p["propertyValue"] = value
                else:
                    p.property_value = value
                return
        self.properties.append(_Property(name, value))

    def __repr__(self) -> str:
        return (
            f"<Worklet id={self.id} source_id={self.source_id} "
            f"type={self.worklet_type} props={len(self.properties)}>"
        )
