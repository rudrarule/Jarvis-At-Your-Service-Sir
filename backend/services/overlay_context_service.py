"""Short-lived context store for overlay captures and follow-ups."""
from __future__ import annotations

import time
import uuid
from collections import deque
from typing import Any


_MAX_CONTEXTS = 30
_contexts: dict[str, dict[str, Any]] = {}
_history: deque[dict[str, Any]] = deque(maxlen=100)


def create_overlay_context(
    *,
    session_id: str,
    question: str,
    reply: str,
    image_base64: str,
    image_stats: dict[str, Any],
    metadata: dict[str, Any],
    mission_id: str,
) -> str:
    context_id = uuid.uuid4().hex[:12]
    now = time.time()
    record = {
        "context_id": context_id,
        "session_id": session_id,
        "question": question,
        "reply": reply,
        "image_base64": image_base64,
        "image": image_stats,
        "metadata": metadata,
        "mission_id": mission_id,
        "created_at": now,
        "updated_at": now,
        "turns": [{"question": question, "reply": reply, "created_at": now}],
    }
    _contexts[context_id] = record
    _history.appendleft(_public_record(record))
    _trim_contexts()
    return context_id


def get_overlay_context(context_id: str) -> dict[str, Any] | None:
    return _contexts.get(context_id)


def get_overlay_context_public(context_id: str) -> dict[str, Any] | None:
    record = _contexts.get(context_id)
    return _public_record(record) if record else None


def append_overlay_turn(context_id: str, question: str, reply: str) -> None:
    record = _contexts.get(context_id)
    if not record:
        return
    now = time.time()
    record["updated_at"] = now
    record["question"] = question
    record["reply"] = reply
    record.setdefault("turns", []).append({"question": question, "reply": reply, "created_at": now})
    _history.appendleft(_public_record(record))


def list_overlay_history(limit: int = 30) -> list[dict[str, Any]]:
    return list(_history)[: max(0, min(limit, 100))]


def list_overlay_sessions(limit: int = 30) -> list[dict[str, Any]]:
    records = sorted(_contexts.values(), key=lambda item: item.get("updated_at", 0), reverse=True)
    return [_public_record(record) for record in records[: max(0, min(limit, 100))]]


def clear_overlay_history() -> None:
    _contexts.clear()
    _history.clear()


def _trim_contexts() -> None:
    if len(_contexts) <= _MAX_CONTEXTS:
        return
    oldest = sorted(_contexts.items(), key=lambda item: item[1].get("updated_at", 0))
    for context_id, _record in oldest[: len(_contexts) - _MAX_CONTEXTS]:
        _contexts.pop(context_id, None)


def _public_record(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "context_id": record["context_id"],
        "session_id": record["session_id"],
        "question": record["question"],
        "reply": record["reply"],
        "image": record.get("image", {}),
        "metadata": record.get("metadata", {}),
        "mission_id": record.get("mission_id"),
        "created_at": record.get("created_at"),
        "updated_at": record.get("updated_at"),
        "turn_count": len(record.get("turns", [])),
        "turns": list(record.get("turns", [])),
    }
