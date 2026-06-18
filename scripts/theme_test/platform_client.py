"""Test platform client backed by the OpenAI-compatible IDP LLM gateway — FOR TESTING ONLY.

Implements the one method the theme generation handler calls, ``agenerate(message, model_params,
output_function)``, against the same gateway the teg integration uses: json_schema structured output
built from the caller's pydantic model, custom IDP bearer auth, and the gateway's single-"choice"
response quirk. Config comes from environment variables (see build_platform_client). Not part of the
production package; the real platform client lives in prod.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx
from pydantic import BaseModel

from idp_auth import IDPCustomAuth


class IdpPlatformClient:
    """Minimal platform client exposing ``agenerate`` for theme generation tests."""

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        *,
        model: str,
        completion_path: str = "/api/v1/chatcompletions",
        api_version: str = "2024-04-01-preview",
        reasoning_effort: Optional[str] = None,
        max_output_tokens: Optional[int] = None,
        max_retries: int = 5,
        base_delay: float = 1.0,
        max_delay: float = 30.0,
    ) -> None:
        self._http = http_client
        self._model = model
        self._completion_path = completion_path
        self._api_version = api_version
        self._reasoning_effort = reasoning_effort or None
        self._max_output_tokens = max_output_tokens
        self._max_retries = max_retries
        self._base_delay = base_delay
        self._max_delay = max_delay

    async def aclose(self) -> None:
        await self._http.aclose()

    async def agenerate(
        self,
        message: List[Dict[str, str]],
        model_params: Optional[Dict[str, Any]] = None,
        output_function: Optional[type[BaseModel]] = None,
        **kwargs: Any,
    ) -> Tuple[Optional[Any], Optional[str], int]:
        """Run one structured chat-completion. Returns (data, error, status_code).

        On success: (parsed JSON dict, None, 200). On failure: (None, error message, status_code).
        """
        params = model_params or {}
        try:
            body: Dict[str, Any] = {
                "model": params.get("model") or self._model,
                "messages": list(message),
                "api_version": self._api_version,
            }
            if output_function is not None:
                body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {
                        "name": output_function.__name__,
                        "schema": _strict_schema(output_function),
                        "strict": True,
                    },
                }
            reasoning = params.get("reasoning_effort") or self._reasoning_effort
            if reasoning:
                body["reasoning_effort"] = reasoning
            max_tokens = (
                params.get("max_completion_tokens")
                or params.get("max_output_tokens")
                or self._max_output_tokens
            )
            if max_tokens:
                body["max_completion_tokens"] = max_tokens
            if params.get("temperature") is not None:
                body["temperature"] = params["temperature"]

            response = await self._post_with_retry(body)
            if response.status_code != 200:
                return None, f"gateway {response.status_code}: {response.text[:500]}", response.status_code
            content = _extract_content(response.json())
            return json.loads(content), None, 200
        except Exception as exc:  # noqa: BLE001 - surface as (None, error, status) for the handler
            return None, str(exc), 500

    async def _post_with_retry(self, body: Dict[str, Any]) -> httpx.Response:
        """POST with exponential backoff on 429/5xx/transient-network errors."""
        delay = self._base_delay
        last_error: Optional[Exception] = None
        for attempt in range(self._max_retries + 1):
            if attempt:
                await asyncio.sleep(min(delay, self._max_delay))
                delay *= 2
            try:
                response = await self._http.post(self._completion_path, json=body)
            except httpx.TransportError as exc:
                last_error = exc
                continue
            if response.status_code == 429 or response.status_code >= 500:
                last_error = httpx.HTTPStatusError(
                    f"gateway {response.status_code}", request=response.request, response=response
                )
                continue
            return response
        raise last_error or RuntimeError("gateway request failed")

    # --- PlatformClient protocol stubs (unused by theme generation) -----------------------
    async def generate(self, json: Dict[str, Any]) -> str:
        raise NotImplementedError("test client implements agenerate only")

    async def get_entity_by_id(self, id: str) -> Dict[str, Any]:
        raise NotImplementedError("test client implements agenerate only")

    async def get_entities(self, query_params: Dict[str, str]) -> List[Dict[str, Any]]:
        raise NotImplementedError("test client implements agenerate only")

    async def get_similar_entities(self, payload: Dict[str, Any]) -> Any:
        raise NotImplementedError("test client implements agenerate only")


def _strict_schema(schema: type[BaseModel]) -> dict:
    """Pydantic JSON schema transformed for OpenAI structured-output strict mode."""
    return _strictify(schema.model_json_schema(by_alias=True))


def _strictify(node: Any) -> Any:
    if isinstance(node, dict):
        node.pop("default", None)
        if isinstance(node.get("properties"), dict):
            node["required"] = list(node["properties"].keys())
            node["additionalProperties"] = False
        for value in node.values():
            _strictify(value)
    elif isinstance(node, list):
        for item in node:
            _strictify(item)
    return node


def _extract_content(payload: dict) -> str:
    if payload.get("error"):
        raise RuntimeError(str(payload["error"]))
    choice = payload.get("choice")  # IDP gateway quirk: single "choice"
    if choice is None:
        choices = payload.get("choices") or []
        choice = choices[0] if choices else {}
    content = (choice.get("message") or {}).get("content")
    if not content:
        raise RuntimeError("LLM returned no content")
    return content


def build_platform_client() -> IdpPlatformClient:
    """Build the client from environment variables.

    Required: LLM_BASE_URL, LLM_MODEL, LLM_APP_ID, IDP_AUTH_URL, IDP_CLIENT_ID, IDP_CLIENT_SECRET,
    IDP_USER, IDP_PASSWORD. Optional: LLM_COMPLETION_PATH, LLM_API_VERSION, LLM_REASONING_EFFORT,
    LLM_MAX_OUTPUT_TOKENS, LLM_TIMEOUT_SECONDS, LLM_VERIFY_SSL. (Map these from your teg .env values.)
    """
    verify_ssl = os.environ.get("LLM_VERIFY_SSL", "false").lower() == "true"
    auth = IDPCustomAuth(
        app_id=os.environ.get("LLM_APP_ID", ""),
        auth_url=os.environ.get("IDP_AUTH_URL", ""),
        client_id=os.environ.get("IDP_CLIENT_ID", ""),
        client_secret=os.environ.get("IDP_CLIENT_SECRET", ""),
        user=os.environ.get("IDP_USER", ""),
        password=os.environ.get("IDP_PASSWORD", ""),
        verify_ssl=verify_ssl,
    )
    http_client = httpx.AsyncClient(
        base_url=os.environ.get("LLM_BASE_URL", ""),
        auth=auth,
        timeout=float(os.environ.get("LLM_TIMEOUT_SECONDS", "60")),
        verify=verify_ssl,
    )
    max_tokens = os.environ.get("LLM_MAX_OUTPUT_TOKENS") or ""
    return IdpPlatformClient(
        http_client,
        model=os.environ.get("LLM_MODEL", ""),
        completion_path=os.environ.get("LLM_COMPLETION_PATH", "/api/v1/chatcompletions"),
        api_version=os.environ.get("LLM_API_VERSION", "2024-04-01-preview"),
        reasoning_effort=os.environ.get("LLM_REASONING_EFFORT") or None,
        max_output_tokens=int(max_tokens) if max_tokens.isdigit() else None,
    )
