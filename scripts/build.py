"""Build the portable Windows directory and ZIP. Run with the project virtualenv."""

import os
import shutil
import subprocess
import sys
from importlib.metadata import distribution
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def build_environment() -> dict[str, str]:
    env = os.environ.copy()
    windows = Path(os.environ["SystemRoot"])
    # Native dependency scanners must not pick same-named DLLs from unrelated apps on PATH.
    env["PATH"] = os.pathsep.join(
        str(p)
        for p in (
            Path(sys.executable).parent,
            Path(sys.base_prefix),
            Path(sys.base_prefix) / "DLLs",
            windows / "System32",
            windows,
        )
    )
    return env


def main() -> None:
    os.chdir(ROOT)
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    sys.path.insert(0, str(ROOT))
    from PySide6.QtWidgets import QApplication

    from xiaoyi import __version__
    from xiaoyi.ui import app_icon

    app = QApplication.instance() or QApplication([])
    assets = ROOT / "build" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    icon = assets / "xiaoyi.ico"
    output_root = ROOT / "dist" / __version__
    if not app_icon().pixmap(64, 64).save(str(icon)):
        raise RuntimeError("Failed to create Windows icon")
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            "--onedir",
            "--windowed",
            "--name",
            "HelloXiaoyi",
            "--distpath",
            str(output_root),
            "--icon",
            str(icon),
            "--hidden-import",
            "win32timezone",
            "--hidden-import",
            "win32com.client",
            "--hidden-import",
            "win32cred",
            "--hidden-import",
            "win32clipboard",
            "--collect-data",
            "certifi",
            "--exclude-module",
            "PySide6.QtWebEngineCore",
            "--exclude-module",
            "PySide6.QtWebEngineWidgets",
            "--exclude-module",
            "PySide6.QtQml",
            "--exclude-module",
            "PySide6.QtQuick",
            "--exclude-module",
            "tkinter",
            "--exclude-module",
            "pytest",
            "main.py",
        ],
        check=True,
        env=build_environment(),
    )
    destination = output_root / "HelloXiaoyi"
    for source in ("README.md", "THIRD_PARTY_NOTICES.md"):
        shutil.copy2(ROOT / source, destination / source)
    shutil.copytree(ROOT / "docs", destination / "docs", dirs_exist_ok=True)
    licenses = destination / "licenses"
    licenses.mkdir(exist_ok=True)
    for name in ("edge-tts", "PySide6", "PySide6_Essentials", "PySide6_Addons", "httpx", "pywin32"):
        package = distribution(name)
        for file in package.files or []:
            if "license" in str(file).lower() or "copying" in str(file).lower():
                source = Path(package.locate_file(file))
                if source.is_file():
                    target = licenses / name / str(file).replace("..", "_")
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, target)
    shutil.make_archive(
        str(ROOT / "dist" / f"HelloXiaoyi-{__version__}-windows-x64"),
        "zip",
        output_root,
        "HelloXiaoyi",
    )
    # Keep a reference to QApplication until all icon-related operations are complete.
    app.processEvents()


if __name__ == "__main__":
    main()
