"""Tests for the strict response_format builder."""

from jwg_app.domain.models.theme_generation import BatchedCapabilitySelection
from jwg_app.infrastructure.external.strict_schema import strict_response_format


def test_strict_response_format_envelope():
    rf = strict_response_format(BatchedCapabilitySelection)
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["name"] == "BatchedCapabilitySelection"
    assert rf["json_schema"]["strict"] is True


def test_every_object_is_closed_and_all_props_required():
    schema = strict_response_format(BatchedCapabilitySelection)["json_schema"]["schema"]

    def check(node):
        if isinstance(node, dict):
            assert "default" not in node
            if node.get("type") == "object" and "properties" in node:
                assert node["additionalProperties"] is False
                assert set(node["required"]) == set(node["properties"].keys())
            for value in node.values():
                check(value)
        elif isinstance(node, list):
            for item in node:
                check(item)

    check(schema)
    # the capability pick is named "id" (what the model emits); strict forces exactly that field
    pick = schema["$defs"]["CapabilityPick"]
    assert set(pick["properties"].keys()) == {"id", "name"}
    assert set(pick["required"]) == {"id", "name"}
