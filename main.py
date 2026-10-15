"""Source and frozen application entry point."""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    if sys.platform != "win32":
        print("你好，小译第一版仅支持 Windows。")
        return 1
    from PySide6.QtCore import QTimer, qVersion
    from PySide6.QtNetwork import QLocalServer, QLocalSocket
    from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon

    from xiaoyi import __version__
    from xiaoyi.app import Desktop
    from xiaoyi.config import Settings, load_settings
    from xiaoyi.ui import STYLE, app_icon

    parser = argparse.ArgumentParser(description="你好，小译 / HELLO XIAOYI")
    parser.add_argument("--background", action="store_true")
    parser.add_argument("--smoke-test", type=Path, metavar="REPORT_JSON")
    args = parser.parse_args()
    app = QApplication(sys.argv[:1])
    app.setApplicationName("HelloXiaoyi")
    app.setApplicationDisplayName("你好，小译")
    app.setQuitOnLastWindowClosed(False)
    app.setWindowIcon(app_icon())
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    name = "HelloXiaoyi-v1" + ("-smoke" if args.smoke_test else "")
    socket = QLocalSocket()
    socket.connectToServer(name)
    if socket.waitForConnected(400):
        socket.write(b"settings")
        socket.waitForBytesWritten(400)
        return 0
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
    if not server.listen(name):
        QMessageBox.critical(None, "你好，小译", "无法创建本地单实例通道，请检查是否已运行。")
        return 1
    if not QSystemTrayIcon.isSystemTrayAvailable():
        QMessageBox.critical(None, "你好，小译", "当前环境没有可用的 Windows 系统托盘。")
        return 1
    try:
        settings = Settings() if args.smoke_test else load_settings()
    except ValueError as exc:
        QMessageBox.critical(None, "你好，小译", str(exc))
        return 1
    desktop = Desktop(app, settings)

    def new_connection():
        connection = server.nextPendingConnection()
        if connection:
            connection.close()
            connection.deleteLater()
        desktop.show_settings()

    server.newConnection.connect(new_connection)
    if args.smoke_test:

        def finish_smoke():
            report = {
                "version": __version__,
                "qt": qVersion(),
                "frozen": bool(getattr(sys, "frozen", False)),
                "tray": desktop.tray.isVisible(),
                "hook_thread": desktop.hook.thread.is_alive(),
                "errors": desktop.health_errors,
            }
            args.smoke_test.parent.mkdir(parents=True, exist_ok=True)
            args.smoke_test.write_text(json.dumps(report, indent=2), encoding="utf-8")
            app.quit()

        QTimer.singleShot(1200, finish_smoke)
    elif not args.background:
        desktop.show_settings()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
