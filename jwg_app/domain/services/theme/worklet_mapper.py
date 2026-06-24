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

from jwg_app.domain.models.base import WorkletType
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

    Uses the worklet's native ``get_property_value`` when available; otherwise reads the
    ``properties`` list directly. Reading the list keeps this working across Worklet variants whose
    envelope does not expose the helper methods (the property entries are ``{propertyName,
    propertyValue}``, as objects or dicts).

    Args:
        worklet: The worklet to read from.
        name: The property name to look up.
        default: The value to return when the property is absent.

    Returns:
        The property value with ``name``, or ``default`` when absent.
    """
    getter = getattr(worklet, "get_property_value", None)
    if callable(getter):
        value = getter(name)
        return default if value is None else value
    for prop in getattr(worklet, "properties", None) or []:
        if _prop_name(prop) == name:
            value = _prop_value(prop)
            return default if value is None else value
    return default


def set_property(worklet: Worklet, name: str, value: Any) -> None:
    """
    Write a worklet property value by name (updated when present, appended otherwise).

    Uses the worklet's native ``upsert_property`` when available; otherwise updates/appends the
    ``properties`` list directly so the property is stored in the worklet's own ``{propertyName,
    propertyValue}`` shape regardless of the Worklet variant.

    Args:
        worklet: The worklet to write to.
        name: The property name to set.
        value: The value to store.
    """
    upsert = getattr(worklet, "upsert_property", None)
    if callable(upsert):
        upsert(name=name, value=value)
        return
    for prop in getattr(worklet, "properties", None) or []:
        if _prop_name(prop) == name:
            _set_prop_value(prop, value)
            return
    worklet.properties.append({"propertyName": name, "propertyValue": value})


def _prop_name(prop: Any) -> Any:
    if isinstance(prop, dict):
        return prop.get("propertyName", prop.get("property_name"))
    return getattr(prop, "property_name", getattr(prop, "propertyName", None))


def _prop_value(prop: Any) -> Any:
    if isinstance(prop, dict):
        return prop.get("propertyValue", prop.get("property_value"))
    return getattr(prop, "property_value", getattr(prop, "propertyValue", None))


def _set_prop_value(prop: Any, value: Any) -> None:
    if isinstance(prop, dict):
        prop["propertyValue" if "propertyValue" in prop else "property_value"] = value
    elif hasattr(prop, "property_value"):
        prop.property_value = value
    else:
        prop.propertyValue = value


class ERProps:
    TITLE = "title"
    RAW_TEXT = "rawText"


class ThemeProps:
    VALUE_STREAM_ID = "valueStreamId"  # input only: the business VS id (the SQL catalogue key)
    SUMMARY = "summary"
    DESCRIPTION = "description"
    BUSINESS_NEEDS = "businessNeeds"
    GENERATED_BY_LLM = "generatedByLLM"
    # These three are id -> "name {id}" maps (key = the catalogue id), not lists.
    SELECTED_TAGS = "selectedTags"
    L3 = "l3BusinessCapabilityModel"
    L2 = "l2BusinessCapabilityModel"


def value_stream_id(vs_worklet: Worklet) -> str:
    """
    Read the Value Stream id (the SQL catalogue lookup key) from the VS worklet's ``valueStreamId``
    property.

    This is the business id (e.g. ``VS10000372``), NOT the worklet's internal ``id``.

    Args:
        vs_worklet: The value-stream worklet.

    Returns:
        The Value Stream id.
    """
    return get_property(vs_worklet, ThemeProps.VALUE_STREAM_ID, "")


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
        vs_id: The value-stream id (from the VS worklet's valueStreamId property).
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


def _id_label_map(items: Sequence[Any], *, id_of, name_of) -> dict[str, str]:
    """Build the ``{ id: "<name> {id}" }`` map used for the stage/L3/L2 properties (key = the id)."""
    return {id_of(i): f"{name_of(i)} {{{id_of(i)}}}" for i in items}


def to_theme_worklet(
    vs_worklet: Worklet,
    *,
    summary: str,
    description: str,
    business_needs: str,
    selected_stages: Sequence[SelectedStage],
    l3: Sequence[L3Capability],
    l2: Sequence[L2Capability],
) -> Worklet:
    """
    Generate a new THEME worklet from the generated content, parented to the value-stream worklet.

    The theme worklet is **created** (not an enriched stub): its ``parent_worklet_id`` is the VS
    worklet's id, its ``worklet_type`` is ``THEME``, its ``source_id`` carries down from the VS
    worklet, and its ``properties`` are the generated theme content (as
    ``{propertyName, propertyValue}`` entries). Stages, L3, and L2 are stored as ``{ id: "name {id}" }``
    maps (key = the catalogue id), not lists.

    Args:
        vs_worklet: The value-stream worklet this theme is generated under (its id becomes the
            theme's parent id).
        summary: The Theme summary (``"<ticket title> - <vs name>"``).
        description: The Theme description.
        business_needs: The Business Needs text.
        selected_stages: The stages selected for the value stream.
        l3: The selected L3 capabilities.
        l2: The derived L2 capabilities.

    Returns:
        A new THEME worklet parented to ``vs_worklet``.
    """
    properties = {
        ThemeProps.SUMMARY: summary,
        ThemeProps.DESCRIPTION: description,
        ThemeProps.BUSINESS_NEEDS: business_needs,
        ThemeProps.GENERATED_BY_LLM: True,
        ThemeProps.SELECTED_TAGS: _id_label_map(
            selected_stages, id_of=lambda s: s.stage_id, name_of=lambda s: s.stage_name
        ),
        ThemeProps.L3: _id_label_map(l3, id_of=lambda c: c.id, name_of=lambda c: c.name),
        ThemeProps.L2: _id_label_map(l2, id_of=lambda c: c.id, name_of=lambda c: c.name),
    }
    return Worklet(
        worklet_type=WorkletType.THEME,
        parent_worklet_id=vs_worklet.id,
        source_id=vs_worklet.source_id,
        properties=[
            {"propertyName": name, "propertyValue": value} for name, value in properties.items()
        ],
    )
