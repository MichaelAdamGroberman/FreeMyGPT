"""Backend protocol.

Every backend the bridge can talk to (MCP stdio server, Codex CLI, etc.)
implements the small async API defined here:

* :meth:`Backend.list_tools` — return available tools
* :meth:`Backend.call_tool`  — invoke a tool and return the result
* :meth:`Backend.close`      — release any held subprocess / session

Backends are lazily started on first use and reused across requests.
They are **not** session-scoped — state like "the user asked Codex for
a diff" lives in the shared :class:`freemygpt.sessions.SessionStore`
so it survives HTTP request boundaries.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable


class BackendError(RuntimeError):
    """Raised when a backend call fails (timeout, tool missing, bad args)."""


@dataclass(frozen=True, slots=True)
class ToolInfo:
    name: str
    description: str
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Normalized result returned by every backend.

    ``is_error`` is a soft flag: ``True`` when the tool itself reported
    a failure (for example an MCP ``isError`` result), distinct from an
    exception raised by the transport (which propagates as
    :class:`BackendError`).
    """

    text: str
    structured: dict[str, Any] | None = None
    is_error: bool = False


@runtime_checkable
class Backend(Protocol):
    name: str

    async def start(self) -> None: ...

    async def list_tools(self) -> list[ToolInfo]: ...

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float,
    ) -> ToolResult: ...

    async def close(self) -> None: ...
