"""Unit tests for the theme prompt builder (pure; no DB/LLM)."""

from jwg_app.domain.models.theme_generation import (
    ERContext,
    L3Capability,
    SelectedStage,
    ValueStage,
    VSContext,
)
from jwg_app.domain.services.theme import prompt_builder as pb


def _vs(vs_id="vs1", name="VS One", desc="vsdesc", vp="vprop", trigger="trig") -> VSContext:
    return VSContext(vs_id=vs_id, vs_name=name, vs_description=desc, value_proposition=vp, trigger=trigger)


def test_ticket_context_is_raw_text_only():
    er = ERContext(idmt_ticket_title="T", raw_text="RAW TICKET TEXT")
    assert pb.ticket_context(er) == "- content: RAW TICKET TEXT"


def test_stage_value_streams_renders_header_attrs_and_stages():
    stages = [
        ValueStage(
            stage_id="st1",
            stage_name="Stage One",
            stage_description="sd",
            entrance_criteria="en",
            exit_criteria="ex",
        )
    ]
    out = pb.stage_value_streams([(_vs(), stages)])
    assert "## Value Stream vs1" in out
    assert "Name: VS One" in out
    assert "Trigger: trig" in out
    assert "[st1] Stage One" in out
    assert "Entrance: en | Exit: ex" in out


def test_capability_value_streams_renders_stage_and_l3():
    stage = SelectedStage(stage_id="st1", stage_name="Stage One")
    l3 = [L3Capability(id="c1", name="Cap One", description="cd", stage_id="st1", level_two_id="L2", level_two_name="L2 Name")]
    out = pb.capability_value_streams([(_vs(), [(stage, l3)])])
    assert "## Value Stream vs1" in out
    assert "### Stage st1: Stage One" in out
    assert "[c1] Cap One" in out
    assert "(L2: L2 Name)" in out


def test_framing_value_streams_lists_each_vs():
    out = pb.framing_value_streams([_vs("vs1", "One"), _vs("vs2", "Two")])
    assert "valueStreamId: vs1" in out
    assert "valueStreamId: vs2" in out
    assert "valueStreamName: One" in out


def test_framing_value_streams_omits_unset_optional_fields():
    vs = VSContext(vs_id="vs1", vs_name="One", vs_description="", value_proposition="")
    out = pb.framing_value_streams([vs])
    assert "valueStreamDescription" not in out
    assert "valueProposition" not in out


def test_selected_stages_block():
    out = pb.selected_stages([SelectedStage(stage_id="st1", stage_name="S1")])
    assert out == "[st1] S1"
