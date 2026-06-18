"""Builds the context strings fed INTO the theme-generation prompts.

Pure and stateless: each function turns the ER/VS/catalogue inputs into the ``{ticket_context}`` /
``{value_streams}`` / ``{selected_stages}`` blocks a prompt expects. The handler passes these as
the prompt template variables.
"""

from __future__ import annotations

from collections.abc import Sequence

from jwg_app.domain.models.theme_generation import (
    ERContext,
    L3Capability,
    SelectedStage,
    ValueStage,
    VSContext,
)


def ticket_context(er: ERContext) -> str:
    """The ``{ticket_context}`` block every prompt reads. ``generated_summary`` carries the RAW text."""
    lines = [f"- content: {er.generated_summary}"]
    if er.business_problem:
        lines.append(f"- businessProblem: {er.business_problem}")
    if er.business_capability:
        lines.append(f"- businessCapability: {er.business_capability}")
    if er.key_terms:
        lines.append(f"- keyTerms: {', '.join(er.key_terms)}")
    if er.stakeholders:
        lines.append(f"- stakeholders: {', '.join(er.stakeholders)}")
    if er.systems_and_products:
        lines.append(f"- systemsAndProducts: {', '.join(er.systems_and_products)}")
    return "\n".join(lines)


def stage_value_streams(pairs: Sequence[tuple[VSContext, Sequence[ValueStage]]]) -> str:
    """The ``{value_streams}`` block for stage selection: each VS + its candidate stages."""
    return "\n\n".join(_vs_stage_block(vs, stages) for vs, stages in pairs)


def capability_value_streams(
    groups: Sequence[tuple[VSContext, Sequence[tuple[SelectedStage, Sequence[L3Capability]]]]]
) -> str:
    """The ``{value_streams}`` block for capability selection: each VS -> its selected stages ->
    that stage's own candidate L3."""
    return "\n\n".join(_vs_l3_block(vs, stage_caps) for vs, stage_caps in groups)


def framing_value_streams(vs_list: Sequence[VSContext]) -> str:
    """The ``{value_streams}`` block for description framing: id/name/description/valueProposition."""
    blocks = []
    for vs in vs_list:
        lines = [f"- valueStreamId: {vs.vs_id}", f"  valueStreamName: {vs.vs_name}"]
        if vs.vs_description:
            lines.append(f"  valueStreamDescription: {vs.vs_description}")
        if vs.value_proposition:
            lines.append(f"  valueProposition: {vs.value_proposition}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def selected_stages(stages: Sequence[SelectedStage]) -> str:
    """The ``{selected_stages}`` block for business needs."""
    return "\n".join(f"[{s.stage_id}] {s.stage_name}" for s in stages)


# ---- block builders -------------------------------------------------------------------

def _vs_stage_block(vs: VSContext, stages: Sequence[ValueStage]) -> str:
    lines = [f"### Value stream {vs.vs_id}", f"Name: {vs.vs_name}"]
    lines += _vs_attribute_lines(vs)
    lines.append("Candidate stages:")
    lines.append("\n".join(_stage_line(s) for s in stages))
    return "\n".join(lines)


def _vs_l3_block(
    vs: VSContext, stage_caps: Sequence[tuple[SelectedStage, Sequence[L3Capability]]]
) -> str:
    head = [f"### Value Stream {vs.vs_id} — {vs.vs_name}", *_vs_attribute_lines(vs, lower=True)]
    blocks = ["\n".join(head)]
    for stage, caps in stage_caps:
        lines = [
            f"### Stage {stage.stage_id}",
            f"[{stage.stage_id}] {stage.stage_name}",
            "Candidate L3 capabilities (choose by id; each shows its parent L2):",
            *(_l3_line(c) for c in caps),
        ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _vs_attribute_lines(vs: VSContext, *, lower: bool = False) -> list[str]:
    """The shared VS attribute lines (description / value proposition / trigger), present when set.
    ``lower`` selects the lowercase label style the capability block uses."""
    labels = (
        ("description", "value proposition", "trigger") if lower
        else ("Description", "Value proposition", "Trigger")
    )
    values = (vs.vs_description, vs.value_proposition, vs.trigger)
    return [f"{label}: {value}" for label, value in zip(labels, values) if value]


def _stage_line(s: ValueStage) -> str:
    desc = f"\ndescription: {s.stage_description}" if s.stage_description else ""
    crit = ""
    if s.entrance_criteria or s.exit_criteria:
        crit = f"\nentrance: {s.entrance_criteria} | exit: {s.exit_criteria}"
    return f"[{s.stage_id}] {s.stage_name}{desc}{crit}"


def _l3_line(c: L3Capability) -> str:
    desc = f" - {c.description}" if c.description else ""
    parent = f" (L2: {c.level_two_name})" if c.level_two_name else ""
    return f"- {c.id} | {c.name}{desc}{parent}"
