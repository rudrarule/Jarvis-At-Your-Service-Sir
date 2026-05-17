"""Quick action chip palette shown after region capture."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt, pyqtSignal
from PyQt6.QtGui import QGuiApplication, QKeyEvent
from PyQt6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from ..actions import QUICK_ACTIONS


class ActionPalette(QWidget):
    action_selected = pyqtSignal(str)
    ask_selected = pyqtSignal()
    chat_selected = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.setObjectName("ActionPalette")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setStyleSheet(
            """
            QWidget#ActionPalette {
                background: rgba(9, 16, 25, 226);
                border: 1px solid rgba(92, 225, 255, 118);
                border-radius: 14px;
            }
            QPushButton {
                color: #edfaff;
                background: rgba(255, 255, 255, 20);
                border: 1px solid rgba(255, 255, 255, 34);
                border-radius: 10px;
                padding: 7px 10px;
                font-size: 12px;
            }
            QPushButton:hover {
                background: rgba(92, 225, 255, 44);
                border-color: rgba(92, 225, 255, 120);
            }
            """
        )

        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        for action in QUICK_ACTIONS:
            button = QPushButton(action.label)
            button.clicked.connect(lambda _checked=False, action_id=action.action_id: self.action_selected.emit(action_id))
            layout.addWidget(button)

        ask_button = QPushButton("Ask...")
        ask_button.clicked.connect(self.ask_selected.emit)
        layout.addWidget(ask_button)

        chat_button = QPushButton("Chat...")
        chat_button.clicked.connect(self.chat_selected.emit)
        layout.addWidget(chat_button)

    def open_at(self, point: QPoint) -> None:
        self.adjustSize()
        self.move(_clamp_to_screen(point + QPoint(14, 14), self.width(), self.height()))
        self.show()
        self.raise_()
        self.activateWindow()

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()
            return
        super().keyPressEvent(event)


def _clamp_to_screen(point: QPoint, width: int, height: int) -> QPoint:
    screen = QGuiApplication.screenAt(point) or QGuiApplication.primaryScreen()
    geometry = screen.availableGeometry()
    x = min(max(point.x(), geometry.left() + 8), geometry.right() - width - 8)
    y = min(max(point.y(), geometry.top() + 8), geometry.bottom() - height - 8)
    return QPoint(x, y)
