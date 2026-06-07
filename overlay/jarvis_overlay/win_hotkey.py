"""Reliable OS-level global hotkey via the Win32 RegisterHotKey API.

This is more robust than a software key hook (pynput): Windows delivers the
hotkey to our message loop regardless of which app has focus, and it won't fight
other keyboard hooks. Falls back gracefully — if registration fails, the caller
keeps using the pynput listener.
"""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes

from PyQt6.QtCore import QObject, pyqtSignal

# Modifier + virtual-key constants
MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
VK_SPACE = 0x20
_HOTKEY_ID = 0xA11


class Win32HotkeyListener(QObject):
    """Registers Ctrl+Shift+Space at the OS level and emits ``activated``.

    The signal is emitted from a background thread; because the receiving slot
    lives on the Qt main thread, Qt delivers it via a queued connection.
    """

    activated = pyqtSignal()

    def __init__(self, modifiers: int = MOD_CONTROL | MOD_SHIFT, vk: int = VK_SPACE):
        super().__init__()
        self._modifiers = modifiers | MOD_NOREPEAT
        self._vk = vk
        self._thread: threading.Thread | None = None
        self._thread_id: int | None = None
        self._running = False
        self.available = False  # set True once RegisterHotKey succeeds

    def start(self) -> None:
        if self._thread:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, name="JarvisWin32Hotkey", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread_id is not None:
            try:
                ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            except Exception:
                pass
        self._thread = None
        self._thread_id = None

    def _run(self) -> None:
        try:
            user32 = ctypes.windll.user32
            kernel32 = ctypes.windll.kernel32
            self._thread_id = kernel32.GetCurrentThreadId()

            if not user32.RegisterHotKey(None, _HOTKEY_ID, self._modifiers, self._vk):
                self.available = False
                return
            self.available = True

            msg = wintypes.MSG()
            while self._running:
                ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if ret in (0, -1):  # WM_QUIT or error
                    break
                if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                    self.activated.emit()
        except Exception:
            self.available = False
        finally:
            try:
                ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
            except Exception:
                pass
