"""HTTP gateway end-to-end tests with a fake backend.

We swap in a fake Backend that avoids spawning any real subprocess or
MCP server so CI stays fast and deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from freemygpt.app import create_app
from freemygpt.backends.base import Backend, BackendError, ToolInfo, ToolResult
from freemygpt.config import AuthConfig, BackendConfig, BridgeConfig


class FakeBackend(Backend):
    name = "fake"

    def __init__(self, *_: Any, **__: Any) -> None:
        self.started = False
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def start(self) -> None:
        self.started = True

    async def list_tools(self) -> list[ToolInfo]:
        return [
            ToolInfo(
                name="echo",
                description="Echo a message back.",
                input_schema={
                    "type": "object",
                    "properties": {"message": {"type": "string"}},
                    "required": ["message"],
                },
            ),
            ToolInfo(name="boom", description="Always errors."),
            ToolInfo(name="chat", description="Synthetic chat tool."),
        ]

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        *,
        timeout_s: float,
    ) -> ToolResult:
        self.calls.append((tool_name, arguments))
        if tool_name == "echo":
            return ToolResult(text=f"echo: {arguments.get('message', '')}")
        if tool_name == "chat":
            return ToolResult(text=f"you said: {arguments.get('message', '')}")
        if tool_name == "boom":
            raise BackendError("boom on purpose")
        raise BackendError(f"unknown tool {tool_name}")

    async def close(self) -> None:
        self.started = False


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FREEMYGPT_TOKEN", "testtoken")
    cfg = BridgeConfig(
        auth=AuthConfig(token_env="FREEMYGPT_TOKEN"),
        backends={
            "fake": BackendConfig(
                name="fake",
                type="mcp",  # type is ignored here because we swap the constructor
                command="ignored",
                args=[],
                default_timeout_s=5.0,
            )
        },
    )
    monkeypatch.setattr("freemygpt.app._build_backend", lambda _: FakeBackend())
    app = create_app(cfg=cfg, session_db_path=tmp_path / "sessions.db")
    return TestClient(app)


def test_healthz_is_unauthenticated(client: TestClient) -> None:
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "version" in body


def test_backends_requires_token(client: TestClient) -> None:
    r = client.get("/backends")
    assert r.status_code == 401

    r = client.get("/backends", params={"token": "wrong"})
    assert r.status_code == 401

    r = client.get("/backends", params={"token": "testtoken"})
    assert r.status_code == 200
    assert r.json()["backends"][0]["name"] == "fake"


def test_list_tools(client: TestClient) -> None:
    r = client.get("/fake/tools", params={"token": "testtoken"})
    assert r.status_code == 200
    names = [t["name"] for t in r.json()["tools"]]
    assert names == ["echo", "boom", "chat"]


def test_call_tool_with_query_args(client: TestClient) -> None:
    r = client.get(
        "/fake/call/echo",
        params={"token": "testtoken", "message": "hello"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["is_error"] is False
    assert body["text"] == "echo: hello"


def test_call_tool_with_args_json(client: TestClient) -> None:
    r = client.get(
        "/fake/call/echo",
        params={"token": "testtoken", "args_json": '{"message": "from json"}'},
    )
    assert r.status_code == 200
    assert r.json()["text"] == "echo: from json"


def test_call_tool_error_surfaces_as_502(client: TestClient) -> None:
    r = client.get(
        "/fake/call/boom",
        params={"token": "testtoken"},
    )
    assert r.status_code == 502
    assert "boom on purpose" in r.json()["detail"]


def test_unknown_backend_returns_404(client: TestClient) -> None:
    r = client.get("/nope/tools", params={"token": "testtoken"})
    assert r.status_code == 404


def test_header_based_auth_also_works(client: TestClient) -> None:
    r = client.get("/backends", headers={"Authorization": "Bearer testtoken"})
    assert r.status_code == 200


def test_session_round_trip(client: TestClient) -> None:
    # Create a session.
    r = client.get(
        "/fake/sessions/new",
        params={"token": "testtoken", "label": "demo"},
    )
    assert r.status_code == 200
    sid = r.json()["session_id"]

    # Send a message.
    r = client.get(
        f"/fake/sessions/{sid}/send",
        params={"token": "testtoken", "message": "hi"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "you said: hi"

    # Poll for the full transcript.
    r = client.get(
        f"/fake/sessions/{sid}/poll",
        params={"token": "testtoken", "since": 0},
    )
    assert r.status_code == 200
    messages = r.json()["messages"]
    roles = [m["role"] for m in messages]
    assert roles == ["user", "backend"]
    assert messages[0]["text"] == "hi"
    assert messages[1]["text"] == "you said: hi"

    # Close the session.
    r = client.get(
        f"/fake/sessions/{sid}/close",
        params={"token": "testtoken"},
    )
    assert r.status_code == 200
    assert r.json()["closed"] is True


def test_session_on_wrong_backend_returns_404(client: TestClient) -> None:
    r = client.get(
        "/fake/sessions/new",
        params={"token": "testtoken"},
    )
    sid = r.json()["session_id"]
    # Try to poll via a nonexistent backend.
    r = client.get(
        f"/bogus/sessions/{sid}/poll",
        params={"token": "testtoken"},
    )
    assert r.status_code == 404
