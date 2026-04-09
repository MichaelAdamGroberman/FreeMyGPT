# FreeMyGPT

[![CI](https://github.com/MichaelAdamGroberman/FreeMyGPT/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/MichaelAdamGroberman/FreeMyGPT/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/freemygpt.svg?logo=pypi&logoColor=white&label=PyPI)](https://pypi.org/project/freemygpt/)
[![Python](https://img.shields.io/pypi/pyversions/freemygpt.svg?logo=python&logoColor=white)](https://pypi.org/project/freemygpt/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Downloads](https://static.pepy.tech/badge/freemygpt)](https://pepy.tech/project/freemygpt)
[![Code style: ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Checked with mypy](https://www.mypy-lang.org/static/mypy_badge.svg)](https://mypy-lang.org/)

> **Free ChatGPT from its sandbox.** FreeMyGPT is a tiny HTTP gateway that lets ChatGPT (and any other LLM with an HTTP fetcher) drive **any local MCP server** — Gr0m_Mem, Codex CLI, Kali MCP, Home Assistant MCP, or anything else that speaks the Model Context Protocol — using nothing but **simple GET requests**. No Custom GPT Actions, no GitHub plugin, no OAuth dance, no POST bodies.

```
ChatGPT  ──GET──►  FreeMyGPT  ──stdio──►  MCP server (any)
                                  └─────►  Codex CLI (subprocess)
```

## Why

- ChatGPT's built-in browse tool can **read URLs** but cannot send POST requests or custom headers. Everyone else's "let ChatGPT call your API" guide assumes Custom GPT Actions. FreeMyGPT assumes you do not have that option.
- Local MCP servers are powerful (Gr0m_Mem, the Kali server, Home Assistant, Codex) but they only speak stdio. They cannot be reached from a ChatGPT conversation by default.
- FreeMyGPT is the thinnest possible layer between them: a FastAPI app that spawns each MCP server on first use, forwards `call_tool` requests, and returns the result as JSON in the HTTP response. Bearer token auth via `?token=…` query param so ChatGPT can pass it without setting headers.

## Architecture

- **HTTP frontend** (FastAPI, stdio) — GET-only, JSON responses
- **Hybrid backends**:
  - `mcp` — any stdio MCP server (official `mcp` Python SDK client)
  - `codex` — bundled wrapper that spawns `codex exec <prompt>` and exposes a single `chat` tool, so Codex looks like any other MCP backend from the HTTP side
- **Bearer token auth** — required on every endpoint except `/healthz`, read from an env var, matched in constant time
- **Session store** — SQLite; stores chat transcripts so ChatGPT can poll long-running sessions without losing history
- **One config file** — YAML with an `auth` block and a `backends` map; see `config.example.yaml`

## HTTP surface

```
GET /healthz                                        (no auth)
GET /backends                                       ?token=...
GET /{backend}/tools                                ?token=...
GET /{backend}/call/{tool}                          ?token=...&arg1=...&arg2=...
GET /{backend}/sessions/new                         ?token=...&label=...
GET /{backend}/sessions/{sid}/send                  ?token=...&message=...
GET /{backend}/sessions/{sid}/poll                  ?token=...&since=<id>
GET /{backend}/sessions/{sid}/close                 ?token=...
```

**Tool arguments** are passed as query parameters. Simple scalars (strings, ints, floats, bools) are coerced automatically. For structured arguments, pass them as a JSON blob in `args_json`:

```
GET /gr0m_mem/call/mem_record_decision?token=...&args_json={"subject":"db","decision":"Postgres","rationale":"concurrent writes"}
```

### Base64 string and file arguments

ChatGPT's built-in browse tool can only emit GET requests with URL-safe query strings, so callers can't upload binary files or send text that contains reserved characters (`&`, `=`, `%`, newlines) directly. FreeMyGPT accepts base64 through two reserved suffix conventions:

- **`?foo_b64=<urlsafe-b64>`** — decoded as a UTF-8 **string** and assigned to `args["foo"]`. Use for long text payloads or content with reserved URL characters.
- **`?foo_file_b64=<urlsafe-b64>`** — decoded as **raw bytes**. Assigned to `args["foo"]` as `{"bytes": b"...", "name": str, "mime": str, "size": int}`. Companion params `?foo_file_name=` and `?foo_file_mime=` are optional metadata.

Both accept standard Base64 (`+`/`/`) **and** URL-safe Base64 (`-`/`_`), padded or unpadded. Binary bytes in a `*_b64` param (not `*_file_b64`) return a 400 with a clear pointer at the correct form.

Example — sending a PNG to a tool that builds a captioned image:

```bash
# PNG bytes are base64-encoded first:
IMG=$(base64 -i hero.png | tr -d '\n')

# Then sent as a single GET:
curl -G "https://<tunnel>/mytool/call/caption" \
     --data-urlencode "token=<yours>" \
     --data-urlencode "image_file_b64=$IMG" \
     --data-urlencode "image_file_name=hero.png" \
     --data-urlencode "image_file_mime=image/png" \
     --data-urlencode "caption=release day"
```

If both a plain value and its base64 variant are sent for the same key, the base64 form wins (explicit intent) and the plain form is preserved under `<key>_plain` for debugging.

## Quick start

```bash
pip install freemygpt

# 1. Make a token
export FREEMYGPT_TOKEN="$(freemygpt new-token)"

# 2. Write a config
mkdir -p ~/.freemygpt
cp $(python -c "import freemygpt, os; print(os.path.join(os.path.dirname(freemygpt.__file__), '..', '..', 'config.example.yaml'))") ~/.freemygpt/config.yaml
# edit to enable the backends you want

# 3. Sanity check
freemygpt doctor

# 4. Run
freemygpt serve --host 127.0.0.1 --port 8933
```

## Exposing it to ChatGPT

ChatGPT needs to reach the gateway over the public internet. Pick any reverse tunnel:

### Option A — Cloudflare Tunnel (recommended, free, no account required for quick tunnels)

```bash
brew install cloudflared
cloudflared tunnel --url http://127.0.0.1:8933
```

Cloudflared prints a `https://<random>.trycloudflare.com` URL. Paste it into your ChatGPT conversation with the token appended:

```
https://<random>.trycloudflare.com/gr0m_mem/call/mem_wakeup?token=<your token>
```

ChatGPT will browse the URL and inline the JSON response.

### Option B — Tailscale Funnel

If your machine is already on Tailscale, enable Funnel on port 8933 and use the `*.ts.net` hostname. Token auth still applies.

### Option C — ngrok

```bash
ngrok http 8933
```

Same idea.

## Using it from a ChatGPT conversation

Once the URL is live and the token is in the query string, a ChatGPT conversation looks like:

> **You:** Fetch `https://tunnel.example.com/gr0m_mem/call/mem_wakeup?token=XYZ` and summarize the response.
>
> **ChatGPT:** *(browses the URL, receives the JSON snapshot)* You're Michael, a software engineer on macOS; active project is the FreeMyGPT launch; recent decisions locked in: Postgres for the database (concurrent writes), Clerk over Auth0 (better DX), SQLite FTS5 is the zero-dep default for Gr0m_Mem.

Because the responses are plain JSON, any LLM with an HTTP fetcher (Claude browsing, Gemini's `google_search_retrieval`, local Llama with a URL-fetching tool, etc.) can use the exact same URLs.

## Security posture

- Bearer token required on every authenticated endpoint, compared in constant time
- Gateway refuses to start if the configured env var is empty
- Every backend runs as a subprocess of the gateway — no network listener exposed
- Session state in SQLite with `PRAGMA foreign_keys=ON`; sessions delete their messages on close
- `SECURITY.md` documents private vulnerability reporting via GitHub advisories
- Branch protection on every long-lived branch (no force pushes, no deletions, linear history)
- CI runs ruff, mypy `--strict`, and the full test suite on every push

See [`SECURITY.md`](SECURITY.md) for the full disclosure policy and out-of-scope list.

## Status

v0.1.0 alpha. API surface is stable; the wire format (`{"text": ..., "structured": ..., "is_error": ...}`) is not expected to change. Breaking changes will bump the minor version until v1.0.

## License

MIT — see [LICENSE](LICENSE).

## Contact

Maintained by **Michael Adam Groberman**.

- **GitHub**: [@MichaelAdamGroberman](https://github.com/MichaelAdamGroberman)
- **LinkedIn**: [michael-adam-groberman](https://www.linkedin.com/in/michael-adam-groberman/)

For security reports, use GitHub private vulnerability advisories (see [SECURITY.md](SECURITY.md)) — **do not** use LinkedIn DMs for sensitive disclosures.
