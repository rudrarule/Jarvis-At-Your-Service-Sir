"""SQLite mission history for the J.A.R.V.I.S. dashboard."""
from __future__ import annotations

import contextvars
import json
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_CURRENT_MISSION_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "dashboard_current_mission_id",
    default=None,
)

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "dashboard_missions.sqlite3"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _ensure_schema(conn)
    return conn


def _ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS missions (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            title TEXT NOT NULL,
            request TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            duration_ms INTEGER,
            final_answer TEXT,
            error TEXT
        );

        CREATE TABLE IF NOT EXISTS mission_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            mission_id TEXT,
            session_id TEXT,
            event_type TEXT NOT NULL,
            source TEXT,
            level TEXT,
            timestamp TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            FOREIGN KEY(mission_id) REFERENCES missions(id) ON DELETE SET NULL
        );

        CREATE INDEX IF NOT EXISTS idx_missions_created_at ON missions(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_mission_id ON mission_events(mission_id, id);
        """
    )
    conn.commit()


def set_current_mission_id(mission_id: str | None):
    return _CURRENT_MISSION_ID.set(mission_id)


def reset_current_mission_id(token) -> None:
    _CURRENT_MISSION_ID.reset(token)


def get_current_mission_id() -> str | None:
    return _CURRENT_MISSION_ID.get()


def create_mission(session_id: str, request: str) -> dict[str, Any]:
    mission_id = uuid.uuid4().hex[:12]
    now = _utc_now()
    title = _make_title(request)
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO missions (id, session_id, title, request, status, created_at, updated_at)
            VALUES (?, ?, ?, ?, 'running', ?, ?)
            """,
            (mission_id, session_id, title, request, now, now),
        )
        conn.commit()
    return get_mission(mission_id) or {
        "id": mission_id,
        "session_id": session_id,
        "title": title,
        "request": request,
        "status": "running",
        "created_at": now,
        "updated_at": now,
    }


def complete_mission(mission_id: str, final_answer: str, duration_ms: int) -> dict[str, Any] | None:
    now = _utc_now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE missions
            SET status='completed', updated_at=?, completed_at=?, duration_ms=?, final_answer=?
            WHERE id=?
            """,
            (now, now, duration_ms, final_answer, mission_id),
        )
        conn.commit()
    return get_mission(mission_id)


def fail_mission(mission_id: str, error: str, duration_ms: int) -> dict[str, Any] | None:
    now = _utc_now()
    with _connect() as conn:
        conn.execute(
            """
            UPDATE missions
            SET status='failed', updated_at=?, completed_at=?, duration_ms=?, error=?
            WHERE id=?
            """,
            (now, now, duration_ms, error, mission_id),
        )
        conn.commit()
    return get_mission(mission_id)


def list_missions(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM missions
            ORDER BY datetime(created_at) DESC
            LIMIT ?
            """,
            (max(1, min(limit, 100)),),
        ).fetchall()
    return [_row_to_mission(row) for row in rows]


def get_mission(mission_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute("SELECT * FROM missions WHERE id=?", (mission_id,)).fetchone()
    return _row_to_mission(row) if row else None


def get_mission_events(mission_id: str, limit: int = 100) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT *
            FROM mission_events
            WHERE mission_id=?
            ORDER BY id DESC
            LIMIT ?
            """,
            (mission_id, max(1, min(limit, 500))),
        ).fetchall()
    return [_row_to_event(row) for row in reversed(rows)]


def record_event(event: dict[str, Any]) -> None:
    payload = event.get("payload") or {}
    mission_id = _extract_string(payload.get("mission_id")) or get_current_mission_id()
    session_id = _extract_string(payload.get("session_id"))
    timestamp = event.get("timestamp") or _utc_now()
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO mission_events (mission_id, session_id, event_type, source, level, timestamp, payload_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                mission_id,
                session_id,
                event.get("type", "unknown"),
                event.get("source"),
                event.get("level"),
                timestamp,
                json.dumps(_safe_payload(payload), ensure_ascii=True),
            ),
        )
        conn.commit()


def _row_to_mission(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "session_id": row["session_id"],
        "title": row["title"],
        "request": row["request"],
        "status": row["status"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "completed_at": row["completed_at"],
        "duration_ms": row["duration_ms"],
        "final_answer": row["final_answer"],
        "error": row["error"],
    }


def _row_to_event(row: sqlite3.Row) -> dict[str, Any]:
    try:
        payload = json.loads(row["payload_json"])
    except json.JSONDecodeError:
        payload = {}
    return {
        "id": row["id"],
        "mission_id": row["mission_id"],
        "session_id": row["session_id"],
        "type": row["event_type"],
        "source": row["source"],
        "level": row["level"],
        "timestamp": row["timestamp"],
        "payload": payload,
    }


def _make_title(request: str) -> str:
    clean = " ".join(request.strip().split())
    if len(clean) <= 48:
        return clean or "Untitled mission"
    return clean[:45].rstrip() + "..."


def _safe_payload(value: Any, limit: int = 500) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in {"image_base64", "screenshot_base64", "frame_base64"} and isinstance(item, str):
                result[key] = f"<image:{len(item)} chars>"
            else:
                result[str(key)] = _safe_payload(item, limit)
        return result
    if isinstance(value, list):
        return [_safe_payload(item, limit) for item in value[:20]]
    if isinstance(value, tuple):
        return [_safe_payload(item, limit) for item in value[:20]]
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def _extract_string(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None
