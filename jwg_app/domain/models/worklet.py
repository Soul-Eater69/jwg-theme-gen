"""Worklet envelope (reconstructed from the API request/response examples).

STAGING ONLY — on integration, replace this with the prod `Worklet` model import. A worklet is
a generic typed envelope whose payload is a list of name/value ``properties``. Helpers read/write
a property by name so the handler doesn't index the list by hand.
"""

from __future__ import annotations

from typing import Any, List, Optional

from pydantic import BaseModel, Field


class WorkletProperty(BaseModel):
    propertyName: str
    propertyValue: Any = None


class Worklet(BaseModel):
    id: Optional[str] = None
    workletType: str = ""               # "ER" | "VS" | "THEME"
    parentWorkletId: Optional[str] = None
    sourceId: Optional[str] = None
    properties: List[WorkletProperty] = Field(default_factory=list)
    state: Optional[str] = None         # e.g. "C"
    currentUser: Optional[dict] = None
    workletMap: dict = Field(default_factory=dict)
    userHistory: list = Field(default_factory=list)


def get_property(worklet: Worklet, name: str, default: Any = None) -> Any:
    """Return the first property value with ``name``, or ``default`` when absent."""
    for p in worklet.properties:
        if p.propertyName == name:
            return p.propertyValue
    return default


def set_property(worklet: Worklet, name: str, value: Any) -> None:
    """Set an existing property value or append a new property when absent."""
    for p in worklet.properties:
        if p.propertyName == name:
            p.propertyValue = value
            return
    worklet.properties.append(WorkletProperty(propertyName=name, propertyValue=value))
