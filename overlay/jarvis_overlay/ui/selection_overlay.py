"""Fullscreen translucent drag-selection overlay."""
from __future__ import annotations

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QKeyEvent, QMouseEvent, QPainter, QPen
from PyQt6.QtWidgets import QWidget

from ..config import OverlayConfig


class SelectionOverlay(QWidget):
    selected = pyqtSignal(object, QRect, QPoint)
    cancelled = pyqtSignal()

    def __init__(self, screen, config: OverlayConfig):
        super().__init__()
        self._screen = screen
        self._config = config
        self._origin: QPoint | None = None
        self._current: QPoint | None = None

        self.setObjectName("SelectionOverlay")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
        self.setGeometry(screen.geometry())

    def keyPressEvent(self, event: QKeyEvent) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.cancelled.emit()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        self._origin = event.position().toPoint()
        self._current = self._origin
        self.update()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._origin is None:
            return
        self._current = event.position().toPoint()
        self.update()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        if event.button() != Qt.MouseButton.LeftButton or self._origin is None:
            return
        self._current = event.position().toPoint()
        local_rect = QRect(self._origin, self._current).normalized()
        self._origin = None
        self._current = None
        if local_rect.width() < self._config.min_selection_px or local_rect.height() < self._config.min_selection_px:
            self.cancelled.emit()
            return
        global_rect = local_rect.translated(self.geometry().topLeft())
        self.selected.emit(self._screen, global_rect, event.globalPosition().toPoint())

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 92))

        if self._origin is None or self._current is None:
            self._draw_reticle_hint(painter)
            return

        selection = QRect(self._origin, self._current).normalized()
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Clear)
        painter.fillRect(selection, QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        painter.setPen(QPen(QColor(97, 224, 255, 230), 2))
        painter.drawRoundedRect(selection.adjusted(1, 1, -1, -1), 8, 8)
        painter.setPen(QPen(QColor(255, 255, 255, 120), 1))
        painter.drawRoundedRect(selection.adjusted(5, 5, -5, -5), 5, 5)

    def _draw_reticle_hint(self, painter: QPainter) -> None:
        center = self.rect().center()
        painter.setPen(QPen(QColor(97, 224, 255, 140), 1))
        painter.drawLine(center.x() - 18, center.y(), center.x() + 18, center.y())
        painter.drawLine(center.x(), center.y() - 18, center.x(), center.y() + 18)
