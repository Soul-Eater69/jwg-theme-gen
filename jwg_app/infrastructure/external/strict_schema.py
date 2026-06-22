"""Build a strict ``response_format`` payload from a pydantic model for constrained structured output.

The chat-completions gateway supports strict JSON-schema structured outputs (constrained decoding):
the model is forced, token by token, to emit JSON that matches the schema - so it cannot rename a
field (``id`` vs ``capabilityId``), omit a required field, or return an object where the schema wants
a string. That removes the whole class of structured-output parse failures.

OpenAI/Azure strict mode requires the schema to: mark every object property ``required``, set
``additionalProperties: false`` on every object, and drop unsupported keywords (e.g. ``default``).
``strict_response_format`` post-processes ``model.model_json_schema()`` to satisfy that, and wraps it
in the ``response_format`` envelope the gateway expects.

Usage in the platform client's ``agenerate`` (when an ``output_function`` is given):

    body["response_format"] = strict_response_format(output_function)
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


def strict_response_format(model: type[BaseModel]) -> dict[str, Any]:
    """The ``response_format`` request field that constrains the model to ``model``'s schema.

    Args:
        model: The pydantic model the response must match.

    Returns:
        ``{"type": "json_schema", "json_schema": {"name", "schema", "strict": True}}``.
    """
    schema = _as_strict(model.model_json_schema())
    return {
        "type": "json_schema",
        "json_schema": {"name": model.__name__, "schema": schema, "strict": True},
    }


def _as_strict(node: Any) -> Any:
    """Recursively make a JSON schema strict: every object requires all its properties and forbids
    extras; unsupported keywords are dropped. Edits and returns ``node``."""
    if isinstance(node, dict):
        node.pop("default", None)  # strict mode rejects defaults
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        for value in node.values():
            _as_strict(value)
    elif isinstance(node, list):
        for item in node:
            _as_strict(item)
    return node
