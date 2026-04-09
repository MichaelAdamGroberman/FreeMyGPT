<!--
  Thanks for the pull request! Before you submit, please check off
  every item in the "Required checks" list.
-->

## What does this change?

<!-- 1-3 sentences describing the user-visible effect. -->

## Why?

Closes #

## How did you test it?

```console
$ .venv/bin/python -m pytest -q tests/test_<your_area>.py

```

## Required checks

- [ ] The three CI commands pass locally:
  - [ ] `ruff check src tests`
  - [ ] `mypy src`
  - [ ] `pytest -q`
- [ ] If this touches `src/freemygpt/app.py::_coerce_tool_args` or base64 handling, `tests/test_base64_args.py` still passes
- [ ] New public API is covered by a test in `tests/`
- [ ] Commit messages follow [Conventional Commits](https://www.conventionalcommits.org/) (`feat:`, `fix:`, `docs:`, etc.)
- [ ] If this changes behavior users will notice, `CHANGELOG.md` has an entry under `## [Unreleased]`
- [ ] I have read the [Code of Conduct](CODE_OF_CONDUCT.md)

## Optional

- [ ] This is a breaking change to the HTTP surface (new version bump required)
- [ ] This adds a new backend type (describe authentication, error model, and lifecycle)
- [ ] This adds a new dependency (justify in the description)
