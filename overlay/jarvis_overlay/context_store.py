"""Local overlay context and history store."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .state import RegionCapture


HISTORY_PATH = Path.home() / ".jarvis_overlay" / "history.json"


@dataclass
class OverlayInteraction:
    question: str
    reply: str
    context_id: str | None
    mission_id: str | None
    created_at: float
    image: dict[str, Any]
    turns: list[dict[str, Any]]
    metadata: dict[str, Any]


class OverlayContextStore:
    def __init__(self, history_path: Path = HISTORY_PATH):
        self.history_path = history_path
        self.last_capture: RegionCapture | None = None
        self.last_context_id: str | None = None
        self.last_reply: str = ""
        self.current_turns: list[dict[str, Any]] = []
        self.current_metadata: dict[str, Any] = {}

    def begin_session(self, capture: RegionCapture, metadata: dict[str, Any] | None = None) -> None:
        self.last_capture = capture
        self.last_context_id = None
        self.last_reply = ""
        self.current_turns = []
        self.current_metadata = metadata or {}

    def set_capture(self, capture: RegionCapture) -> None:
        self.last_capture = capture

    def remember_response(self, question: str, payload: dict[str, Any]) -> None:
        self.last_context_id = payload.get("context_id") or self.last_context_id
        self.last_reply = str(payload.get("reply") or "")
        turns = payload.get("turns")
        last_backend_question = ""
        if isinstance(turns, list) and turns:
            last_backend_question = str((turns[-1] or {}).get("question") or "")
        if isinstance(turns, list) and turns and (not self.current_turns or last_backend_question == question):
            self.current_turns = turns
        else:
            self.current_turns.append({"question": question, "reply": self.last_reply, "created_at": time.time()})
        metadata = payload.get("metadata")
        if isinstance(metadata, dict):
            self.current_metadata = {**self.current_metadata, **metadata}
        interaction = OverlayInteraction(
            question=question,
            reply=self.last_reply,
            context_id=self.last_context_id,
            mission_id=payload.get("mission_id"),
            created_at=time.time(),
            image=payload.get("image") or {},
            turns=self.current_turns,
            metadata=self.current_metadata,
        )
        self._append_history(interaction)

    def _append_history(self, interaction: OverlayInteraction) -> None:
        self.history_path.parent.mkdir(parents=True, exist_ok=True)
        history = self.load_history()
        history.insert(0, interaction.__dict__)
        history = history[:100]
        self.history_path.write_text(json.dumps(history, indent=2), encoding="utf-8")

    def load_history(self) -> list[dict[str, Any]]:
        if not self.history_path.exists():
            return []
        try:
            return json.loads(self.history_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return []
