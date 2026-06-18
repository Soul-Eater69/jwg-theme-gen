"""Turns the LLM's batched picks into the final theme values.

The stage and capability calls cover ALL approved value streams at once, so the model can list a
stage or capability under the wrong value stream. Each id belongs to exactly one parent, so we keep
each pick under the value stream / stage it really belongs to, and move any misplaced pick back.
Also holds the small deterministic steps: the L2 list from L3, the theme title, the description.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

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


# ---- LLM output -> final values -------------------------------------------------------

def resolve_framings(out: FramingsOut, vs_ids: Sequence[str]) -> dict[str, str]:
    """One framing paragraph per approved value stream, keyed by OUR ids (not the model's). A value
    stream the model skips gets "" (the description still has the shared body); an unknown id is
    ignored."""
    by_vs = {f.value_stream_id: f.text for f in out.framings}
    return {vs_id: by_vs.get(vs_id, "") for vs_id in vs_ids}


def resolve_stages(
    out: BatchedStageSelection, stage_lists: Mapping[str, Sequence[ValueStage]]
) -> dict[str, list[SelectedStage]]:
    """Per value stream: keep only its own stage ids (with the catalogue name). If the model picked
    nothing valid for a value stream, fall back to all its stages so none is left empty. Then move
    any stage the model listed under the wrong value stream back to the right one."""
    by_vs = {entry.value_stream_id: entry for entry in out.value_streams}
    resolved: dict[str, list[SelectedStage]] = {}
    picks_by_vs: dict[str, list[str]] = {}
    for vs_id, stages in stage_lists.items():
        picks = by_vs[vs_id].selected_stages if vs_id in by_vs else []
        resolved[vs_id] = _keep_known_stages(picks, stages)
        picks_by_vs[vs_id] = [p.stage_id for p in picks]

    _reassign_misplaced(
        resolved,
        picks_by_vs,
        stage_lists,
        id_of=lambda s: s.stage_id,
        make=lambda vs_id, stage_id: SelectedStage(
            stage_id=stage_id, stage_name=_name_in(stage_lists[vs_id], stage_id)
        ),
    )
    return resolved


def resolve_l3(
    out: BatchedCapabilitySelection, candidates_by_stage: Mapping[str, Sequence[L3Capability]]
) -> dict[str, list[L3Capability]]:
    """Per stage: keep only the capability ids allowed for THAT stage (the catalogue record),
    deduped, marked selected. Then move any capability the model listed under the wrong stage back
    to the right one. Returns ``{stage_id: [L3Capability]}``."""
    by_stage = {entry.stage_id: entry for entry in out.stages}
    resolved: dict[str, list[L3Capability]] = {}
    picks_by_stage: dict[str, list[str]] = {}
    for stage_id, candidates in candidates_by_stage.items():
        picks = by_stage[stage_id].capabilities if stage_id in by_stage else []
        resolved[stage_id] = _keep_known_caps(picks, candidates)
        picks_by_stage[stage_id] = [p.capability_id for p in picks]

    _reassign_misplaced(
        resolved,
        picks_by_stage,
        candidates_by_stage,
        id_of=lambda c: c.id,
        make=lambda stage_id, cap_id: _mark_selected(_cap_in(candidates_by_stage[stage_id], cap_id)),
    )
    return resolved


def derive_l2(selected_l3: Sequence[L3Capability]) -> list[L2Capability]:
    """The unique parent L2 over the selected L3; all marked selected."""
    seen: dict[str, L2Capability] = {}
    for cap in selected_l3:
        if not cap.level_two_id or cap.level_two_id in seen:
            continue
        seen[cap.level_two_id] = L2Capability(
            id=cap.level_two_id, name=cap.level_two_name, stage_id=cap.stage_id, selected=True
        )
    return list(seen.values())


# ---- theme title + description --------------------------------------------------------

def theme_title(er: ERContext, vs: VSContext) -> str:
    """The THEME title: «ticket title -- value stream name»."""
    return f"{er.idmt_ticket_title} -- {vs.vs_name}"


def assemble_description(framing: str, body: str) -> str:
    """A Theme description: the value stream's framing paragraph over the shared body."""
    parts = []
    if framing.strip():
        parts.append("Theme Description:\n" + framing.strip())
    if body.strip():
        parts.append(body.strip())
    return "\n\n".join(parts)


# ---- internals ------------------------------------------------------------------------

def _keep_known_stages(
    picks: Sequence[SelectedStage], stages: Sequence[ValueStage]
) -> list[SelectedStage]:
    """Keep the picks that name a real stage of this value stream; if none do, use every stage."""
    by_id = {s.stage_id: s for s in stages}
    chosen = [(p.stage_id, p.reason) for p in picks if p.stage_id in by_id]
    chosen = chosen or [(s.stage_id, "") for s in stages]
    out: list[SelectedStage] = []
    seen: set[str] = set()
    for stage_id, reason in chosen:
        if stage_id in seen:
            continue
        seen.add(stage_id)
        out.append(SelectedStage(stage_id=stage_id, stage_name=by_id[stage_id].stage_name, reason=reason))
    return out


def _keep_known_caps(picks: Sequence, candidates: Sequence[L3Capability]) -> list[L3Capability]:
    """Keep the picks that name a real candidate of this stage, deduped, marked selected."""
    by_id = {c.id: c for c in candidates}
    out: list[L3Capability] = []
    seen: set[str] = set()
    for pick in picks:
        cap = by_id.get(pick.capability_id)
        if cap is None or cap.id in seen:
            continue
        seen.add(cap.id)
        out.append(_mark_selected(cap))
    return out


def _reassign_misplaced(
    resolved: dict[str, list],
    picks_by_parent: Mapping[str, Sequence[str]],
    catalogue: Mapping[str, Sequence],
    *,
    id_of: Callable[[Any], str],
    make: Callable[[str, str], Any],
) -> None:
    """Each id belongs to exactly one parent. If the model listed an id under the wrong parent, move
    it to the parent it really belongs to. Edits ``resolved`` in place."""
    parent_of = {id_of(item): parent for parent, items in catalogue.items() for item in items}
    for listed_under, ids in picks_by_parent.items():
        for item_id in ids:
            real_parent = parent_of.get(item_id)
            if real_parent is None or real_parent == listed_under:
                continue
            target = resolved[real_parent]
            if any(id_of(rec) == item_id for rec in target):
                continue
            target.append(make(real_parent, item_id))


def _mark_selected(cap: L3Capability) -> L3Capability:
    return cap.model_copy(update={"llm_selected": True, "selected": True})


def _name_in(stages: Sequence[ValueStage], stage_id: str) -> str:
    return next(s.stage_name for s in stages if s.stage_id == stage_id)


def _cap_in(candidates: Sequence[L3Capability], cap_id: str) -> L3Capability:
    return next(c for c in candidates if c.id == cap_id)
