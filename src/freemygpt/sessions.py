"""Session store — used by the HTTP gateway for stateful chat flows.

Not every backend needs sessions (MCP tool calls are mostly stateless),
but the ``chat`` style that Codex and similar runtimes expose benefits
from a durable transcript so ChatGPT can poll for long-running output
without losing history. We keep this layer minimal — SQLite with two
tables — because the real brain is Gr0m_Mem, and the bridge is just
plumbing.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    backend     TEXT NOT NULL,
    label       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id  TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,     -- 'user' | 'backend' | 'system'
    text        TEXT NOT NULL,
    structured  TEXT,              -- optional JSON
    is_error    INTEGER NOT NULL DEFAULT 0,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);
"""


@dataclass(frozen=True, slots=True)
class Session:
    id: str
    backend: str
    label: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class Message:
    id: int
    session_id: str
    role: str
    text: str
    structured: dict[str, Any] | None
    is_error: bool
    created_at: datetime


class SessionStore:
    """Thread-safe session store.

    FastAPI's sync test client (and any production server with
    multiple workers sharing one process) dispatches endpoints across
    worker threads, so we open the SQLite connection with
    ``check_same_thread=False`` and gate every write with a lock to
    keep the writer path serialized. Reads take the lock too — SQLite
    is fine with multiple concurrent readers in WAL mode, but holding
    one lock is simpler than introducing a connection pool for what
    amounts to a handful of ops per request.
    """

    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path), isolation_level=None, check_same_thread=False
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(_SCHEMA)
        self._lock = threading.RLock()

    # ── Sessions ──────────────────────────────────────────

    def create(self, backend: str, label: str) -> Session:
        sid = str(uuid4())
        now = datetime.now(tz=timezone.utc)
        with self._lock:
            self._conn.execute(
                "INSERT INTO sessions (id, backend, label, created_at) VALUES (?, ?, ?, ?)",
                (sid, backend, label, now.isoformat()),
            )
        return Session(id=sid, backend=backend, label=label, created_at=now)

    def get(self, session_id: str) -> Session | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM sessions WHERE id = ?", (session_id,)
            ).fetchone()
        return self._row_to_session(row) if row else None

    def close(self, session_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "DELETE FROM sessions WHERE id = ?", (session_id,)
            )
        return cur.rowcount > 0

    # ── Messages ──────────────────────────────────────────

    def append(
        self,
        session_id: str,
        role: str,
        text: str,
        structured: dict[str, Any] | None = None,
        is_error: bool = False,
    ) -> Message:
        now = datetime.now(tz=timezone.utc)
        with self._lock:
            cur = self._conn.execute(
                """
                INSERT INTO messages (session_id, role, text, structured, is_error, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_id,
                    role,
                    text,
                    json.dumps(structured) if structured is not None else None,
                    1 if is_error else 0,
                    now.isoformat(),
                ),
            )
            last_row_id = int(cur.lastrowid or 0)
        return Message(
            id=last_row_id,
            session_id=session_id,
            role=role,
            text=text,
            structured=structured,
            is_error=is_error,
            created_at=now,
        )

    def list_messages(
        self, session_id: str, *, since_id: int = 0
    ) -> list[Message]:
        with self._lock:
            rows = self._conn.execute(
                """
                SELECT * FROM messages
                 WHERE session_id = ? AND id > ?
                 ORDER BY id ASC
                """,
                (session_id, since_id),
            ).fetchall()
        return [self._row_to_message(r) for r in rows]

    # ── Helpers ───────────────────────────────────────────

    def _row_to_session(self, row: sqlite3.Row) -> Session:
        return Session(
            id=row["id"],
            backend=row["backend"],
            label=row["label"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        structured = None
        if row["structured"]:
            structured = json.loads(row["structured"])
        return Message(
            id=int(row["id"]),
            session_id=row["session_id"],
            role=row["role"],
            text=row["text"],
            structured=structured,
            is_error=bool(row["is_error"]),
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def close_store(self) -> None:
        self._conn.close()
