"""
Maps between the Worklet envelope and the theme-generation domain.

All Worklet-to-domain translation lives here, so the handler orchestrates and never indexes worklet
properties by hand. The property-name strings are the only coupling to the worklet shape and are
kept together in this module.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from worklet_data_api import Worklet

from jwg_app.domain.models.base import Property
from jwg_app.domain.models.theme_generation import (
    ValueStreamCatalogue,
    ERContext,
    L2Capability,
    L3Capability,
    SelectedStage,
    VSContext,
)


def get_property(worklet: Worklet, name: str, default: Any = None) -> Any:
    """
    Read a worklet property value by name.

    Args:
        worklet: The worklet to read from.
        name: The property name to look up.
        default: The value to return when the property is absent.

    Returns:
        The first property value with ``name``, or ``default`` when absent.
    """
    for p in worklet.properties:
        if p.property_name == name:
            return p.property_value
    return default


def set_property(worklet: Worklet, name: str, value: Any) -> None:
    """
    Write a worklet property value by name.

    Updates the existing property when present, otherwise appends a new one.

    Args:
        worklet: The worklet to write to.
        name: The property name to set.
        value: The value to store.
    """
    for p in worklet.properties:
        if p.property_name == name:
            p.property_value = value
            return
    worklet.properties.append(Property(property_name=name, property_value=value))


class ERProps:
    TITLE = "title"
    RAW_TEXT = "rawText"




class ThemeProps:
    TITLE = "title"
    DESCRIPTION = "description"
    BUSINESS_NEEDS = "Business Needs"
    GENERATED_BY_LLM = "generatedByLLM"
    SELECTED_STAGES = "selectedStages"
    L3 = "L3 Business Capability"
    L2 = "L2 Business Capability"


def value_stream_id(theme_stub: Worklet) -> str:
    """
    Read the Value Stream id for a theme stub - its ``parentWorkletId`` (the catalogue lookup key).

    Args:
        theme_stub: The THEME worklet stub (parentWorkletId = the value-stream id).

    Returns:
        The Value Stream id.
    """
    return theme_stub.parent_worklet_id or ""


def to_er_context(er_worklet: Worklet) -> ERContext:
    """
    Extract the ticket fields that ground theme generation: the id, title, and raw text.

    Generation reads the raw ticket text only ("raw to decide"), so no summary-derived fields are read.

    Args:
        er_worklet: The engagement-request worklet.

    Returns:
        The engagement-request context.
    """
    return ERContext(
        idmt_ticket_title=get_property(er_worklet, ERProps.TITLE, ""),
        raw_text=get_property(er_worklet, ERProps.RAW_TEXT, ""),
    )


def to_vs_context(vs_id: str, catalogue: ValueStreamCatalogue) -> VSContext:
    """
    Build the value-stream context from the catalogue. Every attribute (name, description, value
    proposition, trigger) comes from the governed catalogue; only the id is passed in.

    Args:
        vs_id: The value-stream id (from the theme stub's parentWorkletId).
        catalogue: The catalogue record for this value stream.

    Returns:
        The value-stream context.
    """
    vs = catalogue.value_stream
    return VSContext(
        vs_id=vs_id,
        vs_name=vs.name,
        vs_description=vs.description,
        value_proposition=vs.value_proposition,
        trigger=vs.trigger,
    )


def to_theme_worklet(
    theme_stub: Worklet,
    *,
    title: str,
    description: str,
    business_needs: str,
    selected_stages: Sequence[SelectedStage],
    l3: Sequence[L3Capability],
    l2: Sequence[L2Capability],
) -> Worklet:
    """
    Attach the generated theme content onto the theme stub and return it.

    The stub's existing properties (and its identity/parentWorkletId) are preserved; the generated
    properties below are added, or overwritten if already present (e.g. on a re-run). The stub is
    edited in place - the API layer persists the same worklet.

    Args:
        theme_stub: The THEME worklet stub to enrich (edited in place).
        title: The Theme title.
        description: The Theme description.
        business_needs: The Business Needs text.
        selected_stages: The stages selected for the value stream.
        l3: The selected L3 capabilities.
        l2: The derived L2 capabilities.

    Returns:
        The same theme stub, with the generated theme properties attached.
    """
    # CamelModel forces by_alias on model_dump, so the property values serialize camelCase.
    properties = {
        ThemeProps.TITLE: title,
        ThemeProps.DESCRIPTION: description,
        ThemeProps.BUSINESS_NEEDS: business_needs,
        ThemeProps.GENERATED_BY_LLM: True,
        ThemeProps.SELECTED_STAGES: [s.model_dump() for s in selected_stages],
        ThemeProps.L3: [c.model_dump() for c in l3],
        ThemeProps.L2: [c.model_dump() for c in l2],
    }

    for name, value in properties.items():
        set_property(theme_stub, name, value)

    return theme_stub
