"""Worklet property helpers.

The ``Worklet`` type comes from the platform ``worklet_data_api`` package — we do not define it.
These helpers read/write a property by name on the worklet's ``Property`` list so the handler and
mapper never index it by hand.
"""

from __future__ import annotations

from typing import Any

from worklet_data_api import Worklet

from jwg_app.domain.models.base import Property


def get_property(worklet: Worklet, name: str, default: Any = None) -> Any:
    """Return the first property value with ``name``, or ``default`` when absent."""
    for p in worklet.properties:
        if p.property_name == name:
            return p.property_value
    return default


def set_property(worklet: Worklet, name: str, value: Any) -> None:
    """Set an existing property value or append a new property when absent."""
    for p in worklet.properties:
        if p.property_name == name:
            p.property_value = value
            return
    worklet.properties.append(Property(property_name=name, property_value=value))
