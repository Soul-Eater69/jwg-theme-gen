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
    TextOut,
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
    def __init__(self, source_id=None, id=None, parent_worklet_id=None, properties=None):
        self.source_id = source_id
        self.id = id
        self.parent_worklet_id = parent_worklet_id
        self.properties = properties or []

    def get_property_value(self, name):
        for p in self.properties:
            if p.property_name == name:
                return p.property_value
        return None

    def upsert_property(self, *, name, value):
        for p in self.properties:
            if p.property_name == name:
                p.property_value = value
                return
        self.properties.append(_Prop(name, value))


def _er():
    return _Worklet(source_id="t1", id="t1", properties=[_Prop("title", "Ticket Title"), _Prop("rawText", "RAW")])


def _vs_worklet(vs_id):
    # A VALUE_STREAM worklet: its id becomes the theme's parentWorkletId; the valueStreamId PROPERTY
    # carries the VS id (the catalogue lookup key); businessValueStream is carried onto the theme.
    return _Worklet(
        id=f"vswlet-{vs_id}",
        source_id="t1",
        properties=[
            _Prop("valueStreamId", vs_id),
            _Prop("businessValueStream", f"Value Stream {{{vs_id}}}"),
        ],
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
    """Non-retryable failure (400) -> fails fast."""

    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        return None, "bad request", 400


class CountingPlatform:
    """Always returns a transient status; counts how many agenerate calls were made."""

    def __init__(self, status=503):
        self.calls = 0
        self.status = status

    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        self.calls += 1
        return None, "transient", self.status


class SchemaFailingPlatform:
    """Fails (503) only the call whose output schema name matches; all other calls succeed."""

    def __init__(self, failing_schema):
        self.failing_schema = failing_schema
        self._ok = FakePlatform()

    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        name = output_function.__name__ if output_function else ""
        if name == self.failing_schema:
            return None, "core call down", 503
        return await self._ok.agenerate(message, model_params, output_function, **kwargs)


class BusinessNeedsFailingPlatform:
    """Core calls succeed; business needs (the per-VS TextOut for ``failing_vs``) returns 503."""

    def __init__(self, failing_vs):
        self.failing_vs = failing_vs
        self._ok = FakePlatform()

    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        name = output_function.__name__ if output_function else ""
        user = message[-1]["content"] if message else ""
        # business needs is a TextOut whose rendered prompt carries the value-stream id (body does not).
        if name == "TextOut" and self.failing_vs in user:
            return None, "needs gateway down", 503
        return await self._ok.agenerate(message, model_params, output_function, **kwargs)


def _catalogue_with_stages(*vs_ids):
    data = {}
    for vid in vs_ids:
        data[vid] = ValueStreamCatalogue(
            value_stream=ValueStreamAttributes(name=f"VS {vid}", description="d", value_proposition="vp", trigger="tr"),
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
        asyncio.run(handler.run(None, [_vs_worklet("vs1")]))
    assert exc.value.status_code == 404


def test_empty_vs_worklets_raises_404():
    handler = ThemeGenerationHandler(FakeCatalogue({}), FakePlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(_er(), []))
    assert exc.value.status_code == 404


def test_catalogue_failure_raises_503():
    handler = ThemeGenerationHandler(RaisingCatalogue(), FakePlatform(), CONFIG_PATH)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler.run(_er(), [_vs_worklet("vs1")]))
    assert exc.value.status_code == 503


def _is_failed(theme):
    return mapper.get_property(theme, mapper.ThemeProps.GENERATION_ERROR, None) is not None


def test_vs_with_no_stages_returns_only_that_vs_failed():
    # vs2 has no catalogue stages -> only vs2 comes back as a failure worklet; vs1 still succeeds.
    handler = ThemeGenerationHandler(_catalogue_with_stages("vs1"), FakePlatform(), CONFIG_PATH)
    themes = asyncio.run(handler.run(_er(), [_vs_worklet("vs1"), _vs_worklet("vs2")]))
    assert len(themes) == 2
    by_parent = {t.parent_worklet_id: t for t in themes}
    assert not _is_failed(by_parent["vswlet-vs1"])  # vs1 produced a real theme
    assert _is_failed(by_parent["vswlet-vs2"])  # vs2 had no stages -> failure worklet
    # the success worklet still carries the normal generated fields
    assert mapper.get_property(by_parent["vswlet-vs1"], mapper.ThemeProps.SUMMARY, "")


def test_shared_call_failure_fails_every_value_stream():
    # FailingPlatform fails every call; the first shared call (description body) failing means no
    # theme can be built for ANY value stream -> all come back as failure worklets (no raise).
    handler = ThemeGenerationHandler(_catalogue_with_stages("vs1", "vs2"), FailingPlatform(), CONFIG_PATH)
    themes = asyncio.run(handler.run(_er(), [_vs_worklet("vs1"), _vs_worklet("vs2")]))
    assert len(themes) == 2
    assert all(_is_failed(t) for t in themes)
    # failure worklets keep the THEME envelope: parented to their VS worklet + businessValueStream
    assert [t.parent_worklet_id for t in themes] == ["vswlet-vs1", "vswlet-vs2"]
    assert all(mapper.get_property(t, mapper.ThemeProps.BUSINESS_VALUE_STREAM, "") for t in themes)


@pytest.mark.parametrize(
    "schema", ["TextOut", "FramingsOut", "BatchedStageSelection", "BatchedCapabilitySelection"]
)
def test_any_shared_call_failure_fails_every_value_stream(schema):
    # description body / framing / stage / capability selection are shared: a failure in any of them
    # fails every value stream's worklet. (TextOut is the body call, which runs first.)
    platform = SchemaFailingPlatform(failing_schema=schema)
    handler = _handler(platform)
    themes = asyncio.run(handler.run(_er(), [_vs_worklet("vs1")]))
    assert themes and all(_is_failed(t) for t in themes)


def _handler(platform, catalogue=None):
    return ThemeGenerationHandler(catalogue or _catalogue_with_stages("vs1"), platform, CONFIG_PATH)


class ValidationFailingPlatform:
    """Returns a 200 whose body does not match the output schema, and counts the calls made."""

    def __init__(self):
        self.calls = 0

    async def agenerate(self, message, model_params=None, output_function=None, **kwargs):
        self.calls += 1
        return ["not", "an", "object"], None, 200  # 200 but does not match TextOut


def test_validation_failure_raises_503_in_one_attempt():
    # No retry: a 200 whose body fails schema validation surfaces a 503 after a single call.
    platform = ValidationFailingPlatform()
    handler = _handler(platform)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler._call("description_body", TextOut, ticket_context="x"))
    assert exc.value.status_code == 503
    assert platform.calls == 1  # one attempt, no re-sample


def test_llm_failure_makes_a_single_call():
    # A transient gateway status is not retried either: one call, then 503.
    platform = CountingPlatform(status=503)
    handler = _handler(platform)
    with pytest.raises(CustomException) as exc:
        asyncio.run(handler._call("description_body", TextOut, ticket_context="x"))
    assert exc.value.status_code == 503
    assert platform.calls == 1


# ---- happy path (multiple value streams) ----------------------------------------------

def test_produces_one_theme_per_value_stream():
    handler = ThemeGenerationHandler(_catalogue_with_stages("vs1", "vs2"), FakePlatform(), CONFIG_PATH)
    themes = asyncio.run(handler.run(_er(), [_vs_worklet("vs1"), _vs_worklet("vs2")]))

    assert len(themes) == 2
    summaries = [mapper.get_property(t, mapper.ThemeProps.SUMMARY, "") for t in themes]
    assert all("Ticket Title" in s for s in summaries)
    # each theme is a new THEME worklet parented to its value-stream worklet
    assert [t.parent_worklet_id for t in themes] == ["vswlet-vs1", "vswlet-vs2"]
    assert all(str(t.worklet_type) in ("WorkletType.THEME", "THEME") for t in themes)
    # businessValueStream is carried over from each VS worklet onto its theme
    bvs = [mapper.get_property(t, mapper.ThemeProps.BUSINESS_VALUE_STREAM, "") for t in themes]
    assert bvs == ["Value Stream {vs1}", "Value Stream {vs2}"]
    for theme in themes:
        # selectedStages is an {id: "name {id}"} map, one entry per selected stage
        tags = mapper.get_property(theme, mapper.ThemeProps.SELECTED_STAGES, {})
        assert len(tags) == 1
        (sid, label), = tags.items()
        assert sid in label and "{" in label  # value is "name {id}"


# ---- partial success (business needs is the per-VS decider) ---------------------------

def test_one_vs_business_needs_failure_returns_partial_set():
    # vs1's business needs fails -> only vs1 is a failure worklet; vs2 is returned as a real theme.
    platform = BusinessNeedsFailingPlatform(failing_vs="vs1")
    handler = _handler(platform, catalogue=_catalogue_with_stages("vs1", "vs2"))
    themes = asyncio.run(handler.run(_er(), [_vs_worklet("vs1"), _vs_worklet("vs2")]))
    assert len(themes) == 2
    by_parent = {t.parent_worklet_id: t for t in themes}
    assert _is_failed(by_parent["vswlet-vs1"])  # business needs failed -> failure worklet
    assert not _is_failed(by_parent["vswlet-vs2"])  # vs2 produced a real theme
    # the failure worklet carries the error text + still identifies its value stream
    assert mapper.get_property(by_parent["vswlet-vs1"], mapper.ThemeProps.GENERATION_ERROR, "")
    assert mapper.get_property(by_parent["vswlet-vs1"], mapper.ThemeProps.BUSINESS_VALUE_STREAM, "")
    # the success worklet has the normal generated fields, not a generationError
    assert mapper.get_property(by_parent["vswlet-vs2"], mapper.ThemeProps.SUMMARY, "")
