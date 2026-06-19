"""Unit tests for ThemeGenerationHandler orchestration + error conditions.

Uses fakes for the catalogue reader and platform client, and duck-typed worklets for input, so no
DB/LLM is touched. The handler builds real THEME worklets via worklet_data_api on the happy path.
"""

import asyncio
from pathlib import Path

import pytest

from jwg_app.domain.exceptions.custom_exception import CustomException
from jwg_app.domain.models.theme_generation import (
    L3Capability,
    ValueStage,
    ValueStreamAttributes,
    ValueStreamCatalogue,
)
from jwg_app.domain.services.theme import worklet_mapper as mapper
from jwg_app.domain.services.theme_generation_handler import ThemeGenerationHandler

CONFIG_PATH = str(Path(__file__).resolve().parents[2] / "configs" / "user_config.yaml")


# ---- duck-typed worklets + fakes ------------------------------------------------------

class _Prop:
    def __init__(self, name, value):
        self.property_name = name
        self.property_value = value


class _Worklet:
    def __init__(self, source_id=None, id=None, properties=None):
        self.source_id = source_id
        self.id = id
        self.properties = properties or []


def _er():
    return _Worklet(source_id="t1", id="t1", properties=[_Prop("title", "Ticket Title"), _Prop("rawText", "RAW")])


def _vs(vs_id):
    return _Worklet(
        source_id=vs_id,
        id=f"w-{vs_id}",
        properties=[_Prop("title", f"VS {vs_id}"), _Prop("valueStreamDescription", "d")],
    )


class FakeCatalogue:
    def __init__(self, data):
        self._data = data

    async def fetch_theme_inputs(self, vs_ids):
        return {i: self._data.get(i, ValueStreamCatalogue()) for i in vs_ids}


class RaisingCatalogue:
    async def fetch_theme_inputs(self, vs_ids):
        raise RuntimeError("db down")


class FakePlatform:
    """Canned structured output per schema (empty selections -> stage fallback)."""

    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        name = output_function.__name__ if output_function else ""
        if name == "TextOut":
            return {"text": "generated"}, None, 200
        if name == "FramingsOut":
            return {"framings": []}, None, 200
        if name == "BatchedStageSelection":
            return {"value_streams": []}, None, 200
        if name == "BatchedCapabilitySelection":
            return {"stages": []}, None, 200
        return {}, None, 200


class FailingPlatform:
    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        return None, "gateway exploded", 500


def _catalogue_with_stages(*vs_ids):
    data = {}
    for vid in vs_ids:
        data[vid] = ValueStreamCatalogue(
            value_stream=ValueStreamAttributes(value_proposition="vp", trigger="tr"),
            stage_list=[ValueStage(stage_id=f"{vid}-st1", stage_name="S1")],
            l3_capabilities=[
                L3Capability(id=f"{vid}-c1", name="C1", stage_id=f"{vid}-st1", level_two_id="L2", level_two_name="L2N")
            ],
        )
    return FakeCatalogue(data)


# ---- error conditions -----------------------------------------------------------------

def test_missing_er_worklet_raises_404():
    handler = ThemeGenerationHandler(FakeCatalogue({}), FakePlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(None, [_vs("vs1")]))
    assert exc.value.status_code == 404


def test_empty_vs_worklets_raises_404():
    handler = ThemeGenerationHandler(FakeCatalogue({}), FakePlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(_er(), []))
    assert exc.value.status_code == 404


def test_catalogue_failure_raises_503():
    handler = ThemeGenerationHandler(RaisingCatalogue(), FakePlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(_er(), [_vs("vs1")]))
    assert exc.value.status_code == 503


def test_no_stages_resolved_raises_400():
    # catalogue returns an empty ValueStreamCatalogue (no stages) for vs1
    handler = ThemeGenerationHandler(FakeCatalogue({}), FakePlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(_er(), [_vs("vs1")]))
    assert exc.value.status_code == 400


def test_llm_failure_raises_503():
    handler = ThemeGenerationHandler(_catalogue_with_stages("vs1"), FailingPlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(_er(), [_vs("vs1")]))
    assert exc.value.status_code == 503


# ---- happy path (multiple value streams) ----------------------------------------------

def test_produces_one_theme_per_value_stream():
    handler = ThemeGenerationHandler(_catalogue_with_stages("vs1", "vs2"), FakePlatform(), CONFIG_PATH)
    themes = asyncio.run(handler.run(_er(), [_vs("vs1"), _vs("vs2")]))

    assert len(themes) == 2
    titles = [mapper.get_property(t, mapper.ThemeProps.TITLE, "") for t in themes]
    assert all("Ticket Title" in t for t in titles)
    # each theme carries its selected stages (stage selection fell back to all catalogue stages)
    for theme in themes:
        stages = mapper.get_property(theme, mapper.ThemeProps.SELECTED_STAGES, [])
        assert len(stages) == 1
