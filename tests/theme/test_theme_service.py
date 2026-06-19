"""Unit tests for ThemeService catalogue assembly (fake repos; no live DB)."""

import asyncio

from jwg_app.domain.services.theme_service import ThemeService
from jwg_app.infrastructure.database.models import (
    L2CapabilityModel,
    L3CapabilityModel,
    ValueStreamCapabilityModel,
    ValueStreamModel,
    ValueStreamStageModel,
)


class FakeVSRepo:
    def __init__(self, models):
        self._by_id = {m.value_stream_id: m for m in models}

    async def get_by_ids(self, ids):
        found = [self._by_id[i] for i in ids if i in self._by_id]
        missing = [i for i in ids if i not in self._by_id]
        return found, missing


class FakeJunctionRepo:
    def __init__(self, rows):
        self._rows = rows

    async def get_by_value_stream_ids(self, ids):
        wanted = set(ids)
        return [r for r in self._rows if r.value_stream_id in wanted]


class FakeByIdsRepo:
    def __init__(self, models, id_attr):
        self._by_id = {getattr(m, id_attr): m for m in models}

    async def get_by_ids(self, ids):
        return [self._by_id[i] for i in ids if i in self._by_id]


def _service(vs=None, mappings=None, stages=None, l3=None, l2=None):
    return ThemeService(
        value_stream_repository=FakeVSRepo(vs or []),
        stage_repository=FakeByIdsRepo(stages or [], "value_stream_stage_id"),
        capability_repository=FakeJunctionRepo(mappings or []),
        l3_repository=FakeByIdsRepo(l3 or [], "l3_capability_id"),
        l2_repository=FakeByIdsRepo(l2 or [], "l2_capability_id"),
    )


def _mapping(vs_id, stage_id, cap_id, mid="m"):
    return ValueStreamCapabilityModel(
        id=mid, value_stream_id=vs_id, value_stream_stage_id=stage_id, capability_id=cap_id
    )


def _stage(stage_id, name="Stage"):
    return ValueStreamStageModel(
        value_stream_stage_id=stage_id,
        value_stream_stage_name=name,
        value_stream_stage_description="D",
        value_stream_stage_entrance_criteria="E",
        value_stream_stage_exit_criteria="X",
        value_stream_stage_active="yes",
    )


def _l3(cap_id, name="Cap", parent="L2a"):
    return L3CapabilityModel(
        l3_capability_id=cap_id,
        capability_name=name,
        capability_description="cd",
        parent_capability_id=parent,
        capability_active="yes",
    )


def _l2(l2_id, name="L2 Name"):
    return L2CapabilityModel(l2_capability_id=l2_id, capability_name=name, capability_active="yes")


def test_assembles_full_chain():
    vs = ValueStreamModel(
        value_stream_id="vs1",
        value_stream_value_proposition="VP",
        value_stream_trigger="TR",
        value_stream_active="yes",
    )
    service = _service(
        vs=[vs],
        mappings=[_mapping("vs1", "st1", "c1", "m1"), _mapping("vs1", "st1", "c2", "m2")],
        stages=[_stage("st1", "Stage One")],
        l3=[_l3("c1", "Cap1", "L2a"), _l3("c2", "Cap2", "L2b")],
        l2=[_l2("L2a", "L2 A"), _l2("L2b", "L2 B")],
    )
    cat = asyncio.run(service.fetch_theme_inputs(["vs1"]))["vs1"]

    assert cat.value_stream.value_proposition == "VP"
    assert cat.value_stream.trigger == "TR"
    assert [s.stage_id for s in cat.stage_list] == ["st1"]
    assert cat.stage_list[0].stage_description == "D"
    assert {c.id for c in cat.l3_capabilities} == {"c1", "c2"}
    assert {c.level_two_name for c in cat.l3_capabilities} == {"L2 A", "L2 B"}
    # each L3 is tied to the stage from the mapping
    assert all(c.stage_id == "st1" for c in cat.l3_capabilities)


def test_missing_value_stream_yields_empty_attributes():
    service = _service(vs=[])  # vs1 not present
    cat = asyncio.run(service.fetch_theme_inputs(["vs1"]))["vs1"]
    assert cat.value_stream.value_proposition == ""
    assert cat.value_stream.trigger == ""
    assert cat.stage_list == []
    assert cat.l3_capabilities == []


def test_capability_not_in_l3_is_skipped():
    vs = ValueStreamModel(value_stream_id="vs1", value_stream_active="yes")
    service = _service(
        vs=[vs],
        mappings=[_mapping("vs1", "st1", "c1"), _mapping("vs1", "st1", "ghost")],
        stages=[_stage("st1")],
        l3=[_l3("c1")],  # 'ghost' not present
        l2=[_l2("L2a")],
    )
    cat = asyncio.run(service.fetch_theme_inputs(["vs1"]))["vs1"]
    assert {c.id for c in cat.l3_capabilities} == {"c1"}


def test_l3_with_missing_l2_parent_has_empty_name():
    vs = ValueStreamModel(value_stream_id="vs1", value_stream_active="yes")
    service = _service(
        vs=[vs],
        mappings=[_mapping("vs1", "st1", "c1")],
        stages=[_stage("st1")],
        l3=[_l3("c1", parent="L2missing")],
        l2=[],  # parent not present
    )
    cat = asyncio.run(service.fetch_theme_inputs(["vs1"]))["vs1"]
    assert cat.l3_capabilities[0].level_two_name == ""


def test_stage_not_in_stage_table_is_skipped():
    vs = ValueStreamModel(value_stream_id="vs1", value_stream_active="yes")
    service = _service(
        vs=[vs],
        mappings=[_mapping("vs1", "st1", "c1"), _mapping("vs1", "ghost_stage", "c2")],
        stages=[_stage("st1")],  # ghost_stage not present
        l3=[_l3("c1"), _l3("c2")],
        l2=[_l2("L2a")],
    )
    cat = asyncio.run(service.fetch_theme_inputs(["vs1"]))["vs1"]
    assert [s.stage_id for s in cat.stage_list] == ["st1"]
