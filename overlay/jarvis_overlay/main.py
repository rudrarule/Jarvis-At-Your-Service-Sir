"""Entry point for the J.A.R.V.I.S native overlay."""
from __future__ import annotations

import sys

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from .controller import OverlayController


def main() -> int:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("J.A.R.V.I.S Overlay")

    controller = OverlayController()
    controller.start()
    app.aboutToQuit.connect(controller.stop)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
