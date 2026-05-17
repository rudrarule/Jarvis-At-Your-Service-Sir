"""Best-effort active application metadata for overlay captures."""
from __future__ import annotations

import ctypes
import sys
from pathlib import Path
from typing import Any


def get_active_app_context() -> dict[str, Any]:
    if sys.platform != "win32":
        return {}
    try:
        return _get_windows_context()
    except Exception:
        return {}


def _get_windows_context() -> dict[str, Any]:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return {}

    length = user32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, buffer, length + 1)
    window_title = buffer.value

    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

    process_path = ""
    process_name = ""
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if handle:
        try:
            size = ctypes.c_ulong(32768)
            path_buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, path_buffer, ctypes.byref(size)):
                process_path = path_buffer.value
                process_name = Path(process_path).name
        finally:
            kernel32.CloseHandle(handle)

    return {
        "window_title": window_title,
        "process_id": str(pid.value) if pid.value else "",
        "process_name": process_name,
        "process_path": process_path,
        "app_name": _friendly_app_name(process_name, window_title),
    }


def _friendly_app_name(process_name: str, window_title: str) -> str:
    stem = Path(process_name).stem.lower() if process_name else ""
    names = {
        "code": "Visual Studio Code",
        "chrome": "Google Chrome",
        "msedge": "Microsoft Edge",
        "firefox": "Firefox",
        "windowsterminal": "Windows Terminal",
        "powershell": "PowerShell",
        "cmd": "Command Prompt",
        "acrobat": "Adobe Acrobat",
        "acrord32": "Adobe Reader",
        "winword": "Microsoft Word",
    }
    if stem in names:
        return names[stem]
    if window_title:
        return window_title.split(" - ")[-1][:80]
    return process_name
