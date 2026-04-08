"""Bearer-token authentication for the HTTP gateway.

ChatGPT's browse tool can only send simple GET requests, so we accept
the token either in the ``Authorization: Bearer …`` header (for callers
that can set headers) or in a ``?token=…`` query string parameter (for
the Custom GPT / browse case where headers are not available).

Every request except ``/healthz`` must include a valid token. Without
a configured ``FREEMYGPT_TOKEN`` env var, the gateway refuses to
start — we never run in an unauthenticated mode, even on localhost,
because the whole point of the gateway is to be reachable from the
public internet.
"""

from __future__ import annotations

import hmac
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Query, Request, status
from fastapi import params as fastapi_params

from freemygpt.config import BridgeConfig


def _extract_token(request: Request, token_qs: str | None) -> str | None:
    """Pull a candidate token out of the request, header first."""
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1].strip()
    return token_qs


def require_token(cfg: BridgeConfig) -> fastapi_params.Depends:
    """Build a FastAPI dependency that enforces the configured bearer token."""

    expected = cfg.auth.token
    if not expected:
        raise RuntimeError(
            "no bearer token configured — set "
            f"{cfg.auth.token_env} before starting the bridge. "
            "We refuse to run unauthenticated because the gateway is "
            "intended to be reachable from the public internet."
        )

    async def _check(
        request: Request,
        token: Annotated[str | None, Query()] = None,
    ) -> None:
        candidate = _extract_token(request, token)
        if candidate is None or not hmac.compare_digest(candidate, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="missing or invalid bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return cast(fastapi_params.Depends, Depends(_check))
