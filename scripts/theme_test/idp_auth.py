"""IDP bearer auth for the LLM gateway — FOR TESTING ONLY.

Fetches a JWT from the IDP token endpoint, caches it, injects it as ``Authorization: Bearer`` plus
the ``app-id`` header, and refreshes once on a 401. Ported from the teg integration so the test
platform client can reach the same OpenAI-compatible IDP gateway. Not part of the production package.
"""

from __future__ import annotations

import asyncio

import httpx

_TOKEN_MAX_RETRIES = 3
_TOKEN_BACKOFF_SECONDS = 0.5
_TOKEN_RETRY_STATUS = {401, 408, 429}  # plus any 5xx; transient on the dev STS


class IDPCustomAuth(httpx.Auth):
    """httpx auth flow that mints and refreshes an IDP JWT for the gateway."""

    def __init__(
        self,
        *,
        app_id: str,
        auth_url: str,
        client_id: str,
        client_secret: str,
        user: str,
        password: str,
        verify_ssl: bool = False,
    ) -> None:
        self._app_id = app_id
        self._auth_url = auth_url
        self._client_id = client_id
        self._client_secret = client_secret
        self._user = user
        self._password = password
        self._verify_ssl = verify_ssl
        self._token: str | None = None
        self._lock = asyncio.Lock()

    async def async_auth_flow(self, request: httpx.Request):
        token = await self._ensure_token(stale=None)
        self._apply(request, token)

        response = yield request
        if response.status_code == 401:
            token = await self._ensure_token(stale=token)
            self._apply(request, token)
            yield request

    async def _ensure_token(self, *, stale: str | None) -> str:
        async with self._lock:
            if self._token is None or self._token == stale:
                self._token = await self._fetch_token()
            return self._token

    def _apply(self, request: httpx.Request, token: str) -> None:
        request.headers["Authorization"] = f"Bearer {token}"
        request.headers["app-id"] = str(self._app_id)

    async def _fetch_token(self) -> str:
        headers = {
            "Accept": "*/*",
            "ClientId": self._client_id,
            "ClientSecret": self._client_secret,
            "scope": "profile openid roles permissions",
        }
        body = {"username": self._user, "password": self._password}
        last_error: Exception | None = None
        async with httpx.AsyncClient(verify=self._verify_ssl) as client:
            for attempt in range(_TOKEN_MAX_RETRIES + 1):
                if attempt:
                    await asyncio.sleep(_TOKEN_BACKOFF_SECONDS * (2 ** (attempt - 1)))
                try:
                    response = await client.post(self._auth_url, headers=headers, json=body)
                except httpx.TransportError as exc:
                    last_error = exc
                    continue
                if response.status_code in _TOKEN_RETRY_STATUS or response.status_code >= 500:
                    last_error = httpx.HTTPStatusError(
                        f"token endpoint {response.status_code}",
                        request=response.request,
                        response=response,
                    )
                    continue
                response.raise_for_status()
                token = response.json().get("jwt_token")
                if not token:
                    raise RuntimeError("IDP token response missing jwt_token")
                return str(token)
        raise last_error or RuntimeError("IDP token fetch failed")
