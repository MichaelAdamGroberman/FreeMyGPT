# Contributing to FreeMyGPT

Thanks for your interest! This file is the practical "how do I help"
guide. The governance contract is in
[`CODE_OF_CONDUCT.md`](CODE_OF_CONDUCT.md) and the disclosure policy
is in [`SECURITY.md`](SECURITY.md).

## Before you open an issue or PR

- **Security issues** — please do NOT open a public issue. Use the
  GitHub private vulnerability reporting button on the Security tab,
  or email the maintainer. See [`SECURITY.md`](SECURITY.md) for the
  full disclosure policy.
- **Bug reports** — use the **Bug report** issue template
  (`.github/ISSUE_TEMPLATE/bug_report.yml`). Include:
  - FreeMyGPT version (`freemygpt --version`)
  - Python version (`python --version`)
  - OS and arch (`uname -a` on Unix)
  - Output of `freemygpt doctor`
  - The backend you configured (`mcp` stdio or `codex` subprocess)
  - A minimal reproducer (the exact GET URL that fails, with the
    token redacted)
  - The actual error or unexpected behavior
- **Feature requests** — use the **Feature request** template. Tell us
  the problem before the solution. A small change that fits the
  GET-only philosophy is more likely to merge than a big change that
  adds a new transport.
- **Questions** — open a GitHub Discussion instead of an issue.

## Local development setup

```bash
git clone https://github.com/<you>/FreeMyGPT.git
cd FreeMyGPT

# uv — recommended
uv venv --python 3.12
uv pip install -e ".[dev]"

# Or pip + venv
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Generate a local dev token
export FREEMYGPT_TOKEN="$(freemygpt new-token)"

# Write a config file (example provided)
mkdir -p ~/.freemygpt
cp config.example.yaml ~/.freemygpt/config.yaml
# ... edit backends to taste

# Run the gateway
freemygpt serve --host 127.0.0.1 --port 8933
```

## Running the checks locally

The CI runs the exact same three commands:

```bash
.venv/bin/python -m ruff check src tests
.venv/bin/python -m mypy src
.venv/bin/python -m pytest -q
```

All 32 tests must pass. The test suite includes the base64
query-parameter coverage — if you touch `_coerce_tool_args` in
`src/freemygpt/app.py`, the 16 base64 tests in
`tests/test_base64_args.py` must stay green.

## Coding conventions

- **Python 3.10+**, `from __future__ import annotations` at the top of
  every file
- **Ruff** with the rules in `pyproject.toml` (E, F, I, B, UP, SIM)
- **Mypy `--strict`** — every function gets type hints
- **Conventional Commits** for commit messages (`feat:`, `fix:`,
  `docs:`, `test:`, `ci:`, `refactor:`, `perf:`, `chore:`, `sec:`,
  optionally scoped like `feat(backends):` or `feat(auth):`)
- **GET-only transport** — never add a `POST`, `PUT`, `DELETE`, or
  request-body-using route. Every caller is assumed to be
  ChatGPT browse or an equally-constrained tool. If a feature
  genuinely needs a body, implement it as a session-based flow that
  streams the state through multiple GETs
- **Constant-time token comparison** — any new auth logic uses
  `hmac.compare_digest`, never `==`
- **Backend adapters** that spawn subprocesses must inherit a scrubbed
  environment (only the keys explicitly listed in the config's `env`
  block plus the process's own environment)

## Pull request flow

1. Open an issue first for non-trivial changes
2. Fork, branch (`feat/short-topic` or `fix/short-topic`), make the
   change, verify the three local checks pass
3. Open the PR using the template (`.github/PULL_REQUEST_TEMPLATE.md`)
4. CI runs across macOS + Ubuntu on Python 3.10, 3.11, 3.12
5. The maintainer is `@MichaelAdamGroberman` and is auto-requested as
   a reviewer via `CODEOWNERS`

## License

By contributing you agree that your contribution will be licensed
under the [MIT License](LICENSE) that covers this project.
