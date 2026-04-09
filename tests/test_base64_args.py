"""Base64 query-parameter coercion.

Exercises the three forms:

* ``?foo=literal``                               → plain string (existing)
* ``?foo_b64=<b64>``                             → decoded UTF-8 string
* ``?foo_file_b64=<b64>&foo_file_name=...``      → raw bytes + metadata

Plus the collision and error paths.
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from freemygpt.app import _decode_b64, create_app
from freemygpt.backends.base import Backend, ToolInfo, ToolResult
from freemygpt.config import AuthConfig, BackendConfig, BridgeConfig


class EchoBackend(Backend):
    """Fake backend that echoes whatever arguments it received."""

    name = "echo"
    last_args: dict[str, Any] = {}

    def __init__(self, *_: Any, **__: Any) -> None:
        pass

    async def start(self) -> None:
        return None

    async def list_tools(self) -> list[ToolInfo]:
        return [ToolInfo(name="echo", description="echo")]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float,
    ) -> ToolResult:
        EchoBackend.last_args = arguments
        # Turn any bytes fields into a short hex summary so the assertions
        # can reason about them through the JSON wire format.
        summary: dict[str, Any] = {}
        for k, v in arguments.items():
            if isinstance(v, bytes):
                summary[k] = {"__bytes_hex__": v.hex(), "len": len(v)}
            elif isinstance(v, dict) and isinstance(v.get("bytes"), bytes):
                summary[k] = {
                    "__file__": True,
                    "bytes_hex": v["bytes"].hex(),
                    "name": v.get("name"),
                    "mime": v.get("mime"),
                    "size": v.get("size"),
                }
            else:
                summary[k] = v
        import json as _json

        return ToolResult(text=_json.dumps(summary))

    async def close(self) -> None:
        return None


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FREEMYGPT_TOKEN", "testtoken")
    cfg = BridgeConfig(
        auth=AuthConfig(token_env="FREEMYGPT_TOKEN"),
        backends={
            "echo": BackendConfig(
                name="echo", type="mcp", command="ignored", args=[], default_timeout_s=5.0
            )
        },
    )
    monkeypatch.setattr("freemygpt.app._build_backend", lambda _: EchoBackend())
    app = create_app(cfg=cfg, session_db_path=tmp_path / "sessions.db")
    return TestClient(app)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


# ── _decode_b64 directly ─────────────────────────────────


class TestDecodeB64:
    def test_standard(self) -> None:
        assert _decode_b64("aGVsbG8=") == b"hello"

    def test_urlsafe(self) -> None:
        assert _decode_b64("aGVsbG8") == b"hello"  # unpadded
        assert _decode_b64("aGVsbG8gd29ybGQ") == b"hello world"

    def test_roundtrip_binary(self) -> None:
        payload = bytes(range(256))
        encoded = _b64(payload)
        assert _decode_b64(encoded) == payload

    def test_empty_rejected(self) -> None:
        with pytest.raises(ValueError, match="empty"):
            _decode_b64("")

    def test_garbage_rejected(self) -> None:
        with pytest.raises(ValueError, match="invalid base64"):
            _decode_b64("!!!not-base64!!!")

    def test_url_safe_chars(self) -> None:
        # `+` and `/` are valid standard-base64 chars that also need to work.
        standard = base64.b64encode(b"hello+world/").decode("ascii")
        assert _decode_b64(standard) == b"hello+world/"


# ── String base64 via ?key_b64 ───────────────────────────


class TestStringB64:
    def test_plain_string_still_works(self, client: TestClient) -> None:
        r = client.get("/echo/call/echo", params={"token": "testtoken", "message": "hi"})
        assert r.status_code == 200
        assert EchoBackend.last_args["message"] == "hi"

    def test_b64_string_decoded(self, client: TestClient) -> None:
        text = "hello from base64 — with emoji ✨"
        r = client.get(
            "/echo/call/echo",
            params={"token": "testtoken", "message_b64": _b64(text.encode("utf-8"))},
        )
        assert r.status_code == 200
        assert EchoBackend.last_args["message"] == text

    def test_b64_with_reserved_chars(self, client: TestClient) -> None:
        """Values with &=% can't be sent plain; base64 is the only path."""
        text = "a=1&b=2&c=3%20space"
        r = client.get(
            "/echo/call/echo",
            params={"token": "testtoken", "query_b64": _b64(text.encode("utf-8"))},
        )
        assert r.status_code == 200
        assert EchoBackend.last_args["query"] == text

    def test_invalid_b64_returns_400(self, client: TestClient) -> None:
        r = client.get(
            "/echo/call/echo",
            params={"token": "testtoken", "message_b64": "!!!not-base64!!!"},
        )
        assert r.status_code == 400
        assert "base64" in r.json()["detail"].lower()

    def test_non_utf8_in_string_b64_returns_400(self, client: TestClient) -> None:
        """Binary bytes in ``*_b64`` must surface a clear error pointing at ``*_file_b64``."""
        r = client.get(
            "/echo/call/echo",
            params={"token": "testtoken", "payload_b64": _b64(b"\xff\xfe\xfd")},
        )
        assert r.status_code == 400
        assert "payload_file_b64" in r.json()["detail"]


# ── Binary file base64 via ?key_file_b64 ────────────────


class TestFileB64:
    def test_binary_upload(self, client: TestClient) -> None:
        png_header = bytes.fromhex("89504e470d0a1a0a0000000d49484452")
        r = client.get(
            "/echo/call/echo",
            params={
                "token": "testtoken",
                "image_file_b64": _b64(png_header),
                "image_file_name": "hero.png",
                "image_file_mime": "image/png",
            },
        )
        assert r.status_code == 200
        # The EchoBackend stringifies its args into ``text``. Parse it.
        import json as _json

        echoed = _json.loads(r.json()["text"])
        assert echoed["image"]["__file__"] is True
        assert echoed["image"]["bytes_hex"] == png_header.hex()
        assert echoed["image"]["name"] == "hero.png"
        assert echoed["image"]["mime"] == "image/png"
        assert echoed["image"]["size"] == len(png_header)

    def test_file_b64_defaults_mime_and_name(self, client: TestClient) -> None:
        r = client.get(
            "/echo/call/echo",
            params={"token": "testtoken", "blob_file_b64": _b64(b"anything")},
        )
        assert r.status_code == 200
        import json as _json

        echoed = _json.loads(r.json()["text"])
        assert echoed["blob"]["mime"] == "application/octet-stream"
        assert echoed["blob"]["name"] == ""
        assert echoed["blob"]["size"] == len(b"anything")

    def test_invalid_file_b64_returns_400(self, client: TestClient) -> None:
        r = client.get(
            "/echo/call/echo",
            params={"token": "testtoken", "blob_file_b64": "xxx%%%"},
        )
        assert r.status_code == 400


# ── Collision between plain and base64 ──────────────────


class TestCollision:
    def test_b64_wins_plain_preserved(self, client: TestClient) -> None:
        r = client.get(
            "/echo/call/echo",
            params={
                "token": "testtoken",
                "message": "literal",
                "message_b64": _b64(b"decoded"),
            },
        )
        assert r.status_code == 200
        assert EchoBackend.last_args["message"] == "decoded"
        # Plain form preserved under ``_plain`` for debugging.
        assert EchoBackend.last_args["message_plain"] == "literal"


# ── Interaction with args_json ──────────────────────────


def test_args_json_wins_over_everything(client: TestClient) -> None:
    import json as _json

    r = client.get(
        "/echo/call/echo",
        params={
            "token": "testtoken",
            "message": "plain",
            "message_b64": _b64(b"from_b64"),
            "args_json": _json.dumps({"message": "from_args_json"}),
        },
    )
    assert r.status_code == 200
    assert EchoBackend.last_args["message"] == "from_args_json"
