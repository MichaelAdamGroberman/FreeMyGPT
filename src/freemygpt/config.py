"""Config loader for FreeMyGPT.

Config is a YAML file mapping backend names to their launcher. A backend
is either ``type: mcp`` (any stdio MCP server) or ``type: codex``
(shorthand for spawning the Codex CLI in non-interactive mode).

Example ``config.yaml``::

    auth:
      # Bearer token required on every request. Generate with:
      #   python -c "import secrets; print(secrets.token_urlsafe(32))"
      token_env: FREEMYGPT_TOKEN

    backends:
      gr0m_mem:
        type: mcp
        command: python
        args: ["-m", "gr0m_mem.mcp_server"]

      codex:
        type: codex
        command: codex
        args: ["exec"]

      kali:
        type: mcp
        command: /usr/local/bin/kali-mcp
        args: []
        env:
          KALI_HOST: 10.0.0.29

The config file path is taken from ``FREEMYGPT_CONFIG`` (defaults to
``~/.freemygpt/config.yaml``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

BackendType = Literal["mcp", "codex"]


@dataclass(frozen=True, slots=True)
class BackendConfig:
    name: str
    type: BackendType
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    # Seconds to wait for a single tool call before aborting. Generous
    # default because Codex can take a while; per-call override via
    # ``?timeout_s=...`` query param.
    default_timeout_s: float = 120.0


@dataclass(frozen=True, slots=True)
class AuthConfig:
    token_env: str = "FREEMYGPT_TOKEN"

    @property
    def token(self) -> str | None:
        """Read the bearer token from the configured env var, if set."""
        return os.environ.get(self.token_env)


@dataclass(frozen=True, slots=True)
class BridgeConfig:
    auth: AuthConfig
    backends: dict[str, BackendConfig]

    @classmethod
    def load(cls, path: Path | None = None) -> BridgeConfig:
        path = path or _default_path()
        if not path.exists():
            raise FileNotFoundError(
                f"chatgpt-external-bridge config not found at {path}. "
                "Copy config.example.yaml and set FREEMYGPT_CONFIG "
                "to point at it."
            )
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return cls._from_raw(raw)

    @classmethod
    def _from_raw(cls, raw: dict[str, Any]) -> BridgeConfig:
        auth_raw = raw.get("auth") or {}
        auth = AuthConfig(token_env=auth_raw.get("token_env", "FREEMYGPT_TOKEN"))

        backends_raw = raw.get("backends") or {}
        if not backends_raw:
            raise ValueError("config must define at least one backend")

        backends: dict[str, BackendConfig] = {}
        for name, entry in backends_raw.items():
            if not isinstance(entry, dict):
                raise ValueError(f"backend {name!r} must be a mapping")
            btype = entry.get("type")
            if btype not in ("mcp", "codex"):
                raise ValueError(
                    f"backend {name!r} has unknown type {btype!r} "
                    "(expected 'mcp' or 'codex')"
                )
            command = entry.get("command")
            if not command:
                raise ValueError(f"backend {name!r} is missing 'command'")
            backends[name] = BackendConfig(
                name=name,
                type=btype,
                command=str(command),
                args=[str(a) for a in entry.get("args") or []],
                env={str(k): str(v) for k, v in (entry.get("env") or {}).items()},
                default_timeout_s=float(entry.get("default_timeout_s", 120.0)),
            )

        return cls(auth=auth, backends=backends)


def _default_path() -> Path:
    override = os.environ.get("FREEMYGPT_CONFIG")
    if override:
        return Path(override).expanduser()
    return Path.home() / ".freemygpt" / "config.yaml"
