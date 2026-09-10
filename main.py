from __future__ import annotations

import os
import sys

APP_VERSION = "0.3.b"


def main() -> int:
    if "--version" in sys.argv:
        print(f"UREX MCS Simulator v{APP_VERSION}")
        return 0

    smoke_test = "--smoke-test" in sys.argv
    if smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # Import Qt only after smoke-test environment has been configured. This also
    # keeps --version usable without initializing the GUI runtime.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from gui.main_window import MainWindow

    app = QApplication(sys.argv)
    window = MainWindow()

    if smoke_test:
        # Exercise construction, transport startup, and the event loop without
        # displaying a window. This is used against the frozen Windows EXE.
        QTimer.singleShot(250, app.quit)
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
