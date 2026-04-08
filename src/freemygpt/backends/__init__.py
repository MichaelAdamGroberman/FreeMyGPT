"""Backend adapters: one class per runtime the bridge can talk to."""

from freemygpt.backends.base import (
    Backend,
    BackendError,
    ToolInfo,
    ToolResult,
)
from freemygpt.backends.codex import CodexBackend
from freemygpt.backends.mcp_stdio import McpStdioBackend

__all__ = [
    "Backend",
    "BackendError",
    "CodexBackend",
    "McpStdioBackend",
    "ToolInfo",
    "ToolResult",
]
