"""Unit tests for the theme output resolver (pure; no DB/LLM)."""

from jwg_app.domain.models.theme_generation import (
    BatchedCapabilitySelection,
    BatchedStageSelection,
    CapabilityPick,
    L3Capability,
    SelectedStage,
    StageCapabilityPicks,
    ValueStage,
    VsStageSelection,
)
from jwg_app.domain.services.theme import output_resolver as resolver


def _stage(stage_id: str, name: str = "S") -> ValueStage:
    return ValueStage(
        stage_id=stage_id,
        stage_name=name,
        stage_description=f"{name} desc",
        entrance_criteria=f"{name} in",
        exit_criteria=f"{name} out",
    )


def _l3(cap_id: str, stage: str = "s1", l2_id: str = "L2", l2_name: str = "N") -> L3Capability:
    return L3Capability(id=cap_id, name=cap_id, stage_id=stage, level_two_id=l2_id, level_two_name=l2_name)


# ---- resolve_stages -------------------------------------------------------------------

def test_resolve_stages_keeps_valid_picks_with_canonical_name():
    stage_lists = {"vs1": [_stage("st1", "Alpha"), _stage("st2", "Beta")]}
    picks = BatchedStageSelection(
        value_streams=[
            VsStageSelection(
                value_stream_id="vs1",
                selected_stages=[SelectedStage(stage_id="st1", stage_name="echoed", reason="r")],
            )
        ]
    )
    out = resolver.resolve_stages(picks, stage_lists)
    assert [s.stage_id for s in out["vs1"]] == ["st1"]
    assert out["vs1"][0].stage_name == "Alpha"  # canonical catalogue name, not the model's echo
    assert out["vs1"][0].reason == "r"
    # scope is carried from the catalogue so downstream prompts see the full stage
    assert out["vs1"][0].stage_description == "Alpha desc"
    assert out["vs1"][0].entrance_criteria == "Alpha in"
    assert out["vs1"][0].exit_criteria == "Alpha out"


def test_resolve_stages_empty_falls_back_to_all():
    stage_lists = {"vs1": [_stage("st1"), _stage("st2")]}
    out = resolver.resolve_stages(BatchedStageSelection(value_streams=[]), stage_lists)
    assert {s.stage_id for s in out["vs1"]} == {"st1", "st2"}


def test_resolve_stages_all_invalid_falls_back():
    stage_lists = {"vs1": [_stage("st1")]}
    picks = BatchedStageSelection(
        value_streams=[VsStageSelection(value_stream_id="vs1", selected_stages=[SelectedStage(stage_id="NOPE")])]
    )
    out = resolver.resolve_stages(picks, stage_lists)
    assert [s.stage_id for s in out["vs1"]] == ["st1"]


def test_resolve_stages_reassigns_misplaced_to_owner():
    stage_lists = {"vs1": [_stage("st1")], "vs2": [_stage("st2"), _stage("st3")]}
    picks = BatchedStageSelection(
        value_streams=[
            VsStageSelection(
                value_stream_id="vs1",
                selected_stages=[SelectedStage(stage_id="st1"), SelectedStage(stage_id="st2")],  # st2 misplaced
            ),
            VsStageSelection(value_stream_id="vs2", selected_stages=[SelectedStage(stage_id="st3")]),
        ]
    )
    out = resolver.resolve_stages(picks, stage_lists)
    assert [s.stage_id for s in out["vs1"]] == ["st1"]  # st2 dropped from the wrong VS
    assert {s.stage_id for s in out["vs2"]} == {"st2", "st3"}  # st2 moved to its owner


def test_resolve_stages_dedups_repeated_picks():
    stage_lists = {"vs1": [_stage("st1")]}
    picks = BatchedStageSelection(
        value_streams=[
            VsStageSelection(
                value_stream_id="vs1",
                selected_stages=[SelectedStage(stage_id="st1"), SelectedStage(stage_id="st1")],
            )
        ]
    )
    out = resolver.resolve_stages(picks, stage_lists)
    assert [s.stage_id for s in out["vs1"]] == ["st1"]


# ---- resolve_l3 -----------------------------------------------------------------------

def test_resolve_l3_keeps_known_and_marks_selected():
    candidates = {"s1": [_l3("c1"), _l3("c2")]}
    picks = BatchedCapabilitySelection(
        stages=[StageCapabilityPicks(stage_id="s1", capabilities=[CapabilityPick(capability_id="c1")])]
    )
    out = resolver.resolve_l3(picks, candidates)
    assert [c.id for c in out["s1"]] == ["c1"]
    assert out["s1"][0].selected and out["s1"][0].llm_selected


def test_resolve_l3_tolerates_bracketed_padded_and_alt_id_field():
    # the model may echo the id as shown ("[c1]"), with whitespace, or under "id"/"capabilityId".
    candidates = {"s1": [_l3("c1"), _l3("c2"), _l3("c3")]}
    picks = BatchedCapabilitySelection(
        stages=[
            StageCapabilityPicks(
                stage_id="s1",
                capabilities=[
                    CapabilityPick.model_validate({"id": "[c1]"}),         # bracketed, "id" field
                    CapabilityPick.model_validate({"capabilityId": " c2 "}),  # alt field + padding
                    CapabilityPick.model_validate({"name": "no id"}),        # malformed -> dropped
                    CapabilityPick(capability_id="c3"),
                ],
            )
        ]
    )
    out = resolver.resolve_l3(picks, candidates)
    assert [c.id for c in out["s1"]] == ["c1", "c2", "c3"]


def test_resolve_l3_empty_picks_gives_no_capabilities():
    candidates = {"s1": [_l3("c1")]}
    out = resolver.resolve_l3(BatchedCapabilitySelection(stages=[]), candidates)
    assert out["s1"] == []  # capabilities are optional - no fallback to all


def test_resolve_l3_reassigns_misplaced_to_owner_stage():
    candidates = {"s1": [_l3("c1", "s1")], "s2": [_l3("c2", "s2")]}
    picks = BatchedCapabilitySelection(
        stages=[
            StageCapabilityPicks(
                stage_id="s1",
                capabilities=[CapabilityPick(capability_id="c1"), CapabilityPick(capability_id="c2")],  # c2 misplaced
            )
        ]
    )
    out = resolver.resolve_l3(picks, candidates)
    assert [c.id for c in out["s1"]] == ["c1"]
    assert [c.id for c in out["s2"]] == ["c2"]  # moved to its owner stage


def test_resolve_l3_dedups_repeated_picks():
    candidates = {"s1": [_l3("c1")]}
    picks = BatchedCapabilitySelection(
        stages=[
            StageCapabilityPicks(
                stage_id="s1",
                capabilities=[CapabilityPick(capability_id="c1"), CapabilityPick(capability_id="c1")],
            )
        ]
    )
    out = resolver.resolve_l3(picks, candidates)
    assert [c.id for c in out["s1"]] == ["c1"]


# ---- derive_l2 ------------------------------------------------------------------------

def test_derive_l2_unique_parents_all_selected():
    selected = [
        _l3("c1", l2_id="L2a", l2_name="A"),
        _l3("c2", l2_id="L2a", l2_name="A"),  # same parent -> deduped
        _l3("c3", l2_id="L2b", l2_name="B"),
    ]
    out = resolver.derive_l2(selected)
    assert {l2.id for l2 in out} == {"L2a", "L2b"}
    assert all(l2.selected for l2 in out)


def test_derive_l2_skips_l3_without_parent():
    out = resolver.derive_l2([_l3("c1", l2_id="", l2_name="")])
    assert out == []
