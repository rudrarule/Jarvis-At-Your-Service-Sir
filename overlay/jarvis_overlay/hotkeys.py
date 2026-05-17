"""Global hotkey listener for Ctrl+Shift+Space."""
from __future__ import annotations

from PyQt6.QtCore import QObject, pyqtSignal
from pynput import keyboard


class GlobalHotkeyListener(QObject):
    activated = pyqtSignal()

    def __init__(self):
        super().__init__()
        self._pressed: set[keyboard.Key] = set()
        self._listener: keyboard.Listener | None = None
        self._fired_until_release = False

    def start(self) -> None:
        if self._listener:
            return
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.daemon = True
        self._listener.start()

    def stop(self) -> None:
        if self._listener:
            self._listener.stop()
            self._listener = None
        self._pressed.clear()

    def _on_press(self, key) -> None:
        normalized = _normalize_key(key)
        if normalized:
            self._pressed.add(normalized)
        if not self._fired_until_release and {
            keyboard.Key.ctrl,
            keyboard.Key.shift,
            keyboard.Key.space,
        }.issubset(self._pressed):
            self._fired_until_release = True
            self.activated.emit()

    def _on_release(self, key) -> None:
        normalized = _normalize_key(key)
        if normalized:
            self._pressed.discard(normalized)
        if normalized in {keyboard.Key.ctrl, keyboard.Key.shift, keyboard.Key.space}:
            self._fired_until_release = False


def _normalize_key(key):
    if key in (keyboard.Key.ctrl_l, keyboard.Key.ctrl_r):
        return keyboard.Key.ctrl
    if key in (keyboard.Key.shift_l, keyboard.Key.shift_r):
        return keyboard.Key.shift
    return key
