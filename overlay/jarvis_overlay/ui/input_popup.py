"""Floating prompt widget shown after a region is selected."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from .styles import INPUT_STYLE


class AskPopup(QWidget):
    submitted = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("AskPopup")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setFixedSize(360, 52)
        self.setStyleSheet(INPUT_STYLE)

        self.input = QLineEdit(self)
        self.input.setPlaceholderText("Ask J.A.R.V.I.S...")
        self.input.returnPressed.connect(self._submit)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.input)

    def open_at(self, point: QPoint, seed: str = "") -> None:
        self.input.setText(seed or "")
        self.move(_clamp_to_screen(point + QPoint(14, 14), self.width(), self.height()))
        self.show()
        self.raise_()
        self.activateWindow()
        self.input.setFocus(Qt.FocusReason.PopupFocusReason)
        if seed:
            self.input.setCursorPosition(len(seed))

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)

    def _submit(self) -> None:
        text = self.input.text().strip()
        if text:
            self.submitted.emit(text)


def _clamp_to_screen(point: QPoint, width: int, height: int) -> QPoint:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    geometry = screen.availableGeometry()
    x = min(max(point.x(), geometry.left() + 8), geometry.right() - width - 8)
    y = min(max(point.y(), geometry.top() + 8), geometry.bottom() - height - 8)
    return QPoint(x, y)
