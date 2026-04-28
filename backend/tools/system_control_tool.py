"""
system_control_tool.py — Secure OS Control for J.A.R.V.I.S.

Provides safe system control via whitelisted applications, validated paths,
and confirmation-required destructive actions.
"""
import subprocess
import psutil
import os
from typing import Tuple


# ── Security Configuration ─────────────────────────────────────
# Whitelist of allowed applications (name → executable path)
ALLOWED_APPS = {
    "chrome": r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "firefox": r"C:\Program Files\Mozilla Firefox\firefox.exe",
    "edge": r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "vscode": r"C:\Users\Rudra\AppData\Local\Programs\Microsoft VS Code\Code.exe",
    "notepad": r"C:\Windows\System32\notepad.exe",
    "calc": r"C:\Windows\System32\calc.exe",
    "terminal": r"C:\Windows\System32\cmd.exe",
    "explorer": r"C:\Windows\explorer.exe",
    "spotify": r"C:\Users\Rudra\AppData\Local\Microsoft\WindowsApps\Spotify.exe",
    "discord": r"C:\Users\Rudra\AppData\Local\Discord\app-1.0.9016\Discord.exe",
}

# UWP / Microsoft Store apps (name → shell launch command)
STORE_APPS = {
    "netflix": "shell:AppsFolder\\4DF9E0F8.Netflix_mcm4njqhnhss8!Netflix.App",
    "whatsapp": "whatsapp:",
    "telegram": "tg:",
    "xbox": "xbox:",
    "photos": "ms-photos:",
    "settings": "ms-settings:",
    "store": "ms-windows-store:",
    "maps": "bingmaps:",
}

# Safe folder mappings (friendly name → absolute path)
SAFE_DIRS = {
    "desktop": os.path.join(os.path.expanduser("~"), "Desktop"),
    "downloads": os.path.join(os.path.expanduser("~"), "Downloads"),
    "documents": os.path.join(os.path.expanduser("~"), "Documents"),
    "pictures": os.path.join(os.path.expanduser("~"), "Pictures"),
    "workspace": os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "workspace")),
}

# Allowed base paths for open_folder (prevent traversal)
ALLOWED_FOLDER_PATHS = list(SAFE_DIRS.values())


# ── Utility / Security Layer ──────────────────────────────────
def validate_folder_path(folder_name: str) -> str:
    """
    Validates that the requested folder is in SAFE_DIRS and the path is safe.
    Returns the absolute safe path, or raises ValueError.
    """
    folder_lower = folder_name.lower().strip()

    if folder_lower not in SAFE_DIRS:
        raise ValueError(f"Folder '{folder_name}' is not in the allowed list.")

    path = SAFE_DIRS[folder_lower]

    # Verify path exists
    if not os.path.exists(path):
        raise ValueError(f"Folder '{folder_name}' does not exist on this system.")

    return path


def find_process_by_name(app_name: str) -> psutil.Process:
    """
    Find a running process by name (case-insensitive partial match).
    Returns the process or None if not found.
    """
    app_lower = app_name.lower()
    for proc in psutil.process_iter(["name", "pid"]):
        try:
            proc_name = proc.info["name"] or ""
            if app_lower in proc_name.lower():
                return proc
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return None


# ── Tool Implementations ──────────────────────────────────────

def open_app(app_name: str) -> str:
    """
    Open a whitelisted application.
    Supports both traditional exe apps and UWP/Store apps via protocol URIs.
    """
    try:
        app_lower = app_name.lower().strip()

        # Check UWP/Store apps first (protocol URI)
        if app_lower in STORE_APPS:
            protocol = STORE_APPS[app_lower]
            os.startfile(protocol)
            display_name = app_name.title()
            return f"Opening {display_name}, sir."

        if app_lower not in ALLOWED_APPS:
            available = ", ".join(list(ALLOWED_APPS.keys()) + list(STORE_APPS.keys()))
            return f"I'm sorry, sir. '{app_name}' is not in my allowed applications list. Available: {available}."

        app_path = ALLOWED_APPS[app_lower]

        if not os.path.exists(app_path):
            return f"I'm sorry, sir. The application '{app_name}' is not installed at the expected path."

        subprocess.Popen([app_path], shell=False)
        display_name = app_name.title()
        return f"Opening {display_name}, sir."

    except PermissionError:
        return f"I'm sorry, sir. I don't have permission to open {app_name}."
    except FileNotFoundError:
        return f"I'm sorry, sir. The application '{app_name}' was not found."
    except Exception as e:
        return f"I encountered an error opening {app_name}, sir: {str(e)}"


def close_app(app_name: str) -> str:
    """
    Close a running application by name.
    Uses psutil to find and terminate the process gracefully.
    """
    try:
        app_lower = app_name.lower().strip()

        process = find_process_by_name(app_lower)

        if process is None:
            return f"{app_name.title()} is not currently running, sir."

        process.terminate()
        process.wait(timeout=3)
        return f"Closed {app_name.title()}, sir."

    except psutil.TimeoutExpired:
        # Force kill if terminate doesn't work
        try:
            process.kill()
            return f"Force closed {app_name.title()}, sir."
        except Exception:
            return f"I'm sorry, sir. {app_name.title()} refused to close."
    except psutil.NoSuchProcess:
        return f"{app_name.title()} is not running, sir."
    except Exception as e:
        return f"I encountered an error closing {app_name}, sir: {str(e)}"


def open_folder(folder_name: str) -> str:
    """
    Open a safe, predefined folder in Windows Explorer.
    Uses os.startfile (Windows) for native behavior.
    """
    try:
        safe_path = validate_folder_path(folder_name)
        os.startfile(safe_path)
        display_name = folder_name.title()
        return f"Opening {display_name} folder, sir."

    except ValueError as e:
        return f"I'm sorry, sir. {str(e)}"
    except PermissionError:
        return f"I'm sorry, sir. I don't have permission to access that folder."
    except Exception as e:
        return f"I encountered an error opening the folder, sir: {str(e)}"


def lock_system() -> str:
    """
    Lock the Windows workstation immediately.
    Uses rundll32.exe user32.dll,LockWorkStation
    """
    try:
        subprocess.run(
            ["rundll32.exe", "user32.dll,LockWorkStation"],
            shell=False,
            check=True
        )
        return "Locking the system, sir."
    except Exception as e:
        return f"I encountered an error locking the system, sir: {str(e)}"


def shutdown_system(confirm: bool) -> str:
    """
    Shutdown the system.
    REQUIRES explicit confirmation (confirm=True) to execute.
    """
    if not confirm:
        return "Please confirm before shutting down, sir. Say 'shutdown system confirm' to proceed."

    try:
        subprocess.run(
            ["shutdown", "/s", "/t", "0"],
            shell=False,
            check=True
        )
        return "Shutting down now, sir."
    except Exception as e:
        return f"I encountered an error shutting down, sir: {str(e)}"


def restart_system(confirm: bool) -> str:
    """
    Restart the system.
    REQUIRES explicit confirmation (confirm=True) to execute.
    """
    if not confirm:
        return "Please confirm before restarting, sir. Say 'restart system confirm' to proceed."

    try:
        subprocess.run(
            ["shutdown", "/r", "/t", "0"],
            shell=False,
            check=True
        )
        return "Restarting now, sir."
    except Exception as e:
        return f"I encountered an error restarting, sir: {str(e)}"


def list_running_apps() -> str:
    """
    List currently running applications (user-facing processes).
    Useful for debugging or when user asks "what's open".
    """
    try:
        apps = []
        for proc in psutil.process_iter(["name", "pid"]):
            try:
                name = proc.info["name"] or ""
                # Filter out system processes
                if name and not name.startswith("System") and name.lower() not in ["idle", "system"]:
                    apps.append(name)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if not apps:
            return "No user applications currently running, sir."

        # Deduplicate and limit output
        unique_apps = list(dict.fromkeys(apps))[:15]
        return f"Currently running: {', '.join(unique_apps)}" + (f" and {len(apps) - 15} more." if len(apps) > 15 else ".")

    except Exception as e:
        return f"I encountered an error listing applications, sir: {str(e)}"
