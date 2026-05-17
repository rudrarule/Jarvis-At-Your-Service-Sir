"""Cursor-following contextual HUD for the overlay experience."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, QTimer
from PyQt6.QtGui import QCursor, QGuiApplication
from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .styles import CURSOR_HUD_STYLE


class CursorCompanion(QWidget):
    """Small premium HUD that follows the pointer during overlay workflows."""

    def __init__(self):
        super().__init__()
        self.setObjectName("CursorCompanion")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setFixedWidth(230)
        self.setStyleSheet(CURSOR_HUD_STYLE)

        self.title = QLabel("J.A.R.V.I.S Lens")
        self.title.setObjectName("HudTitle")
        self.body = QLabel("Drag to select screen context")
        self.body.setObjectName("HudBody")
        self.body.setWordWrap(True)
        self.hint = QLabel("Esc cancels")
        self.hint.setObjectName("HudHint")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 11)
        layout.setSpacing(4)
        layout.addWidget(self.title)
        layout.addWidget(self.body)
        layout.addWidget(self.hint)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._follow_cursor)

    def start(self, body: str = "Drag to select screen context", hint: str = "Esc cancels") -> None:
        self.body.setText(body)
        self.hint.setText(hint)
        self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(16)
        self._follow_cursor()

    def set_message(self, body: str, hint: str = "") -> None:
        self.body.setText(body)
        self.hint.setText(hint)
        self.adjustSize()

    def stop(self) -> None:
        self._timer.stop()
        self.hide()

    def _follow_cursor(self) -> None:
        point = QCursor.pos() + QPoint(18, 22)
        self.move(_clamp_to_screen(point, self.width(), self.height()))


def _clamp_to_screen(point: QPoint, width: int, height: int) -> QPoint:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    geometry = screen.availableGeometry()
    x = min(max(point.x(), geometry.left() + 8), geometry.right() - width - 8)
    y = min(max(point.y(), geometry.top() + 8), geometry.bottom() - height - 8)
    return QPoint(x, y)
