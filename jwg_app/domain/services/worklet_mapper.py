"""Data Mapper between the API Worklet envelope and the theme-generation domain.

All Worklet <-> domain translation lives here, so the handler orchestrates and never indexes
worklet properties by hand. The property-name strings are the only coupling to the worklet shape
and are the single place to reconcile with the prod worklets.
"""

from __future__ import annotations

from collections.abc import Sequence

from jwg_app.domain.models.theme_generation import (
    AzureSQLData,
    ERContext,
    L2Capability,
    L3Capability,
    SelectedStage,
    VSContext,
)
from jwg_app.domain.models.base import RecordState, WorkletType
from jwg_app.domain.models.worklet import Worklet, get_property, set_property


class ERProps:
    TITLE = "title"
    RAW_TEXT = "rawText"
    DOCS_SUMMARY = "Docs Summary"


class DocsSummaryKeys:
    BUSINESS_PROBLEM = "businessProblem"
    BUSINESS_CAPABILITY = "businessCapability"
    KEY_TERMS = "keyTerms"
    STAKEHOLDERS = "stakeholders"
    SYSTEMS = "systemsAndProducts"


class VSProps:
    TITLE = "title"
    DESCRIPTION = "valueStreamDescription"


class ThemeProps:
    TITLE = "title"
    DESCRIPTION = "description"
    BUSINESS_NEEDS = "Business Needs"
    RATIONALE = "Rationale"
    GENERATED_BY_LLM = "generatedByLLM"
    SELECTED_STAGES = "selectedStages"
    L3 = "L3 Business Capability"
    L2 = "L2 Business Capability"


def value_stream_id(vs_worklet: Worklet) -> str:
    """Return the external Value Stream id used for catalogue lookups."""
    return _worklet_identity(vs_worklet)


def to_er_context(er_worklet: Worklet) -> ERContext:
    """Extract the ticket fields that ground all theme-generation prompts."""
    summary = get_property(er_worklet, ERProps.DOCS_SUMMARY)
    summary = summary if isinstance(summary, dict) else {}  # guarded: the next lines call .get()

    return ERContext(
        idmt_ticket_id=_worklet_identity(er_worklet),
        idmt_ticket_title=get_property(er_worklet, ERProps.TITLE, ""),
        generated_summary=get_property(er_worklet, ERProps.RAW_TEXT, ""),
        business_problem=summary.get(DocsSummaryKeys.BUSINESS_PROBLEM, ""),
        business_capability=summary.get(DocsSummaryKeys.BUSINESS_CAPABILITY, ""),
        key_terms=summary.get(DocsSummaryKeys.KEY_TERMS, []),
        stakeholders=summary.get(DocsSummaryKeys.STAKEHOLDERS, []),
        systems_and_products=summary.get(DocsSummaryKeys.SYSTEMS, []),
    )


def to_vs_context(vs_worklet: Worklet, catalogue: AzureSQLData) -> VSContext:
    """Combine VS worklet fields with governed catalogue enrichment."""
    vs = catalogue.value_stream

    return VSContext(
        vs_id=value_stream_id(vs_worklet),
        vs_name=get_property(vs_worklet, VSProps.TITLE, ""),
        vs_description=get_property(vs_worklet, VSProps.DESCRIPTION, ""),
        value_proposition=vs.value_proposition,
        trigger=vs.trigger,
        assumptions=vs.assumptions,
    )


def to_theme_worklet(
    vs_worklet: Worklet,
    *,
    title: str,
    description: str,
    business_needs: str,
    selected_stages: Sequence[SelectedStage],
    l3: Sequence[L3Capability],
    l2: Sequence[L2Capability],
) -> Worklet:
    """Build the unsaved THEME worklet returned to the API layer for persistence."""
    theme = Worklet(
        id=None,
        worklet_type=WorkletType.THEME,
        parent_worklet_id=vs_worklet.id,
        source_id=None,
        state=RecordState.CREATED,
    )

    # CamelModel forces by_alias on model_dump, so the property values serialize camelCase.
    properties = {
        ThemeProps.TITLE: title,
        ThemeProps.DESCRIPTION: description,
        ThemeProps.BUSINESS_NEEDS: business_needs,
        ThemeProps.RATIONALE: "",
        ThemeProps.GENERATED_BY_LLM: True,
        ThemeProps.SELECTED_STAGES: [s.model_dump() for s in selected_stages],
        ThemeProps.L3: [c.model_dump() for c in l3],
        ThemeProps.L2: [c.model_dump() for c in l2],
    }

    for name, value in properties.items():
        set_property(theme, name, value)

    return theme


def _worklet_identity(worklet: Worklet) -> str:
    return worklet.source_id or worklet.id or ""
