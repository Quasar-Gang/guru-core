"""HTTP client for the Role Model Service — the only place the API service calls it.

Services must not import each other, so the two sides are bound by the HTTP contract in
PRD section 5. Read and write endpoints are proxied verbatim through `forward`; only
`recommend` has a typed shape, because a use case builds its payload from the profile.
"""

from typing import Any, Protocol

import httpx

from services.api.domain.errors import DomainError, InvalidInput, NotFound, Unauthorized

__all__ = ["FakeRoleModelClient", "RoleModelClient", "RoleModelClientPort"]

_ERRORS: dict[int, type[DomainError]] = {
    401: Unauthorized,
    404: NotFound,
    422: InvalidInput,
}


class RoleModelClientPort(Protocol):
    """What the API service needs from the Role Model Service."""

    async def forward(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        api_key: str | None = None,
    ) -> tuple[int, Any]:
        """Proxy one request; returns the upstream status and decoded body."""
        ...

    async def recommend(self, payload: dict[str, Any]) -> list[dict[str, Any]]: ...


class RoleModelClient:
    """httpx-backed `RoleModelClientPort`."""

    def __init__(
        self,
        base_url: str,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._transport = transport
        self._timeout = timeout

    async def forward(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        api_key: str | None = None,
    ) -> tuple[int, Any]:
        headers = {"X-API-Key": api_key} if api_key is not None else {}
        async with httpx.AsyncClient(
            base_url=self._base_url, transport=self._transport, timeout=self._timeout
        ) as client:
            response = await client.request(method, path, params=params, json=json, headers=headers)
        if not response.content:
            return response.status_code, None
        return response.status_code, response.json()

    async def recommend(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        status, body = await self.forward("POST", "/role-models/recommend", json=payload)
        if status >= 400:
            raise _ERRORS.get(status, DomainError)(f"role model service returned {status}")
        return list(body or [])


class FakeRoleModelClient:
    """In-process `RoleModelClientPort` for tests and local runs without the other service."""

    def __init__(
        self,
        response: Any = None,
        recommendations: list[dict[str, Any]] | None = None,
    ) -> None:
        self._response = response if response is not None else []
        self._recommendations = list(recommendations or [])
        self.calls: list[tuple[str, str]] = []

    async def forward(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        api_key: str | None = None,
    ) -> tuple[int, Any]:
        self.calls.append((method, path))
        return 200, self._response

    async def recommend(self, payload: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append(("POST", "/role-models/recommend"))
        return list(self._recommendations)
