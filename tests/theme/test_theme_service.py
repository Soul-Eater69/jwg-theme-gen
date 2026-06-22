"""Unit tests for ThemeService catalogue assembly (fake session rows; no live DB).

ThemeService runs one projected join and assembles the rows. These tests feed the assembly the
joined rows directly (one row per value-stream x stage x capability), which is what the query
returns - so they exercise the grouping/dedup without a database.
"""

import asyncio
from types import SimpleNamespace

from jwg_app.domain.services.theme_service import ThemeService

# the labels the catalogue query selects; assembly reads rows by these names.
_FIELDS = (
    "vs_id", "vs_name", "vs_description", "vs_value_proposition", "vs_trigger",
    "stage_id", "stage_name", "stage_description", "stage_entrance", "stage_exit",
    "l3_id", "l3_name", "l3_description", "level_two_id", "level_two_name",
)


def _row(**kw):
    return SimpleNamespace(**{f: kw.get(f) for f in _FIELDS})


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _stmt):
        return _FakeResult(self._rows)


def _fetch(rows, ids):
    return asyncio.run(ThemeService(session=_FakeSession(rows)).fetch_theme_inputs(ids))


def test_assembles_full_chain():
    rows = [
        _row(vs_id="vs1", vs_name="Procurement", vs_description="VS desc",
             vs_value_proposition="VP", vs_trigger="TR",
             stage_id="st1", stage_name="Stage One",
             stage_description="D", stage_entrance="E", stage_exit="X",
             l3_id="c1", l3_name="Cap1", l3_description="cd", level_two_id="L2a", level_two_name="L2 A"),
        _row(vs_id="vs1", vs_name="Procurement", vs_description="VS desc",
             vs_value_proposition="VP", vs_trigger="TR",
             stage_id="st1", stage_name="Stage One",
             stage_description="D", stage_entrance="E", stage_exit="X",
             l3_id="c2", l3_name="Cap2", l3_description="cd", level_two_id="L2b", level_two_name="L2 B"),
    ]
    cat = _fetch(rows, ["vs1"])["vs1"]

    assert cat.value_stream.name == "Procurement"
    assert cat.value_stream.description == "VS desc"
    assert cat.value_stream.value_proposition == "VP"
    assert cat.value_stream.trigger == "TR"
    assert [s.stage_id for s in cat.stage_list] == ["st1"]  # deduped
    assert cat.stage_list[0].stage_description == "D"
    assert {c.id for c in cat.l3_capabilities} == {"c1", "c2"}
    assert {c.level_two_name for c in cat.l3_capabilities} == {"L2 A", "L2 B"}
    assert all(c.stage_id == "st1" for c in cat.l3_capabilities)


def test_missing_value_stream_yields_empty_attributes():
    cat = _fetch([], ["vs1"])["vs1"]  # no rows for vs1
    assert cat.value_stream.value_proposition == ""
    assert cat.value_stream.trigger == ""
    assert cat.stage_list == []
    assert cat.l3_capabilities == []


def test_value_stream_with_no_mappings_has_attributes_but_empty_lists():
    # outer join returns the VS row with null stage/l3 columns.
    rows = [_row(vs_id="vs1", vs_name="Lonely")]
    cat = _fetch(rows, ["vs1"])["vs1"]
    assert cat.value_stream.name == "Lonely"
    assert cat.stage_list == []
    assert cat.l3_capabilities == []


def test_inactive_capability_is_skipped():
    # the L3 join did not match (inactive/missing) -> l3 columns null.
    rows = [
        _row(vs_id="vs1", stage_id="st1", stage_name="S",
             l3_id="c1", l3_name="Cap1", level_two_id="L2a", level_two_name="L2 A"),
        _row(vs_id="vs1", stage_id="st1", stage_name="S",
             l3_id=None),  # capability inactive -> no L3
    ]
    cat = _fetch(rows, ["vs1"])["vs1"]
    assert {c.id for c in cat.l3_capabilities} == {"c1"}


def test_l3_with_missing_l2_parent_has_empty_name():
    rows = [_row(vs_id="vs1", stage_id="st1", stage_name="S",
                 l3_id="c1", level_two_id="L2missing", level_two_name=None)]
    cat = _fetch(rows, ["vs1"])["vs1"]
    assert cat.l3_capabilities[0].level_two_name == ""


def test_inactive_stage_drops_its_stage_and_capability():
    # the stage join did not match (inactive) -> stage_id null; its L3 is dropped too, since an L3
    # under an inactive stage can never be a candidate (selected stages are active ones).
    rows = [
        _row(vs_id="vs1", stage_id="st1", stage_name="S", l3_id="c1"),
        _row(vs_id="vs1", stage_id=None, l3_id="c2"),  # stage inactive -> stage + c2 dropped
    ]
    cat = _fetch(rows, ["vs1"])["vs1"]
    assert [s.stage_id for s in cat.stage_list] == ["st1"]
    assert {c.id for c in cat.l3_capabilities} == {"c1"}


def test_dedups_repeated_l3_under_same_stage():
    rows = [
        _row(vs_id="vs1", stage_id="st1", stage_name="S", l3_id="c1"),
        _row(vs_id="vs1", stage_id="st1", stage_name="S", l3_id="c1"),
    ]
    cat = _fetch(rows, ["vs1"])["vs1"]
    assert [c.id for c in cat.l3_capabilities] == ["c1"]
