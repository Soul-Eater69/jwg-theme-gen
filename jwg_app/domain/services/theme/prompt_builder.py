"""
Builds the context strings fed into the theme-generation prompts.

Each function turns the engagement-request and value-stream inputs into one of the prompt template
blocks (ticket context, value streams, selected stages). The functions are pure and stateless: the
handler fills each prompt template with whatever these return.
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
    """
    Build the ticket-context block that every prompt reads.

    Generation reads the raw ticket text only ("raw to decide"); summary-derived fields are not part
    of the generation prompts, per the prompt I/O contract. ``raw_text`` carries that raw ticket text.

    Args:
        er: The engagement-request context extracted from the ticket worklet.

    Returns:
        The ticket-context block as prompt-ready text.
    """
    return f"- content: {er.raw_text}"


def stage_value_streams(pairs: Sequence[tuple[VSContext, Sequence[ValueStage]]]) -> str:
    """
    Build the value-streams block for stage selection.

    Renders each approved value stream together with its own candidate stages, so one call can
    select stages for every value stream at once.

    Args:
        pairs: Each approved value stream paired with its candidate stages.

    Returns:
        The value-streams block as prompt-ready text.
    """
    return "\n\n".join(_vs_stage_block(vs, stages) for vs, stages in pairs)


def capability_value_streams(
    groups: Sequence[tuple[VSContext, Sequence[tuple[SelectedStage, Sequence[L3Capability]]]]]
) -> str:
    """
    Build the value-streams block for capability selection.

    Renders each value stream, its selected stages, and each stage's own candidate L3 capabilities,
    so one call can select capabilities across every stage at once.

    Args:
        groups: Each value stream paired with its selected stages and each stage's candidate L3 list.

    Returns:
        The value-streams block as prompt-ready text.
    """
    return "\n\n".join(_vs_l3_block(vs, stage_caps) for vs, stage_caps in groups)


def framing_value_streams(vs_list: Sequence[VSContext]) -> str:
    """
    Build the value-streams block for description framing.

    Renders each value stream's id, name, description, and value proposition for its opening
    paragraph.

    Args:
        vs_list: The approved value streams to frame.

    Returns:
        The value-streams block as prompt-ready text.
    """
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
    """
    Build the selected-stages block for business needs.

    Args:
        stages: The stages chosen for one value stream.

    Returns:
        The selected-stages block as prompt-ready text.
    """
    return "\n".join(f"[{s.stage_id}] {s.stage_name}" for s in stages)


def _vs_stage_block(vs: VSContext, stages: Sequence[ValueStage]) -> str:
    """Render one value stream and its candidate stages for the stage-selection block."""
    lines = [*_vs_header(vs), "Candidate stages:", *(_stage_line(s) for s in stages)]
    return "\n".join(lines)


def _vs_l3_block(
    vs: VSContext, stage_caps: Sequence[tuple[SelectedStage, Sequence[L3Capability]]]
) -> str:
    """Render one value stream, its selected stages, and each stage's candidate L3 capabilities."""
    blocks = ["\n".join(_vs_header(vs))]
    for stage, caps in stage_caps:
        lines = [
            f"### Stage {stage.stage_id}: {stage.stage_name}",
            "Candidate L3 capabilities (choose by id; each shows its parent L2):",
            *(_l3_line(c) for c in caps),
        ]
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def _vs_header(vs: VSContext) -> list[str]:
    """Render the shared value-stream header: name plus the attributes that are set."""
    lines = [f"## Value Stream {vs.vs_id}", f"Name: {vs.vs_name}"]
    labels = ("Description", "Value proposition", "Trigger")
    values = (vs.vs_description, vs.value_proposition, vs.trigger)
    lines += [f"{label}: {value}" for label, value in zip(labels, values) if value]
    return lines


def _stage_line(s: ValueStage) -> str:
    """Render one candidate-stage line with its optional description and entrance/exit criteria."""
    desc = f"\nDescription: {s.stage_description}" if s.stage_description else ""
    crit = ""
    if s.entrance_criteria or s.exit_criteria:
        crit = f"\nEntrance: {s.entrance_criteria} | Exit: {s.exit_criteria}"
    return f"[{s.stage_id}] {s.stage_name}{desc}{crit}"


def _l3_line(c: L3Capability) -> str:
    """Render one candidate L3-capability line with its optional description and parent L2."""
    desc = f" - {c.description}" if c.description else ""
    parent = f" (L2: {c.level_two_name})" if c.level_two_name else ""
    return f"[{c.id}] {c.name}{desc}{parent}"
