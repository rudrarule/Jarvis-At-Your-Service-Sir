"""Start-with-Windows helper (HKCU Run key). Best-effort and safe to call on any
platform — no-ops cleanly off Windows or if the registry can't be accessed."""
from __future__ import annotations

import sys

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "JARVIS"


def _launch_command() -> str:
    """Command Windows runs at login. Uses the current interpreter to launch the
    overlay package; for a PyInstaller build, sys.executable IS the app exe."""
    exe = sys.executable
    if exe.lower().endswith(("python.exe", "pythonw.exe")):
        return f'"{exe}" -m jarvis_overlay.main'
    return f'"{exe}"'  # packaged single-file app


def is_enabled() -> bool:
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(value)
    except FileNotFoundError:
        return False
    except Exception:
        return False


def set_enabled(enabled: bool) -> bool:
    """Add/remove the autostart entry. Returns True on success."""
    if sys.platform != "win32":
        return False
    try:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            if enabled:
                winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, _launch_command())
            else:
                try:
                    winreg.DeleteValue(key, _VALUE_NAME)
                except FileNotFoundError:
                    pass
        return True
    except Exception:
        return False
