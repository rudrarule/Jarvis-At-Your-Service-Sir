"""HiDPI-aware screen-region capture helpers."""
from __future__ import annotations

from PyQt6.QtCore import QByteArray, QBuffer, QIODevice, QPoint, QRect
from PyQt6.QtGui import QGuiApplication, QScreen

from .state import RegionCapture


def capture_region(screen: QScreen, global_rect: QRect, cursor_pos: QPoint) -> RegionCapture:
    """Capture a selected global screen rect as PNG bytes."""
    rect = global_rect.normalized()
    pixmap = screen.grabWindow(0, rect.x(), rect.y(), rect.width(), rect.height())
    if pixmap.isNull():
        raise RuntimeError("Selected region could not be captured.")

    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    pixmap.save(buffer, "PNG")
    data = bytes(QByteArray(buffer.data()))
    buffer.close()

    return RegionCapture(
        image_bytes=data,
        screen=screen,
        rect=rect,
        cursor_pos=cursor_pos,
        device_pixel_ratio=screen.devicePixelRatio(),
    )


def screen_for_point(point: QPoint) -> QScreen:
    screen = QGuiApplication.screenAt(point)
    return screen or QGuiApplication.primaryScreen()
