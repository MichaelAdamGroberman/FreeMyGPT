"""MCP stdio backend — talks to any stdio-based MCP server.

Wraps the official ``mcp`` Python SDK's ``stdio_client`` +
``ClientSession`` so the bridge can connect to arbitrary MCP servers
defined in the config file — ``gr0m_mem``, a Kali MCP, a Home Assistant
MCP, or any other server that speaks the protocol over stdin/stdout.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from typing import Any

from mcp import StdioServerParameters
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client

from freemygpt.backends.base import (
    Backend,
    BackendError,
    ToolInfo,
    ToolResult,
)
from freemygpt.config import BackendConfig


class McpStdioBackend(Backend):
    """Long-lived connection to a stdio MCP server."""

    def __init__(self, cfg: BackendConfig) -> None:
        if cfg.type != "mcp":
            raise ValueError(f"expected type=mcp, got {cfg.type!r}")
        self.name = cfg.name
        self._cfg = cfg
        self._lock = asyncio.Lock()
        self._stack: contextlib.AsyncExitStack | None = None
        self._session: ClientSession | None = None

    async def start(self) -> None:
        """Spawn the MCP server subprocess and initialize the session.

        Idempotent: subsequent calls are no-ops. The spawned child is
        kept alive until :meth:`close` is called or the process exits.
        """
        async with self._lock:
            if self._session is not None:
                return
            stack = contextlib.AsyncExitStack()
            try:
                params = StdioServerParameters(
                    command=self._cfg.command,
                    args=list(self._cfg.args),
                    env={**os.environ, **self._cfg.env},
                )
                read, write = await stack.enter_async_context(stdio_client(params))
                session = await stack.enter_async_context(ClientSession(read, write))
                await session.initialize()
            except Exception as exc:
                await stack.aclose()
                raise BackendError(
                    f"failed to start MCP backend {self.name!r}: {exc}"
                ) from exc
            self._stack = stack
            self._session = session

    async def list_tools(self) -> list[ToolInfo]:
        await self.start()
        assert self._session is not None
        try:
            result = await self._session.list_tools()
        except Exception as exc:
            raise BackendError(f"list_tools failed on {self.name!r}: {exc}") from exc
        out: list[ToolInfo] = []
        for t in result.tools:
            schema: dict[str, Any] = {}
            raw_schema = getattr(t, "inputSchema", None)
            if isinstance(raw_schema, dict):
                schema = raw_schema
            out.append(
                ToolInfo(
                    name=t.name,
                    description=t.description or "",
                    input_schema=schema,
                )
            )
        return out

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float,
    ) -> ToolResult:
        await self.start()
        assert self._session is not None
        try:
            raw = await asyncio.wait_for(
                self._session.call_tool(tool_name, arguments),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError as exc:
            raise BackendError(
                f"tool {tool_name!r} on backend {self.name!r} timed out "
                f"after {timeout_s:.1f}s"
            ) from exc
        except Exception as exc:
            raise BackendError(
                f"tool {tool_name!r} on backend {self.name!r} failed: {exc}"
            ) from exc

        text_parts: list[str] = []
        structured: dict[str, Any] | None = None
        for block in raw.content:
            block_type = getattr(block, "type", "")
            if block_type == "text":
                text_parts.append(getattr(block, "text", ""))
            else:
                # Unknown content types — fall back to repr so callers
                # get *something* rather than silently dropping data.
                text_parts.append(repr(block))
        # Some SDK versions expose a structured payload separately.
        sc = getattr(raw, "structuredContent", None)
        if isinstance(sc, dict):
            structured = sc

        if not text_parts and structured is not None:
            text_parts.append(json.dumps(structured, indent=2))

        return ToolResult(
            text="\n".join(text_parts).strip(),
            structured=structured,
            is_error=bool(getattr(raw, "isError", False)),
        )

    async def close(self) -> None:
        async with self._lock:
            if self._stack is not None:
                with contextlib.suppress(Exception):
                    await self._stack.aclose()
                self._stack = None
                self._session = None
