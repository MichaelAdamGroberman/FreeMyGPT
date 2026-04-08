"""BridgeConfig loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from freemygpt.config import BridgeConfig


def _write(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "config.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_minimal_valid(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
auth:
  token_env: FREEMYGPT_TOKEN
backends:
  gr0m_mem:
    type: mcp
    command: python
    args: ["-m", "gr0m_mem.mcp_server"]
""",
    )
    cfg = BridgeConfig.load(p)
    assert cfg.auth.token_env == "FREEMYGPT_TOKEN"
    assert "gr0m_mem" in cfg.backends
    assert cfg.backends["gr0m_mem"].command == "python"
    assert cfg.backends["gr0m_mem"].args == ["-m", "gr0m_mem.mcp_server"]


def test_codex_backend(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
backends:
  codex:
    type: codex
    command: codex
    args: ["exec"]
    default_timeout_s: 60
""",
    )
    cfg = BridgeConfig.load(p)
    assert cfg.backends["codex"].type == "codex"
    assert cfg.backends["codex"].default_timeout_s == 60.0


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        BridgeConfig.load(tmp_path / "nope.yaml")


def test_unknown_backend_type_raises(tmp_path: Path) -> None:
    p = _write(
        tmp_path,
        """
backends:
  x:
    type: bogus
    command: /bin/true
""",
    )
    with pytest.raises(ValueError, match="unknown type"):
        BridgeConfig.load(p)


def test_no_backends_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "auth: {token_env: FREEMYGPT_TOKEN}\nbackends: {}\n")
    with pytest.raises(ValueError, match="at least one backend"):
        BridgeConfig.load(p)


def test_missing_command_raises(tmp_path: Path) -> None:
    p = _write(tmp_path, "backends:\n  x:\n    type: mcp\n")
    with pytest.raises(ValueError, match="'command'"):
        BridgeConfig.load(p)
