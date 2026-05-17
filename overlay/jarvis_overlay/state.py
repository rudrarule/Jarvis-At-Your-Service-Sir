"""Shared state models for the overlay controller."""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from PyQt6.QtCore import QPoint, QRect
from PyQt6.QtGui import QScreen


class OverlayState(str, Enum):
    IDLE = "idle"
    SELECTING = "selecting"
    AWAITING_QUESTION = "awaiting_question"
    SENDING = "sending"
    SHOWING_RESPONSE = "showing_response"


@dataclass(frozen=True)
class RegionCapture:
    image_bytes: bytes
    screen: QScreen
    rect: QRect
    cursor_pos: QPoint
    device_pixel_ratio: float
