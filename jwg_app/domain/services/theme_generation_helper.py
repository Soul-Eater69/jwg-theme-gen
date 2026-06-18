"""Pure helpers for theme generation: prompt-context rendering + LLM-output resolution.

Stateless and side-effect-free (SRP) — every function maps inputs to a string or a resolved
record, so the handler stays focused on orchestration. The batched calls (stage selection and
capabilities) cover ALL approved Value Streams at once; resolution keeps each pick under its
governed owner (strict isolation) with a salvage net for any mislink.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from jwg_app.domain.models.theme_generation import (
    BatchedCapabilitySelection,
    BatchedStageSelection,
    ERContext,
    FramingsOut,
    L2Capability,
    L3Capability,
    SelectedStage,
    ValueStage,
    VSContext,
)


# ---- theme title + description assembly (domain composition) --------------------------

def theme_title(er: ERContext, vs: VSContext) -> str:
    """The THEME title: «idmtTicketTitle -- valueStreamName», from the resolved contexts."""
    return f"{er.idmt_ticket_title} -- {vs.vs_name}"


def assemble_description(framing: str, body: str) -> str:
    """Per-VS Theme description: the VS framing paragraph over the shared body."""
    parts = []
    if framing.strip():
        parts.append("Theme Description:\n" + framing.strip())
    if body.strip():
        parts.append(body.strip())
    return "\n\n".join(parts)


# ---- prompt-context rendering ---------------------------------------------------------

def ticket_context(er: ERContext) -> str:
    """The ticket block every generation prompt reads. ``generated_summary`` carries the RAW text."""
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
    """The ``{value_streams}`` block for the batched stage prompt: each VS + its candidate stages."""
    return "\n\n".join(_vs_stage_block(vs, stages) for vs, stages in pairs)


def capability_value_streams(
    groups: Sequence[tuple[VSContext, Sequence[tuple[SelectedStage, Sequence[L3Capability]]]]]
) -> str:
    """The ``{value_streams}`` block for the merged capability prompt: each VS -> its selected
    stages -> each stage's own candidate L3."""
    return "\n\n".join(_vs_l3_block(vs, stage_caps) for vs, stage_caps in groups)


def framing_value_streams(vs_list: Sequence[VSContext]) -> str:
    """The ``{value_streams}`` block for the description-framing prompt."""
    blocks = []
    for vs in vs_list:
        lines = [f"- valueStreamId: {vs.vs_id}", f"  valueStreamName: {vs.vs_name}"]
        if vs.vs_description:
            lines.append(f"  valueStreamDescription: {vs.vs_description}")
        if vs.value_proposition:
            lines.append(f"  valueProposition: {vs.value_proposition}")
        blocks.append("\n".join(lines))
    return "\n".join(blocks)


def render_selected_stages(stages: Sequence[SelectedStage]) -> str:
    """The selected-stage list for the business-needs prompt."""
    return "\n".join(f"[{s.stage_id}] {s.stage_name}" for s in stages)


def _vs_stage_block(vs: VSContext, stages: Sequence[ValueStage]) -> str:
    lines = [f"### Value stream {vs.vs_id}", f"Name: {vs.vs_name}"]
    if vs.vs_description:
        lines.append(f"Description: {vs.vs_description}")
    if vs.value_proposition:
        lines.append(f"Value proposition: {vs.value_proposition}")
    if vs.trigger:
        lines.append(f"Trigger: {vs.trigger}")
    lines.append("Candidate stages:")
    lines.append("\n".join(_stage_line(s) for s in stages))
    return "\n".join(lines)


def _vs_l3_block(
    vs: VSContext, stage_caps: Sequence[tuple[SelectedStage, Sequence[L3Capability]]]
) -> str:
    head = [f"### Value Stream {vs.vs_id} — {vs.vs_name}"]
    if vs.vs_description:
        head.append(f"description: {vs.vs_description}")
    if vs.value_proposition:
        head.append(f"value proposition: {vs.value_proposition}")
    if vs.trigger:
        head.append(f"trigger: {vs.trigger}")
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


# ---- LLM-output resolution (batched picks -> governed records) ------------------------

def resolve_framings(out: FramingsOut, vs_ids: Sequence[str]) -> dict[str, str]:
    """One framing paragraph per approved VS, driven by our ids (not the model's output): a VS the
    model omits gets "" (the description still has the shared body); an unknown id is ignored."""
    by_vs = {f.value_stream_id: f.text for f in out.framings}
    return {vs_id: by_vs.get(vs_id, "") for vs_id in vs_ids}


def resolve_stages_for_all(
    out: BatchedStageSelection, stage_lists: Mapping[str, Sequence[ValueStage]]
) -> dict[str, list[SelectedStage]]:
    """Per VS: keep only that VS's governed stage ids (canonical name); empty/all-invalid -> the
    whole list so no approved VS is left without stages. Salvage reassigns a stage the model put
    under the wrong VS (ids are globally unique) to its true owner."""
    by_vs = {entry.value_stream_id: entry for entry in out.value_streams}
    resolved: dict[str, list[SelectedStage]] = {}
    raw_picks: dict[str, list[str]] = {}
    for vs_id, stages in stage_lists.items():
        entry = by_vs.get(vs_id)
        resolved[vs_id] = _resolve_vs_stages(entry.selected_stages if entry else [], stages)
        raw_picks[vs_id] = [item.stage_id for item in (entry.selected_stages if entry else [])]

    owner_of = {s.stage_id: vs_id for vs_id, stages in stage_lists.items() for s in stages}
    for picker_vs, picks in raw_picks.items():
        for stage_id in picks:
            owner_vs = owner_of.get(stage_id)
            if owner_vs is None or owner_vs == picker_vs:
                continue
            current = resolved[owner_vs]
            if any(s.stage_id == stage_id for s in current):
                continue
            stage = next(s for s in stage_lists[owner_vs] if s.stage_id == stage_id)
            current.append(SelectedStage(stage_id=stage_id, stage_name=stage.stage_name))
    return resolved


def resolve_l3_merged(
    out: BatchedCapabilitySelection, candidates_by_stage: Mapping[str, Sequence[L3Capability]]
) -> dict[str, list[L3Capability]]:
    """Per stage: keep only ids governed for THAT stage (canonical record), deduped, with
    ``llm_selected=True``. Salvage reassigns a capability the model put under the wrong stage to
    its true owner (ids are globally unique). Returns ``{stage_id: [L3Capability]}``."""
    by_stage = {entry.stage_id: entry for entry in out.stages}
    resolved: dict[str, list[L3Capability]] = {}
    raw_picks: dict[str, list[str]] = {}
    for stage_id, candidates in candidates_by_stage.items():
        entry = by_stage.get(stage_id)
        resolved[stage_id] = _resolve_stage_l3(entry.capabilities if entry else [], candidates)
        raw_picks[stage_id] = [pick.capability_id for pick in (entry.capabilities if entry else [])]

    owner_of = {c.id: stage_id for stage_id, caps in candidates_by_stage.items() for c in caps}
    for picker_stage, picks in raw_picks.items():
        for cap_id in picks:
            owner_stage = owner_of.get(cap_id)
            if owner_stage is None or owner_stage == picker_stage:
                continue
            current = resolved[owner_stage]
            if any(c.id == cap_id for c in current):
                continue
            cap = next(c for c in candidates_by_stage[owner_stage] if c.id == cap_id)
            current.append(cap.model_copy(update={"llm_selected": True, "selected": True}))
    return resolved


def derive_l2(selected_l3: Sequence[L3Capability]) -> list[L2Capability]:
    """Unique (levelTwoId, levelTwoName) over the selected L3; selected=True for all derived."""
    seen: dict[str, L2Capability] = {}
    for cap in selected_l3:
        if not cap.level_two_id or cap.level_two_id in seen:
            continue
        seen[cap.level_two_id] = L2Capability(
            id=cap.level_two_id, name=cap.level_two_name, stage_id=cap.stage_id, selected=True
        )
    return list(seen.values())


def _resolve_vs_stages(
    picks: Sequence[SelectedStage], stages: Sequence[ValueStage]
) -> list[SelectedStage]:
    by_id = {s.stage_id: s for s in stages}
    chosen = [(p.stage_id, p.reason) for p in picks if p.stage_id in by_id]
    chosen = chosen or [(s.stage_id, "") for s in stages]  # empty/all-invalid -> the whole list
    out: list[SelectedStage] = []
    seen: set[str] = set()
    for stage_id, reason in chosen:
        if stage_id in seen:
            continue
        seen.add(stage_id)
        out.append(SelectedStage(stage_id=stage_id, stage_name=by_id[stage_id].stage_name, reason=reason))
    return out


def _resolve_stage_l3(
    picks: Sequence, candidates: Sequence[L3Capability]
) -> list[L3Capability]:
    governed = {c.id: c for c in candidates}
    out: list[L3Capability] = []
    seen: set[str] = set()
    for pick in picks:
        cap = governed.get(pick.capability_id)
        if cap is None or cap.id in seen:
            continue
        seen.add(cap.id)
        out.append(cap.model_copy(update={"llm_selected": True, "selected": True}))
    return out
