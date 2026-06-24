"""Tests for worklet_mapper property access — native helper path and the array fallback.

The mapper must work whether the Worklet exposes ``get_property_value`` / ``upsert_property`` or not
(some Worklet variants only carry a ``properties`` list of ``{propertyName, propertyValue}``).
"""

from jwg_app.domain.services.theme import worklet_mapper as mapper


class _NoMethodWorklet:
    """A Worklet variant with only a properties list — no get_property_value / upsert_property."""

    def __init__(self, properties):
        self.properties = properties


class _PropObject:
    def __init__(self, name, value):
        self.property_name = name
        self.property_value = value


class _NativeWorklet:
    """A Worklet that exposes the native helper methods (like the prod Worklet model)."""

    def __init__(self, properties=None):
        self.properties = properties or []

    def get_property_value(self, name, default=None):
        for prop in self.properties:
            if prop.property_name == name:
                return prop.property_value
        return default

    def upsert_property(self, *, name, value):
        for prop in self.properties:
            if prop.property_name == name:
                prop.property_value = value
                return
        self.properties.append(_PropObject(name, value))


def test_get_property_reads_dict_properties_without_helpers():
    worklet = _NoMethodWorklet([{"propertyName": "valueStreamId", "propertyValue": "VSR1"}])
    assert mapper.value_stream_id(worklet) == "VSR1"
    assert mapper.get_property(worklet, "missing", "fallback") == "fallback"


def test_get_property_reads_object_properties_without_helpers():
    worklet = _NoMethodWorklet([_PropObject("valueStreamId", "VSR2")])
    assert mapper.get_property(worklet, "valueStreamId", "") == "VSR2"


def test_set_property_appends_then_overwrites_without_helpers():
    worklet = _NoMethodWorklet([{"propertyName": "valueStreamId", "propertyValue": "VSR1"}])

    mapper.set_property(worklet, "title", "first")
    assert mapper.get_property(worklet, "title") == "first"

    mapper.set_property(worklet, "title", "second")  # update in place, no duplicate
    titles = [p for p in worklet.properties if mapper._prop_name(p) == "title"]
    assert len(titles) == 1
    assert mapper.get_property(worklet, "title") == "second"
    # the original property is untouched
    assert mapper.get_property(worklet, "valueStreamId") == "VSR1"


def test_native_methods_are_used_when_present():
    worklet = _NativeWorklet([_PropObject("valueStreamId", "VSR-native")])
    assert mapper.value_stream_id(worklet) == "VSR-native"

    mapper.set_property(worklet, "title", "via-native")
    assert worklet.get_property_value("title") == "via-native"


class _InputWorklet:
    """A value-stream worklet (id + source_id + properties) used as input to the theme builders."""

    def __init__(self, id, source_id, properties):
        self.id = id
        self.source_id = source_id
        self.properties = properties


def test_to_failed_theme_worklet_carries_bvs_and_error_only():
    vs = _InputWorklet(
        id="vswlet-1",
        source_id="t1",
        properties=[{"propertyName": "businessValueStream", "propertyValue": "Acquire Asset {VSR1}"}],
    )
    failed = mapper.to_failed_theme_worklet(vs, "boom")

    # same THEME envelope as a generated theme: parented to the VS worklet, source id carried
    assert str(failed.worklet_type) in ("WorkletType.THEME", "THEME")
    assert failed.parent_worklet_id == "vswlet-1"
    assert failed.source_id == "t1"
    # carries businessValueStream + the error detail, and nothing generated
    assert mapper.get_property(failed, mapper.ThemeProps.GENERATION_ERROR) == "boom"
    assert mapper.get_property(failed, mapper.ThemeProps.BUSINESS_VALUE_STREAM) == "Acquire Asset {VSR1}"
    assert mapper.get_property(failed, mapper.ThemeProps.SUMMARY) is None
    assert mapper.get_property(failed, mapper.ThemeProps.SELECTED_STAGES) is None
