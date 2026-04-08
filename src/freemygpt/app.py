"""FastAPI application — the HTTP gateway itself.

Exposes a small GET-only surface so ChatGPT's built-in browse tool
(which cannot emit POST requests) can drive it without any Custom GPT
Action, OpenAPI spec, or GitHub plugin. The auth token is accepted
either in the standard ``Authorization: Bearer …`` header or in a
``?token=…`` query parameter — the latter is the only path a ChatGPT
browse call can use.

Endpoints::

    GET /healthz                             — liveness, no auth
    GET /backends                            — list configured backends
    GET /{backend}/tools                     — list tools exposed by a backend
    GET /{backend}/call/{tool}?arg=...       — invoke a tool and return JSON
    GET /{backend}/sessions/new?label=...    — create a chat session
    GET /{backend}/sessions/{sid}/send?message=...
                                             — send a chat message, return reply
    GET /{backend}/sessions/{sid}/poll?since=...
                                             — poll for new messages
    GET /{backend}/sessions/{sid}/close      — close a session

Tool arguments are supplied as query parameters. Simple scalar tools
work out of the box (strings, ints, floats, bools). For structured
arguments, pass them as a JSON blob in an ``args_json`` query parameter.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from freemygpt import __version__
from freemygpt.auth import require_token
from freemygpt.backends import (
    Backend,
    BackendError,
    CodexBackend,
    McpStdioBackend,
)
from freemygpt.config import BridgeConfig
from freemygpt.sessions import SessionStore

log = logging.getLogger("freemygpt")


def _build_backend(cfg_entry: Any) -> Backend:
    if cfg_entry.type == "mcp":
        return McpStdioBackend(cfg_entry)
    if cfg_entry.type == "codex":
        return CodexBackend(cfg_entry)
    raise ValueError(f"unknown backend type {cfg_entry.type!r}")


def _coerce_tool_args(request: Request) -> dict[str, Any]:
    """Pull tool arguments out of query parameters.

    Reserved keys (``token``, ``timeout_s``, ``args_json``) are never
    treated as tool arguments. If ``args_json`` is present it is parsed
    and merged on top of the individual query params so the caller can
    mix simple scalars with a structured blob.
    """
    reserved = {"token", "timeout_s", "args_json"}
    args: dict[str, Any] = {}
    for key, value in request.query_params.multi_items():
        if key in reserved:
            continue
        # Attempt numeric / bool coercion so ChatGPT can send plain
        # query strings and still hit tools that want typed args.
        args[key] = _coerce(value)
    blob = request.query_params.get("args_json")
    if blob:
        try:
            parsed = json.loads(blob)
        except json.JSONDecodeError as exc:
            raise HTTPException(
                status_code=400, detail=f"invalid args_json: {exc}"
            ) from exc
        if not isinstance(parsed, dict):
            raise HTTPException(
                status_code=400, detail="args_json must decode to a JSON object"
            )
        args.update(parsed)
    return args


def _coerce(value: str) -> Any:
    if value.lower() in ("true", "false"):
        return value.lower() == "true"
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        return value


def create_app(
    cfg: BridgeConfig | None = None,
    session_db_path: Path | None = None,
) -> FastAPI:
    cfg = cfg or BridgeConfig.load()
    auth_dep = require_token(cfg)
    session_db_path = session_db_path or (
        Path.home() / ".freemygpt" / "sessions.db"
    )
    store = SessionStore(session_db_path)

    # Instantiate (but do not yet start) every configured backend.
    backends: dict[str, Backend] = {
        name: _build_backend(entry) for name, entry in cfg.backends.items()
    }

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        try:
            yield
        finally:
            for b in backends.values():
                try:
                    await b.close()
                except Exception:  # noqa: BLE001
                    log.exception("backend close failed: %s", b.name)
            store.close_store()

    app = FastAPI(
        title="FreeMyGPT",
        version=__version__,
        description=(
            "HTTP gateway that lets ChatGPT (and any LLM with an HTTP "
            "fetcher) drive any local MCP server via simple GET requests."
        ),
        lifespan=lifespan,
    )

    # ── Public ──────────────────────────────────────────

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    # ── Authenticated ──────────────────────────────────

    @app.get("/backends", dependencies=[auth_dep])
    async def list_backends() -> dict[str, Any]:
        return {
            "backends": [
                {"name": name, "type": entry.type, "command": entry.command}
                for name, entry in cfg.backends.items()
            ]
        }

    def _backend_or_404(name: str) -> Backend:
        backend = backends.get(name)
        if backend is None:
            raise HTTPException(status_code=404, detail=f"unknown backend {name!r}")
        return backend

    @app.get("/{backend}/tools", dependencies=[auth_dep])
    async def list_tools(backend: str) -> dict[str, Any]:
        b = _backend_or_404(backend)
        try:
            tools = await b.list_tools()
        except BackendError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return {"backend": backend, "tools": [asdict(t) for t in tools]}

    @app.get("/{backend}/call/{tool}", dependencies=[auth_dep])
    async def call_tool(
        backend: str,
        tool: str,
        request: Request,
        timeout_s: float | None = Query(default=None),
    ) -> JSONResponse:
        b = _backend_or_404(backend)
        args = _coerce_tool_args(request)
        effective_timeout = timeout_s or cfg.backends[backend].default_timeout_s
        try:
            result = await b.call_tool(
                tool_name=tool,
                arguments=args,
                timeout_s=effective_timeout,
            )
        except BackendError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return JSONResponse(
            {
                "backend": backend,
                "tool": tool,
                "is_error": result.is_error,
                "text": result.text,
                "structured": result.structured,
            }
        )

    # ── Sessions ───────────────────────────────────────

    @app.get("/{backend}/sessions/new", dependencies=[auth_dep])
    async def new_session(
        backend: str, label: str = Query(default="default")
    ) -> dict[str, Any]:
        _backend_or_404(backend)
        sess = store.create(backend=backend, label=label)
        return {
            "session_id": sess.id,
            "backend": sess.backend,
            "label": sess.label,
            "created_at": sess.created_at.isoformat(),
        }

    @app.get("/{backend}/sessions/{sid}/send", dependencies=[auth_dep])
    async def send_message(
        backend: str,
        sid: str,
        message: str = Query(...),
        timeout_s: float | None = Query(default=None),
    ) -> dict[str, Any]:
        b = _backend_or_404(backend)
        sess = store.get(sid)
        if sess is None or sess.backend != backend:
            raise HTTPException(
                status_code=404, detail=f"session {sid!r} not found on backend {backend!r}"
            )
        store.append(session_id=sid, role="user", text=message)
        effective_timeout = timeout_s or cfg.backends[backend].default_timeout_s
        try:
            result = await b.call_tool(
                tool_name="chat",
                arguments={"message": message},
                timeout_s=effective_timeout,
            )
        except BackendError as exc:
            # Record the failure in the session transcript so poll() sees it.
            store.append(
                session_id=sid,
                role="backend",
                text=str(exc),
                is_error=True,
            )
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        reply = store.append(
            session_id=sid,
            role="backend",
            text=result.text,
            structured=result.structured,
            is_error=result.is_error,
        )
        return {
            "session_id": sid,
            "message_id": reply.id,
            "is_error": result.is_error,
            "text": result.text,
            "structured": result.structured,
        }

    @app.get("/{backend}/sessions/{sid}/poll", dependencies=[auth_dep])
    async def poll_session(
        backend: str, sid: str, since: int = Query(default=0)
    ) -> dict[str, Any]:
        sess = store.get(sid)
        if sess is None or sess.backend != backend:
            raise HTTPException(
                status_code=404, detail=f"session {sid!r} not found on backend {backend!r}"
            )
        messages = store.list_messages(sid, since_id=since)
        return {
            "session_id": sid,
            "count": len(messages),
            "messages": [
                {
                    "id": m.id,
                    "role": m.role,
                    "text": m.text,
                    "structured": m.structured,
                    "is_error": m.is_error,
                    "created_at": m.created_at.isoformat(),
                }
                for m in messages
            ],
        }

    @app.get("/{backend}/sessions/{sid}/close", dependencies=[auth_dep])
    async def close_session(backend: str, sid: str) -> dict[str, Any]:
        ok = store.close(sid)
        return {"session_id": sid, "closed": ok}

    return app
