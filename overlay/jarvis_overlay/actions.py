"""Quick actions for selected screen context."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OverlayAction:
    action_id: str
    label: str
    prompt: str


QUICK_ACTIONS = [
    OverlayAction("explain", "Explain", "Explain the selected screen region clearly and concisely."),
    OverlayAction("summarize", "Summarize", "Summarize the selected screen region. Focus on what matters."),
    OverlayAction("debug", "Debug", "Identify the likely problem in this selected region and suggest the next fix."),
    OverlayAction("translate", "Translate", "Translate any visible non-English text in the selected region."),
    OverlayAction("ocr", "OCR", "Extract the readable text from this selected region."),
]


def get_action(action_id: str) -> OverlayAction | None:
    return next((action for action in QUICK_ACTIONS if action.action_id == action_id), None)
