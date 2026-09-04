"""HTTP middleware for the API service.

Rate limiting lives here rather than in a use case: it is a property of the
transport, and it needs the request's identity before any use case runs.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.types import ASGIApp

from packages.cache import CachePort
from services.api.application.ports import ClockPort, TokenIssuerPort
from services.api.domain.errors import Unauthorized

#: Paths that must stay reachable regardless of quota. `/health` is the liveness
#: probe; `/v1/files/*` carries its own presigned authorization and is used for
#: bulk upload and download, where a per-minute request budget makes no sense.
_EXEMPT_PREFIXES = ("/health", "/v1/files/")


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Allow `limit` requests per `window_seconds` per caller.

    The caller is the authenticated user when the request carries a valid token,
    and the client address otherwise, so one user cannot spend another's budget.
    Counting is done with `CachePort.incr`, whose TTL is applied when the key is
    created; the window therefore starts at the first request of a burst.
    """

    def __init__(
        self,
        app: ASGIApp,
        cache: CachePort,
        tokens: TokenIssuerPort,
        clock: ClockPort,
        limit: int = 60,
        window_seconds: int = 60,
    ) -> None:
        super().__init__(app)
        self._cache = cache
        self._tokens = tokens
        self._clock = clock
        self._limit = limit
        self._window = window_seconds

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.url.path.startswith(_EXEMPT_PREFIXES):
            return await call_next(request)

        window = int(self._clock.now().timestamp()) // self._window
        key = f"rl:{self._caller(request)}:{window}"
        used = await self._cache.incr(key, ttl_seconds=self._window)
        if used > self._limit:
            return JSONResponse(
                status_code=429,
                content={
                    "error": {
                        "code": "rate_limited",
                        "message": f"more than {self._limit} requests in {self._window}s",
                    }
                },
                headers={"Retry-After": str(self._window)},
            )
        return await call_next(request)

    def _caller(self, request: Request) -> str:
        header = request.headers.get("authorization", "")
        if header.startswith("Bearer "):
            try:
                return f"user:{self._tokens.verify(header.removeprefix('Bearer '))}"
            except Unauthorized:
                pass
        client = request.client
        return f"ip:{client.host if client else 'unknown'}"
