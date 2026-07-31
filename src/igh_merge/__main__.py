from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from .gui import MainWindow

_OPEN_WINDOWS: list[MainWindow] = []


def main() -> int:
    app = QApplication.instance()
    owns_event_loop = app is None
    if app is None:
        app = QApplication(sys.argv)
    app.setApplicationName("IGH Merge")
    window = MainWindow()
    _OPEN_WINDOWS.append(window)
    window.destroyed.connect(
        lambda: _OPEN_WINDOWS.remove(window) if window in _OPEN_WINDOWS else None
    )
    window.show()
    return app.exec() if owns_event_loop else 0


if __name__ == "__main__":
    raise SystemExit(main())
