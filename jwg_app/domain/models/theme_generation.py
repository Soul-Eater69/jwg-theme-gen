"""
Theme generation data models.

Input contexts (engagement request + value stream), the catalogue read (value stream attributes,
its stages, and its L3 capabilities), the per-call LLM output schemas (batched across all approved
value streams), and the resolved capability records. These are the contracts the theme generation
handler and its prompts read and write; the API ``Worklet`` shape comes from the shared models and
is assembled at the boundary.
"""

from __future__ import annotations

from typing import List

from pydantic import BaseModel, Field

from jwg_app.domain.models.base import CamelModel


class VSContext(BaseModel):
    """An approved Value Stream a Theme is generated for."""

    vs_id: str
    vs_name: str
    vs_description: str
    # catalogue enrichment (stage selection reads both; business needs reads the proposition):
    value_proposition: str = ""
    trigger: str = ""


class ERContext(BaseModel):
    """The Engagement Request context read from the ER worklet.

    ``raw_text`` is the raw ticket text - the only ticket input generation reads ("raw to decide").
    """

    idmt_ticket_title: str
    raw_text: str


class ValueStage(BaseModel):
    """A candidate lifecycle stage from the catalogue for a Value Stream."""

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


class ValueStreamAttributes(BaseModel):
    """A Value Stream's own catalogue attributes. The worklet supplies only the id; name,
    description, value proposition, and trigger all come from the governed catalogue."""

    name: str = ""
    description: str = ""
    value_proposition: str = ""
    trigger: str = ""


class ValueStreamCatalogue(BaseModel):
    """One Value Stream's catalogue read: its attributes, candidate stages, and full L3 list (each
    L3 carries its parent L2 inline). The catalogue is fetched for all approved value streams at once
    and keyed by ``vs_id`` (``dict[str, ValueStreamCatalogue]``)."""

    value_stream: ValueStreamAttributes = Field(default_factory=ValueStreamAttributes)
    stage_list: List[ValueStage] = Field(default_factory=list)
    l3_capabilities: List[L3Capability] = Field(default_factory=list)


class SelectedStage(CamelModel):
    """A stage the work runs through. Name and scope (description, entrance/exit) are canonical from
    the catalogue: the model echoes the name as a selection anchor and we overwrite it - and fill the
    scope - on resolve, so downstream prompts (business needs, capabilities) see the full stage."""

    stage_id: str
    stage_name: str = ""
    stage_description: str = ""
    entrance_criteria: str = ""
    exit_criteria: str = ""
    reason: str = ""


# The raw model picks ``agenerate`` validates against; the handler resolves them against the
# catalogue into the domain records above.

class VsStageSelection(CamelModel):
    """One Value Stream's stage picks (batched stage-selection entry). Empty -> the architect
    takes the whole lifecycle."""

    value_stream_id: str
    selected_stages: List[SelectedStage] = Field(default_factory=list)


class BatchedStageSelection(CamelModel):
    """Stage selection output: one entry per approved Value Stream."""

    value_streams: List[VsStageSelection] = Field(default_factory=list)


class CapabilityPick(CamelModel):
    capability_id: str
    name: str = ""
    reason: str = ""


class StageCapabilityPicks(CamelModel):
    stage_id: str
    capabilities: List[CapabilityPick] = Field(default_factory=list)


class BatchedCapabilitySelection(CamelModel):
    """Merged capability output: picks keyed by stageId, across every approved Value Stream."""

    stages: List[StageCapabilityPicks] = Field(default_factory=list)


class VsFraming(CamelModel):
    value_stream_id: str
    text: str = ""


class FramingsOut(CamelModel):
    """Description-framing output: one opening paragraph per approved Value Stream."""

    framings: List[VsFraming] = Field(default_factory=list)


class TextOut(CamelModel):
    """A single free-text output. Used by both the description body and business needs calls."""

    text: str = ""
