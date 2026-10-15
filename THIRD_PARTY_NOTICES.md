# 第三方组件

便携包使用动态 Qt 库，并在 `licenses/` 中附带可从已安装分发包提取的许可证文件。原始源码、完整许可与替换库的构建信息可从下列官方项目获取；项目保留可复现构建脚本，未修改这些上游组件。

| 组件 | 上游与许可 |
| --- | --- |
| Python | https://www.python.org/ — PSF |
| PySide6 / Qt | https://www.qt.io/qt-for-python — LGPL / GPL / commercial alternatives; Qt module-specific terms apply |
| edge-tts | https://github.com/rany2/edge-tts — see bundled upstream license |
| httpx / httpcore | https://github.com/encode/httpx — BSD-3-Clause |
| pywin32 | https://github.com/mhammond/pywin32 — PSF |
| aiohttp | https://github.com/aio-libs/aiohttp — Apache-2.0 AND MIT (component-specific) |
| PyInstaller bootloader | https://pyinstaller.org/ — GPL with bootloader exception |

Qt Multimedia 可能包含 FFmpeg 动态组件，详见随库分发的许可与 https://doc.qt.io/qt-6/qtmultimedia-attribution-ffmpeg.html 。其他传递依赖以安装包内的 LICENSE / COPYING 为准。当前仓库为私有测试项目，未对项目自有源码授予公开开源许可。
