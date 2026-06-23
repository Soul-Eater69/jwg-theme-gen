"""
Reconciles the model's batched stage and capability picks against the catalogue.

The stage and capability calls cover every approved value stream at once, so the model can return a
stage or capability under the wrong value stream. Each id belongs to exactly one parent, so each
pick is kept under the value stream or stage it really belongs to and any misplaced pick is moved
back. This module also derives the L2 capability rollup from the resolved L3.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any

from jwg_app.domain.models.theme_generation import (
    BatchedCapabilitySelection,
    BatchedStageSelection,
    L2Capability,
    L3Capability,
    SelectedStage,
    ValueStage,
)


def resolve_stages(
    picks: BatchedStageSelection, stage_lists: Mapping[str, Sequence[ValueStage]]
) -> dict[str, list[SelectedStage]]:
    """
    Keep each value stream's selected stages, then move back any stage placed under the wrong one.

    Only stage ids that belong to the value stream are kept, with the catalogue name. If the model
    picked nothing valid for a value stream, every stage of that value stream is used so none is
    left empty.

    Args:
        picks: The model's stage picks per value stream.
        stage_lists: The candidate stages for each value stream, keyed by value-stream id.

    Returns:
        The selected stages for each value stream, keyed by value-stream id.
    """
    by_vs = {entry.value_stream_id: entry for entry in picks.value_streams}
    resolved: dict[str, list[SelectedStage]] = {}
    picks_by_vs: dict[str, list[str]] = {}
    for vs_id, stages in stage_lists.items():
        chosen = by_vs[vs_id].selected_stages if vs_id in by_vs else []
        resolved[vs_id] = _keep_known_stages(chosen, stages)
        picks_by_vs[vs_id] = [p.stage_id for p in chosen]

    _reassign_misplaced(
        resolved,
        picks_by_vs,
        stage_lists,
        id_of=lambda s: s.stage_id,
        make=lambda vs_id, stage_id: _to_selected(_stage_in(stage_lists[vs_id], stage_id)),
    )
    return resolved


def resolve_l3(
    picks: BatchedCapabilitySelection, candidates_by_stage: Mapping[str, Sequence[L3Capability]]
) -> dict[str, list[L3Capability]]:
    """
    Keep each stage's selected L3, then move back any capability placed under the wrong stage.

    Only capability ids that belong to the stage are kept (the catalogue record), deduped and marked
    selected.

    Args:
        picks: The model's capability picks per stage.
        candidates_by_stage: The candidate L3 capabilities for each stage, keyed by stage id.

    Returns:
        The selected L3 capabilities for each stage, keyed by stage id.
    """
    by_stage = {entry.stage_id: entry for entry in picks.stages}
    resolved: dict[str, list[L3Capability]] = {}
    picks_by_stage: dict[str, list[str]] = {}
    for stage_id, candidates in candidates_by_stage.items():
        raw = by_stage[stage_id].capabilities if stage_id in by_stage else []
        # each pick is an object; take its id, normalizing a stray ``[CAP…]`` / whitespace, drop empties
        chosen = [cid for cid in (_clean_id(p.capability_id) for p in raw) if cid]
        resolved[stage_id] = _keep_known_caps(chosen, candidates)
        picks_by_stage[stage_id] = chosen

    _reassign_misplaced(
        resolved,
        picks_by_stage,
        candidates_by_stage,
        id_of=lambda c: c.id,
        make=lambda stage_id, cap_id: _cap_in(candidates_by_stage[stage_id], cap_id),
    )
    return resolved


def derive_l2(selected_l3: Sequence[L3Capability]) -> list[L2Capability]:
    """
    Derive the unique parent L2 capabilities from the selected L3.

    Args:
        selected_l3: The selected L3 capabilities.

    Returns:
        One L2 capability per distinct parent, all marked selected.
    """
    seen: dict[str, L2Capability] = {}
    for cap in selected_l3:
        if not cap.level_two_id or cap.level_two_id in seen:
            continue
        seen[cap.level_two_id] = L2Capability(
            id=cap.level_two_id,
            name=cap.level_two_name,
            description=cap.level_two_description,
            stage_id=cap.stage_id,
        )
    return list(seen.values())


def _keep_known_stages(
    chosen: Sequence[SelectedStage], stages: Sequence[ValueStage]
) -> list[SelectedStage]:
    """Keep the picks that name a real stage of this value stream; if none do, use every stage."""
    by_id = {s.stage_id: s for s in stages}
    kept = [(p.stage_id, p.reason) for p in chosen if p.stage_id in by_id]
    kept = kept or [(s.stage_id, "") for s in stages]  # nothing valid -> all stages, no reason
    out: list[SelectedStage] = []
    seen: set[str] = set()
    for stage_id, reason in kept:
        if stage_id in seen:
            continue
        seen.add(stage_id)
        out.append(_to_selected(by_id[stage_id], reason))
    return out


def _clean_id(value: str) -> str:
    """Normalize a model-returned id: drop surrounding brackets/whitespace (it may echo ``[CAP…]``)."""
    return value.strip().strip("[]").strip()


def _keep_known_caps(chosen: Sequence[str], candidates: Sequence[L3Capability]) -> list[L3Capability]:
    """Keep the ids that name a real candidate of this stage, deduped and marked selected."""
    by_id = {c.id: c for c in candidates}
    out: list[L3Capability] = []
    seen: set[str] = set()
    for cap_id in chosen:
        cap = by_id.get(cap_id)
        if cap is None or cap.id in seen:
            continue
        seen.add(cap.id)
        out.append(cap)
    return out


def _reassign_misplaced(
    resolved: dict[str, list],
    picks_by_parent: Mapping[str, Sequence[str]],
    catalogue: Mapping[str, Sequence],
    *,
    id_of: Callable[[Any], str],
    make: Callable[[str, str], Any],
) -> None:
    """
    Move any pick the model placed under the wrong parent to the parent it really belongs to.

    Each id belongs to exactly one parent. ``resolved`` is edited in place.
    """
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


def _to_selected(stage: ValueStage, reason: str = "") -> SelectedStage:
    """Build a SelectedStage from a catalogue stage, carrying its name, full scope, and the reason."""
    return SelectedStage(
        stage_id=stage.stage_id,
        stage_name=stage.stage_name,
        stage_description=stage.stage_description,
        entrance_criteria=stage.entrance_criteria,
        exit_criteria=stage.exit_criteria,
        reason=reason,
    )


def _stage_in(stages: Sequence[ValueStage], stage_id: str) -> ValueStage:
    """Return the catalogue stage with ``stage_id``."""
    return next(s for s in stages if s.stage_id == stage_id)


def _cap_in(candidates: Sequence[L3Capability], cap_id: str) -> L3Capability:
    """Return the candidate capability with ``cap_id``."""
    return next(c for c in candidates if c.id == cap_id)
