# Changelog

All notable changes to FreeMyGPT are documented here. The format is
based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.2] — 2026-04-08

### Fixed

- Synced `freemygpt.__version__` in ``src/freemygpt/__init__.py`` with
  the distribution version in ``pyproject.toml``. The 0.1.1 wheel on
  PyPI shipped with a stale ``__version__ = "0.1.0"`` string (the
  distribution metadata is authoritative — only the runtime
  ``mem_status``-style diagnostic was affected). 0.1.2 is the first
  release where both strings agree.

## [0.1.1] — 2026-04-08

### Added

- **Base64 query-parameter support** for sending strings with reserved
  URL characters (`&`, `=`, `%`, newlines) and binary files through
  GET-only callers like ChatGPT's built-in browse tool. Two reserved
  suffix conventions:
  - `?foo_b64=<urlsafe-b64>` — decoded as a UTF-8 **string** and
    assigned to `args["foo"]`
  - `?foo_file_b64=<urlsafe-b64>` — decoded as **raw bytes** and
    assigned to `args["foo"]` as `{"bytes": …, "name": …, "mime": …,
    "size": …}`. Companion params `?foo_file_name=` and
    `?foo_file_mime=` are optional metadata.
- `_decode_b64` helper with strict charset pre-validation. Python's
  stdlib `urlsafe_b64decode` silently drops unknown characters; our
  helper regex-checks `[A-Za-z0-9\-_]+=*` before decoding so malformed
  input is rejected with a clear 400 instead of silently producing
  garbage bytes.
- 16 new tests covering the decoder directly, string and file forms,
  URL-safe + standard alphabets, padded + unpadded input, collision
  handling (`<key>_plain` debug preservation), and interaction with
  `args_json`.

### Changed

- On collision, `?foo_b64=…` now wins over `?foo=…` (explicit base64
  signals intent) and the plain form is preserved under
  `<key>_plain` for tool authors debugging conflicts.

## [0.1.0] — 2026-04-08

First public alpha. Single flat commit on `main` with the full
HTTP-to-MCP gateway, two backend adapters, the session store, CLI,
tests, CI, and release workflow.

### Added

- **FastAPI HTTP gateway** with GET-only endpoints so ChatGPT's
  built-in browse tool (which cannot emit POST requests or custom
  headers) can drive local MCP servers without any Custom GPT Action,
  OpenAPI spec, or GitHub plugin.
- **Two backend adapters** behind a shared `Backend` Protocol:
  - `McpStdioBackend` — wraps the official `mcp` Python SDK
    `stdio_client` + `ClientSession` so any stdio MCP server can be
    exposed through the HTTP surface
  - `CodexBackend` — bundled subprocess wrapper that spawns
    `codex exec <prompt>` and exposes a single synthetic `chat` tool
    so Codex looks like any other MCP backend from the HTTP side
- **Bearer token auth** — required on every endpoint except
  `/healthz`, accepted via `?token=` query param (for ChatGPT browse)
  or `Authorization: Bearer` header, compared in constant time via
  `hmac.compare_digest`
- **Refusal to start unauthenticated** — gateway raises at startup if
  `FREEMYGPT_TOKEN` is unset
- **Thread-safe SQLite session store** with WAL mode and RLock
  serialization so FastAPI worker threads can share one connection
- **YAML config file** at `~/.freemygpt/config.yaml` mapping backend
  names to launchers, with per-backend env and timeout overrides
- **CLI**: `freemygpt serve | doctor | new-token`
- **Tests**: 16 passing (config loader + full HTTP app with a fake
  backend swapped in for the factory)
- **CI**: ruff, mypy `--strict`, pytest on macOS + Ubuntu across
  Python 3.10 / 3.11 / 3.12
- **Release workflow**: tag-triggered wheel build, PyPI publish via
  OIDC trusted publisher, and GitHub release creation
- **Security posture**: `SECURITY.md` with private disclosure via
  GitHub advisories, `CODEOWNERS`, Dependabot weekly updates,
  `fork-watch` workflow that logs every fork and star to the Actions
  summary, branch protection on `main` blocking force pushes and
  deletions with linear history required
