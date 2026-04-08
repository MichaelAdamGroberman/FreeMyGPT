"""Command-line entry point for FreeMyGPT.

Subcommands:

* ``serve``      — run the HTTP gateway (uvicorn)
* ``doctor``     — load the config and report its health
* ``new-token``  — print a fresh random bearer token
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from pathlib import Path

from freemygpt import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freemygpt",
        description=(
            "FreeMyGPT — HTTP gateway that lets ChatGPT (and any LLM) "
            "drive any local MCP server via simple GET requests."
        ),
    )
    parser.add_argument("--version", action="version", version=f"freemygpt {__version__}")

    sub = parser.add_subparsers(dest="command", required=True)

    p_serve = sub.add_parser("serve", help="Run the HTTP gateway")
    p_serve.add_argument("--host", default=os.environ.get("FREEMYGPT_HOST", "127.0.0.1"))
    p_serve.add_argument(
        "--port", type=int, default=int(os.environ.get("FREEMYGPT_PORT", "8933"))
    )
    p_serve.add_argument(
        "--config",
        type=Path,
        default=None,
        help="Path to the YAML config file (defaults to ~/.freemygpt/config.yaml)",
    )

    sub.add_parser("doctor", help="Load the config and report its health")
    sub.add_parser("new-token", help="Print a fresh random bearer token")

    return parser


def _cmd_serve(args: argparse.Namespace) -> int:
    import uvicorn

    from freemygpt.app import create_app
    from freemygpt.config import BridgeConfig

    cfg = BridgeConfig.load(args.config)
    app = create_app(cfg=cfg)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    return 0


def _cmd_doctor(_: argparse.Namespace) -> int:
    from freemygpt.config import BridgeConfig

    try:
        cfg = BridgeConfig.load()
    except FileNotFoundError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"freemygpt {__version__}")
    print(f"  token env var: {cfg.auth.token_env}")
    if cfg.auth.token:
        print("  token:         present (hidden)")
    else:
        print(f"  token:         MISSING — export {cfg.auth.token_env}=... before serve")
    print(f"  backends:      {len(cfg.backends)}")
    for name, entry in cfg.backends.items():
        print(f"    - {name} ({entry.type}): {entry.command} {' '.join(entry.args)}")
    return 0


def _cmd_new_token(_: argparse.Namespace) -> int:
    print(secrets.token_urlsafe(32))
    return 0


_HANDLERS = {
    "serve": _cmd_serve,
    "doctor": _cmd_doctor,
    "new-token": _cmd_new_token,
}


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    return _HANDLERS[args.command](args)


if __name__ == "__main__":
    raise SystemExit(main())
