"""Real-time dashboard telemetry for J.A.R.V.I.S."""
from __future__ import annotations

import asyncio
import os
from collections import deque
from datetime import datetime, timezone
from typing import Any

try:
    import psutil
except ImportError:  # pragma: no cover - psutil is declared in requirements.
    psutil = None


_HISTORY_LIMIT = 200
_QUEUE_LIMIT = 100
_IMAGE_KEYS = {"image_base64", "screenshot_base64", "frame_base64"}

_events: deque[dict[str, Any]] = deque(maxlen=_HISTORY_LIMIT)
_subscribers: set[asyncio.Queue] = set()
_event_counter = 0


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _shorten(value: Any, limit: int = 260) -> Any:
    if isinstance(value, dict):
        return {str(k): _shorten(v, limit=limit) for k, v in value.items()}
    if isinstance(value, list):
        return [_shorten(item, limit=limit) for item in value[:8]]
    if isinstance(value, tuple):
        return [_shorten(item, limit=limit) for item in value[:8]]
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def _prepare_wire_payload(value: Any, limit: int = 260) -> Any:
    if isinstance(value, dict):
        prepared = {}
        for key, item in value.items():
            if key in _IMAGE_KEYS and isinstance(item, str):
                prepared[str(key)] = item
            else:
                prepared[str(key)] = _prepare_wire_payload(item, limit=limit)
        return prepared
    if isinstance(value, list):
        return [_prepare_wire_payload(item, limit=limit) for item in value[:20]]
    if isinstance(value, tuple):
        return [_prepare_wire_payload(item, limit=limit) for item in value[:20]]
    if isinstance(value, str) and len(value) > limit:
        return value[: limit - 3] + "..."
    return value


def _enqueue(queue: asyncio.Queue, event: dict[str, Any]) -> None:
    try:
        queue.put_nowait(event)
    except asyncio.QueueFull:
        try:
            queue.get_nowait()
        except asyncio.QueueEmpty:
            pass
        queue.put_nowait(event)


async def emit_dashboard_event(
    event_type: str,
    payload: dict[str, Any] | None = None,
    *,
    source: str = "backend",
    level: str = "info",
) -> dict[str, Any]:
    """Publish an event to all dashboard listeners and keep a short replay history."""
    global _event_counter
    _event_counter += 1
    payload = payload or {}
    wire_event = {
        "id": _event_counter,
        "type": event_type,
        "source": source,
        "level": level,
        "timestamp": _utc_now(),
        "payload": _prepare_wire_payload(payload),
    }
    history_event = {
        **wire_event,
        "payload": _shorten(payload),
    }
    _events.append(history_event)
    _record_persistent_event(history_event)
    for queue in list(_subscribers):
        _enqueue(queue, wire_event)
    return wire_event


def _record_persistent_event(event: dict[str, Any]) -> None:
    try:
        from services.mission_store import record_event

        record_event(event)
    except Exception as exc:
        print(f"[Dashboard] Failed to persist event: {exc}")


def subscribe_dashboard_events() -> asyncio.Queue:
    queue: asyncio.Queue = asyncio.Queue(maxsize=_QUEUE_LIMIT)
    _subscribers.add(queue)
    return queue


def unsubscribe_dashboard_events(queue: asyncio.Queue) -> None:
    _subscribers.discard(queue)


def get_dashboard_history(limit: int = 50) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    return list(_events)[-limit:]


def get_dashboard_snapshot() -> dict[str, Any]:
    from services.mission_store import list_missions

    return {
        "status": "online",
        "subscribers": len(_subscribers),
        "event_count": _event_counter,
        "history": get_dashboard_history(30),
        "health": get_system_health(),
        "missions": list_missions(10),
    }


def get_system_health() -> dict[str, Any]:
    if psutil is None:
        return {
            "cpu_percent": None,
            "memory_percent": None,
            "process_memory_mb": None,
            "llm_tier": _active_llm_tier(),
            "tools": _tool_status(),
        }

    process = psutil.Process(os.getpid())
    memory = psutil.virtual_memory()
    return {
        "cpu_percent": psutil.cpu_percent(interval=None),
        "memory_percent": memory.percent,
        "process_memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
        "llm_tier": _active_llm_tier(),
        "tools": _tool_status(),
    }


def _active_llm_tier() -> str:
    use_claude = os.getenv("USE_CLAUDE", "true").strip().lower() in {"1", "true", "yes", "on"}
    if use_claude:
        return os.getenv("CLAUDE_MODEL_ID", "bedrock").split("/")[-1]
    return os.getenv("OLLAMA_MODEL", "llama3.2:3b")


def _tool_status() -> list[dict[str, str]]:
    return [
        {"label": "Browser", "value": "READY"},
        {"label": "Vision", "value": "READY"},
        {"label": "WhatsApp", "value": "READY"},
        {"label": "Memory", "value": "CHROMA"},
        {"label": "LLM Tier", "value": "BEDROCK" if os.getenv("USE_CLAUDE", "true").lower() == "true" else "LOCAL"},
        {"label": "Guardrail", "value": "ARMED"},
    ]
