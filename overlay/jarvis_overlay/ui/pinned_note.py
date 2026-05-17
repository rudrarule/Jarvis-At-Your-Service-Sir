"""Pinned overlay note for keeping answers beside screen context."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget


class PinnedNote(QWidget):
    def __init__(self, text: str, point: QPoint):
        super().__init__()
        self.setObjectName("PinnedNote")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedWidth(340)
        self.setStyleSheet(
            """
            QWidget#PinnedNote {
                background: rgba(11, 18, 28, 232);
                border: 1px solid rgba(92, 225, 255, 112);
                border-radius: 14px;
            }
            QLabel {
                color: #edfaff;
                background: transparent;
                font-size: 13px;
            }
            QPushButton {
                color: rgba(237, 250, 255, 190);
                background: rgba(255, 255, 255, 22);
                border: 1px solid rgba(255, 255, 255, 34);
                border-radius: 9px;
                padding: 3px 8px;
            }
            """
        )

        title = QLabel("Pinned")
        title.setStyleSheet("font-size: 11px; color: rgba(136, 231, 255, 185);")
        close_button = QPushButton("Close")
        close_button.clicked.connect(self.close)

        header = QHBoxLayout()
        header.addWidget(title)
        header.addStretch(1)
        header.addWidget(close_button)

        body = QLabel(text[:1200])
        body.setWordWrap(True)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 12)
        layout.setSpacing(8)
        layout.addLayout(header)
        layout.addWidget(body)

        self._drag_offset: QPoint | None = None
        self.move(point + QPoint(24, 24))
        self.adjustSize()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)

    def mouseReleaseEvent(self, _event: QMouseEvent) -> None:
        self._drag_offset = None
