"""Theme generation data models.

Input contexts (ER + VS), the governed catalogue payload (Azure SQL), the per-call LLM output
schemas (batched across all approved Value Streams), and the resolved capability records. These
are the contracts the theme generation handler and its prompts read/write; the API ``Worklet``
shape comes from the shared models and is assembled at the boundary.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from jwg_app.domain.models.base import CamelModel


# ---- input contexts -------------------------------------------------------------------

class VSContext(BaseModel):
    """An approved Value Stream a Theme is generated for."""

    vs_id: str
    vs_name: str
    vs_description: str
    # governed-catalogue enrichment (stage selection reads all three; business needs the proposition):
    value_proposition: str = ""
    trigger: str = ""
    assumptions: str = ""


class ERContext(BaseModel):
    """The normalized Engagement Request context (from the ER worklet's condensed fields).

    ``generated_summary`` carries the RAW ticket text in the generation path.
    """

    idmt_ticket_id: str
    idmt_ticket_title: str
    generated_summary: str
    business_problem: str
    business_capability: str
    key_terms: List[str] = Field(default_factory=list)
    stakeholders: List[str] = Field(default_factory=list)
    systems_and_products: List[str] = Field(default_factory=list)


# ---- governed catalogue (Azure SQL) ---------------------------------------------------

class ValueStage(BaseModel):
    """A candidate lifecycle stage from the governed catalogue for a Value Stream."""

    stage_id: str
    stage_name: str
    stage_description: str = ""
    entrance_criteria: str = ""
    exit_criteria: str = ""


class L3Capability(CamelModel):
    """An L3 business capability. ``llm_selected`` is set by the capability call and immutable;
    ``selected`` starts equal to ``llm_selected`` and is toggled by the user via upsert."""

    id: str
    name: str
    description: str = ""
    stage_id: str
    level_two_id: str
    level_two_name: str
    llm_selected: bool = False
    selected: bool = False


class L2Capability(CamelModel):
    """An L2 capability, derived 1:1 from the selected L3 (no LLM). ``selected`` is True on
    derivation and toggled by the user via upsert."""

    id: str
    name: str
    description: str = ""
    stage_id: str
    selected: bool = True


class VSCatalogue(BaseModel):
    """A Value Stream's governed attributes (enrich generation)."""

    value_proposition: str = ""
    trigger: str = ""
    assumptions: str = ""


class AzureSQLData(BaseModel):
    """One Value Stream's governed read: its attributes, candidate stages, and full L3 list (each
    L3 carries its parent L2 inline). The catalogue is fetched for all approved VS at once and keyed
    by ``vs_id`` (``dict[str, AzureSQLData]``)."""

    value_stream: VSCatalogue = Field(default_factory=VSCatalogue)
    stage_list: List[ValueStage] = Field(default_factory=list)
    l3_capabilities: List[L3Capability] = Field(default_factory=list)


# ---- resolved domain records ----------------------------------------------------------

class SelectedStage(CamelModel):
    """A stage the work runs through. Names are canonical from the catalogue; the model echoes the
    name as a selection anchor and we overwrite it on resolve."""

    stage_id: str
    stage_name: str = ""
    reason: str = ""


# ---- LLM output schemas (batched; one structured payload per prompt) ------------------
# The RAW model picks ``agenerate`` validates against; the handler resolves them against the
# governed catalogue into the domain records above.

class VsStageSelection(BaseModel):
    """One Value Stream's stage picks (batched stage-selection entry). Empty -> the architect
    takes the whole lifecycle."""

    value_stream_id: str
    selected_stages: List[SelectedStage] = Field(default_factory=list)


class BatchedStageSelection(BaseModel):
    """Stage selection output: one entry per approved Value Stream."""

    value_streams: List[VsStageSelection] = Field(default_factory=list)


class CapabilityPick(BaseModel):
    capability_id: str
    name: str = ""
    reason: str = ""


class StageCapabilityPicks(BaseModel):
    stage_id: str
    capabilities: List[CapabilityPick] = Field(default_factory=list)


class BatchedCapabilitySelection(BaseModel):
    """Merged capability output: picks keyed by stageId, across every approved Value Stream."""

    stages: List[StageCapabilityPicks] = Field(default_factory=list)


class VsFraming(BaseModel):
    value_stream_id: str
    text: str = ""


class FramingsOut(BaseModel):
    """Description-framing output: one opening paragraph per approved Value Stream."""

    framings: List[VsFraming] = Field(default_factory=list)


class TextOut(BaseModel):
    """A single free-text output. Used by both the description body and business needs calls."""

    text: str = ""
