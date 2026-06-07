"""System-tray presence — the 'always there' anchor for the ambient assistant.

Left-click (or 'Show') summons the orb; the menu toggles cursor-follow and
start-with-Windows, and quits. The icon is painted at runtime so no asset file
is required.
"""
from __future__ import annotations

from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QIcon, QPainter, QPixmap, QRadialGradient
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


class TrayPresence(QObject):
    show_requested = pyqtSignal()
    capture_requested = pyqtSignal()
    follow_toggled = pyqtSignal(bool)
    autostart_toggled = pyqtSignal(bool)
    quit_requested = pyqtSignal()

    def __init__(self, follow_on: bool = True, autostart_on: bool = False):
        super().__init__()
        self.tray = QSystemTrayIcon(self._make_icon())
        self.tray.setToolTip("J.A.R.V.I.S — Ctrl+Shift+Space")

        menu = QMenu()
        show_action = menu.addAction("Show J.A.R.V.I.S")
        show_action.triggered.connect(self.show_requested.emit)

        capture_action = menu.addAction("Ask about screen…")
        capture_action.triggered.connect(self.capture_requested.emit)

        menu.addSeparator()
        self.follow_action = menu.addAction("Follow cursor")
        self.follow_action.setCheckable(True)
        self.follow_action.setChecked(follow_on)
        self.follow_action.toggled.connect(self.follow_toggled.emit)

        self.autostart_action = menu.addAction("Start with Windows")
        self.autostart_action.setCheckable(True)
        self.autostart_action.setChecked(autostart_on)
        self.autostart_action.toggled.connect(self.autostart_toggled.emit)

        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self.quit_requested.emit)

        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

    def _on_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_requested.emit()

    def _make_icon(self) -> QIcon:
        pix = QPixmap(32, 32)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        grad = QRadialGradient(14, 12, 16)
        grad.setColorAt(0.0, QColor(210, 248, 255))
        grad.setColorAt(0.5, QColor(120, 224, 255))
        grad.setColorAt(1.0, QColor(36, 130, 210))
        p.setBrush(grad)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(4, 4, 24, 24)
        p.end()
        return QIcon(pix)

    def hide(self) -> None:
        self.tray.hide()
