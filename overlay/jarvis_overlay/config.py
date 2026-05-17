"""Runtime configuration for the native overlay client."""
from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class OverlayConfig:
    backend_url: str = os.getenv("JARVIS_BACKEND_URL", "http://localhost:8082").rstrip("/")
    session_id: str = os.getenv("JARVIS_OVERLAY_SESSION_ID", "overlay")
    request_timeout_s: float = float(os.getenv("JARVIS_OVERLAY_TIMEOUT", "90"))
    min_selection_px: int = int(os.getenv("JARVIS_OVERLAY_MIN_SELECTION", "12"))


CONFIG = OverlayConfig()
