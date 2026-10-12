from __future__ import annotations

import os
import sys
import argparse

APP_VERSION = "1.0"


def main() -> int:
    if "--version" in sys.argv:
        print(f"UREX MCS Simulator v{APP_VERSION}")
        return 0

    parser = argparse.ArgumentParser(description="UREX simulator and ZeroMQ MCS interface")
    parser.add_argument("--network", action="store_true", help="open the real network monitor")
    parser.add_argument("--bind", default="tcp://127.0.0.1:5557", help="MCS ZeroMQ listen endpoint")
    parser.add_argument("--log-dir", default="logs/mcs")
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    smoke_test = args.smoke_test
    if smoke_test:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    # Import Qt only after smoke-test environment has been configured. This also
    # keeps --version usable without initializing the GUI runtime.
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    app = QApplication([sys.argv[0]])
    if args.network:
        from gui.integration_window import IntegrationWindow
        window = IntegrationWindow(args.bind, args.log_dir)
    else:
        from gui.main_window import MainWindow
        window = MainWindow()
    app.aboutToQuit.connect(window.close)

    if smoke_test:
        # Exercise construction, transport startup, and the event loop without
        # displaying a window. This is used against the frozen Windows EXE.
        QTimer.singleShot(250, app.quit)
    else:
        window.show()

    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
