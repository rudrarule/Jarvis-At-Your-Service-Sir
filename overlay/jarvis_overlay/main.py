"""Entry point for the J.A.R.V.I.S native overlay."""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from .controller import OverlayController

_SINGLETON = "jarvis_overlay_singleton"


def _summon_existing_instance() -> bool:
    """If an instance is already running, tell it to show and return True.
    Best-effort: any failure means we just launch normally."""
    try:
        from PyQt6.QtNetwork import QLocalSocket

        sock = QLocalSocket()
        sock.connectToServer(_SINGLETON)
        if sock.waitForConnected(200):
            sock.write(b"summon")
            sock.flush()
            sock.waitForBytesWritten(200)
            sock.disconnectFromServer()
            return True
    except Exception:
        pass
    return False


def _install_single_instance_server(controller: OverlayController):
    """Listen for a second launch; on connect, summon the orb. Returns the server
    (kept alive by the caller) or None."""
    try:
        from PyQt6.QtNetwork import QLocalServer

        QLocalServer.removeServer(_SINGLETON)
        server = QLocalServer()
        if not server.listen(_SINGLETON):
            return None

        def _on_new_connection():
            conn = server.nextPendingConnection()
            if conn is not None:
                controller.summon()
                conn.disconnectFromServer()

        server.newConnection.connect(_on_new_connection)
        return server
    except Exception:
        return None


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    # Single-instance: a second launch just summons the running assistant.
    if _summon_existing_instance():
        return 0

    app = QApplication(sys.argv)
    app.setApplicationName("J.A.R.V.I.S Overlay")
    app.setQuitOnLastWindowClosed(False)  # ambient: live in the tray, not a window

    controller = OverlayController()
    _server = _install_single_instance_server(controller)  # noqa: F841 (kept alive)
    controller.start()
    app.aboutToQuit.connect(controller.stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
