# Security Policy

## Supported versions

FreeMyGPT is in `0.1.x` alpha. Only the latest tagged release on `main`
receives security fixes.

| Branch  | Status  | Fixes |
|---------|---------|-------|
| `main`  | current | ✅    |
| earlier | n/a     | ❌    |

## Reporting a vulnerability

**Please do not open a public issue for security reports.** Instead:

1. Open a GitHub **private vulnerability report** via the "Report a
   vulnerability" button on the Security tab:
   <https://github.com/MichaelAdamGroberman/FreeMyGPT/security/advisories/new>
2. Or email the maintainer directly (see GitHub profile).

Include:

- The affected version and commit SHA
- A minimal reproduction (the exact request sequence that demonstrates
  the issue)
- Impact — what data, state, or capability an attacker could gain

You will receive an initial response within 72 hours. Fixes for
confirmed vulnerabilities are prioritized; credit is given by default
unless you request anonymity.

## Scope

In scope:

- Authentication bypasses (missing / weak / timing-sensitive token
  checks on any authenticated endpoint)
- Command injection through query parameters into subprocess backends
  (the Codex backend and any `mcp` backend that forwards arguments to
  a child process)
- Session-state leakage between tenants
- Denial of service from an unauthenticated caller (authenticated DoS
  is out of scope — bring your own rate limiter)
- Supply chain issues in the build and release workflows

Out of scope:

- Attacks that require an attacker already on the same machine with
  read access to `~/.freemygpt/sessions.db`
- Vulnerabilities in the backends themselves (the MCP server or the
  Codex CLI) — report those upstream
- Misconfigurations (missing token, exposed port) — the gateway
  refuses to start without a token but cannot defend against a user
  deliberately binding it to `0.0.0.0` behind no firewall

## Hardening applied by default

- Bearer token required on every endpoint except `/healthz`; compared
  in constant time via `hmac.compare_digest`
- The gateway raises at startup if the token env var is unset
- Every subprocess backend inherits a scrubbed environment (only the
  keys explicitly listed in the config's `env` block plus the
  process's own environment) — no secret leakage via child env
- Session-owned SQLite databases enable `foreign_keys=ON` and
  `journal_mode=WAL` and cascade-delete messages when a session closes
- Branch protection on `main` blocks force pushes, deletions, and
  non-linear history; code owner reviews required on every PR
- Secret scanning + push protection + Dependabot security updates
  enabled on the repository
