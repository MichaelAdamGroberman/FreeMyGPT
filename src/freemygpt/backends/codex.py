"""Codex CLI backend — spawns ``codex exec`` as a subprocess per call.

Codex is exposed as a **single synthetic tool** called ``chat`` so it
fits the HTTP shape the bridge gives every other backend. The tool
takes a ``message`` argument, forwards it to Codex via stdin (or as a
positional argument, depending on the binary's calling convention),
captures stdout, and returns it as the tool result.

This is intentionally dumb — we do not try to parse Codex's output or
reinterpret its structure. The caller (ChatGPT) sees whatever Codex
printed. That keeps the bridge transparent and preserves whatever
progress / streaming / error messages Codex emits.

If the Codex binary is not on PATH the backend still starts; the error
surfaces at first call time as a clean :class:`BackendError`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from freemygpt.backends.base import (
    Backend,
    BackendError,
    ToolInfo,
    ToolResult,
)
from freemygpt.config import BackendConfig

CHAT_TOOL = ToolInfo(
    name="chat",
    description=(
        "Send a prompt to Codex (or whichever command this backend is "
        "configured to run). Returns whatever Codex prints on stdout. "
        "Non-zero exit codes are returned as error results rather than "
        "exceptions so the caller can display them."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "message": {
                "type": "string",
                "description": "The prompt / task description to hand to Codex.",
            }
        },
        "required": ["message"],
    },
)


class CodexBackend(Backend):
    """One-shot Codex runner. No persistent process — each call is fresh."""

    def __init__(self, cfg: BackendConfig) -> None:
        if cfg.type != "codex":
            raise ValueError(f"expected type=codex, got {cfg.type!r}")
        self.name = cfg.name
        self._cfg = cfg

    async def start(self) -> None:
        # No setup — we spawn a fresh process on every call_tool.
        return None

    async def list_tools(self) -> list[ToolInfo]:
        return [CHAT_TOOL]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float,
    ) -> ToolResult:
        if tool_name != CHAT_TOOL.name:
            raise BackendError(
                f"codex backend only exposes {CHAT_TOOL.name!r}, got {tool_name!r}"
            )
        message = arguments.get("message")
        if not isinstance(message, str) or not message.strip():
            raise BackendError("codex chat requires a non-empty 'message' argument")

        argv = [self._cfg.command, *self._cfg.args, message]
        env = {**os.environ, **self._cfg.env}

        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env,
            )
        except FileNotFoundError as exc:
            raise BackendError(
                f"codex backend {self.name!r}: command {argv[0]!r} not found "
                f"on PATH ({exc})"
            ) from exc

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=timeout_s
            )
        except asyncio.TimeoutError as exc:
            proc.kill()
            await proc.wait()
            raise BackendError(
                f"codex backend {self.name!r} timed out after {timeout_s:.1f}s"
            ) from exc

        text = (stdout or b"").decode("utf-8", errors="replace").strip()
        err = (stderr or b"").decode("utf-8", errors="replace").strip()
        exit_code = proc.returncode or 0

        if exit_code != 0:
            combined = text
            if err:
                combined = f"{combined}\n\n[stderr]\n{err}" if combined else err
            return ToolResult(
                text=combined or f"codex exited with code {exit_code}",
                structured={"exit_code": exit_code},
                is_error=True,
            )

        return ToolResult(
            text=text,
            structured={"exit_code": 0, "stderr": err} if err else None,
            is_error=False,
        )

    async def close(self) -> None:
        return None
