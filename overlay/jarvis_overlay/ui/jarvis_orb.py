"""J.A.R.V.I.S ambient orb — a premium glowing entry point near the cursor.

Evolves the cursor-companion idea into a clickable, animated orb. Pressing the
global hotkey shows it at the cursor; clicking it (or starting to type) asks the
controller to expand into the chat experience.
"""
from __future__ import annotations

import math
import os

from PyQt6.QtCore import (
    QEasingCurve,
    QPoint,
    QPropertyAnimation,
    Qt,
    QTimer,
    pyqtSignal,
)
from PyQt6.QtGui import (
    QColor,
    QCursor,
    QGuiApplication,
    QKeyEvent,
    QMouseEvent,
    QPainter,
    QRadialGradient,
)
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget


class JarvisOrb(QWidget):
    """Small glowing orb that appears near the cursor and expands on click/typing."""

    expand_requested = pyqtSignal(str)  # seed text; "" when clicked
    dismissed = pyqtSignal()

    SIZE = 76  # window box; visible core is smaller, leaving room for the glow

    def __init__(self):
        super().__init__()
        self.setObjectName("JarvisOrb")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(self.SIZE, self.SIZE)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        glow = QGraphicsDropShadowEffect(self)
        glow.setBlurRadius(46)
        glow.setColor(QColor(92, 225, 255, 200))
        glow.setOffset(0, 0)
        self.setGraphicsEffect(glow)

        self._phase = 0.0
        self._hover = False
        self._pulse = QTimer(self)
        self._pulse.timeout.connect(self._tick)
        self._anim: QPropertyAnimation | None = None

        # Companion follow-mode: the orb gently trails the cursor and settles next
        # to it when the pointer stops (so it stays clickable). Disable with
        # JARVIS_ORB_FOLLOW=0 to keep it parked where it first appeared.
        self._follow_enabled = os.getenv("JARVIS_ORB_FOLLOW", "1").strip().lower() not in {"0", "false", "no", "off"}
        self._follow_timer = QTimer(self)
        self._follow_timer.timeout.connect(self._follow)

    # ── lifecycle ────────────────────────────────────────────
    def appear(self, pos: QPoint) -> None:
        target = _clamp_to_screen(pos + QPoint(14, 14), self.width(), self.height())
        self.move(target)
        self.setWindowOpacity(0.0)
        self.show()
        self.raise_()
        self.activateWindow()
        self.setFocus(Qt.FocusReason.OtherFocusReason)
        if not self._pulse.isActive():
            self._pulse.start(33)  # ~30 fps breathing
        if self._follow_enabled and not self._follow_timer.isActive():
            self._follow_timer.start(16)  # ~60 fps smooth follow
        self._fade(1.0, 160)

    def dismiss(self) -> None:
        self._pulse.stop()
        self._follow_timer.stop()
        self.hide()

    def set_follow(self, enabled: bool) -> None:
        """Runtime toggle for companion follow-mode (e.g. from the tray menu)."""
        self._follow_enabled = enabled
        if enabled and self.isVisible() and not self._follow_timer.isActive():
            self._follow_timer.start(16)
        elif not enabled:
            self._follow_timer.stop()

    def _follow(self) -> None:
        """Ease toward the cursor (trailing companion motion). When the pointer is
        still, the orb glides to rest beside it, remaining easy to click."""
        target = _clamp_to_screen(QCursor.pos() + QPoint(18, 20), self.width(), self.height())
        cur = self.pos()
        dx, dy = target.x() - cur.x(), target.y() - cur.y()
        if abs(dx) < 1 and abs(dy) < 1:
            return
        # Lerp ~22% per frame -> smooth trail that settles quickly when idle.
        self.move(cur.x() + round(dx * 0.22), cur.y() + round(dy * 0.22))

    def _fade(self, to: float, ms: int) -> None:
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(ms)
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setEndValue(to)
        self._anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim.start()

    # ── animation ───────────────────────────────────────────
    def _tick(self) -> None:
        self._phase = (self._phase + 0.05) % (2 * math.pi)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        center = self.rect().center()
        cx, cy = float(center.x()), float(center.y())
        breathe = 2.0 * math.sin(self._phase)
        radius = (self.SIZE / 2) - 16 + breathe + (3 if self._hover else 0)

        # Outer halo
        halo = QRadialGradient(cx, cy, radius + 14)
        halo.setColorAt(0.0, QColor(120, 232, 255, 90 if not self._hover else 120))
        halo.setColorAt(1.0, QColor(40, 140, 220, 0))
        painter.setBrush(halo)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(center, int(radius + 14), int(radius + 14))

        # Glowing core
        core = QRadialGradient(cx - 4, cy - 4, radius)
        core.setColorAt(0.0, QColor(212, 248, 255, 255))
        core.setColorAt(0.45, QColor(120, 224, 255, 255))
        core.setColorAt(1.0, QColor(36, 130, 210, 235))
        painter.setBrush(core)
        painter.drawEllipse(center, int(radius), int(radius))

    # ── interaction ─────────────────────────────────────────
    def enterEvent(self, _event) -> None:
        self._hover = True
        self.update()

    def leaveEvent(self, _event) -> None:
        self._hover = False
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.expand_requested.emit("")

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.dismiss()
            self.dismissed.emit()
            return
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space):
            self.expand_requested.emit("")
            return
        text = event.text()
        if text and text.isprintable() and text.strip():
            self.expand_requested.emit(text)


def _clamp_to_screen(point: QPoint, width: int, height: int) -> QPoint:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    geometry = screen.availableGeometry()
    x = min(max(point.x(), geometry.left() + 8), geometry.right() - width - 8)
    y = min(max(point.y(), geometry.top() + 8), geometry.bottom() - height - 8)
    return QPoint(x, y)
