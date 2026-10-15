"""Desktop orchestration. All widget mutations occur on the Qt GUI thread."""

import os
import time
from dataclasses import replace

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .config import DATA_DIR, Settings, get_key, save_settings, set_key, set_startup
from .core import capture_is_fresh, normalize_text
from .native import (
    KeyboardHook,
    SystemSpeech,
    clipboard_sequence,
    foreground,
    process_id,
    read_clipboard,
)
from .runner import AsyncRunner
from .services import synthesize
from .ui import SettingsWindow, TranslationCard, app_icon


class Desktop:
    def __init__(self, app: QApplication, settings: Settings):
        self.app = app
        self.settings = settings
        self.translation_token = 0
        self.audio_token = 0
        self.test_token = 0
        self.capture_token = 0
        self.translation_started = 0.0
        self.audio_started = 0.0
        self.shutting_down = False
        self.health_errors: list[str] = []
        self.runner = AsyncRunner()
        self.runner.event.connect(self._event)
        self.system = SystemSpeech()
        self.player = QMediaPlayer()
        self.output = QAudioOutput()
        self.player.setAudioOutput(self.output)
        self.output.setVolume(1)
        self.player.errorOccurred.connect(self._playback_error)
        self.card = TranslationCard()
        self.card.speak_requested.connect(lambda: self.speak(self.card.text, self.settings))
        self.card.stop_requested.connect(self.stop_audio)
        self.card.settings_requested.connect(self.show_settings)
        self.card.retry_requested.connect(lambda: self.translate(self.card.text))
        self.card.dismissed.connect(self.dismiss)
        self.window: SettingsWindow | None = None
        self.tray = QSystemTrayIcon(app_icon(), app)
        self.tray.setToolTip("你好，小译 · 已启用 · Ctrl + C C")
        menu = QMenu()
        self.enabled_action = QAction("已启用全局取词", menu)
        self.enabled_action.setCheckable(True)
        self.enabled_action.setChecked(True)
        self.enabled_action.toggled.connect(self.toggle)
        menu.addAction(self.enabled_action)
        menu.addAction("设置", self.show_settings)
        menu.addSeparator()
        menu.addAction("退出你好，小译", app.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.hook = KeyboardHook()
        self.hook.triggered.connect(self.capture)
        self.hook.failed.connect(self._hook_error)
        self.hook.escape_pressed.connect(self.card.close)
        self.hook.start()
        app.aboutToQuit.connect(self.shutdown)

    def _tray_activated(self, reason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self.show_settings()

    def _hook_error(self, message: str) -> None:
        self.health_errors.append(message)
        self.enabled_action.setChecked(False)
        self.notify(message)

    def notify(self, message: str) -> None:
        self.tray.showMessage("你好，小译", message, QSystemTrayIcon.MessageIcon.Warning)
        if self.window:
            self.window.status.setText(message)

    def toggle(self, enabled: bool) -> None:
        if enabled:
            self.hook.enabled.set()
        else:
            self.hook.enabled.clear()
            self.capture_token += 1
            self.card.close()
        self.enabled_action.setText("已启用全局取词" if enabled else "已暂停全局取词")
        self.tray.setToolTip("你好，小译 · " + ("已启用 · Ctrl + C C" if enabled else "已暂停"))

    def show_settings(self) -> None:
        if self.window is None:
            try:
                voices = self.system.voices()
            except Exception:
                voices = []
            self.window = SettingsWindow(self.settings, voices)
            self.window.save_requested.connect(self.save)
            self.window.test_requested.connect(self.test_connection)
            self.window.preview_requested.connect(
                lambda settings: self.speak("Hello Xiaoyi. Attention is all you need.", settings)
            )
            self.window.stop_requested.connect(self.stop_audio)
            self.window.clear_cache_requested.connect(self.clear_audio_cache)
        self.window.show()
        self.window.raise_()
        self.window.activateWindow()

    def save(self, settings: Settings, key: str) -> None:
        try:
            settings.validate()
            set_key(settings.base_url, key)
            set_startup(settings.startup)
            save_settings(settings)
        except (ValueError, OSError, RuntimeError) as exc:
            self.window.status.setText(f"保存失败：{exc}")
            return
        self.settings = replace(settings)
        self.window.current = replace(settings)
        self.dismiss()
        self.window.status.setText("已保存。关闭此窗口后，小译继续在托盘运行。")

    def capture(self, baseline: tuple[int, int]) -> None:
        if not self.hook.enabled.is_set() or process_id(baseline[1]) == os.getpid():
            return
        self.capture_token += 1
        token = self.capture_token
        self.dismiss()
        self.card.hide()
        point = QCursor.pos()
        deadline = time.monotonic() + 0.85

        def poll():
            if token != self.capture_token or not self.hook.enabled.is_set():
                return
            if foreground() != baseline[1]:
                self.notify("取词时前台窗口发生变化，请在原软件重新选择英文。")
                return
            try:
                before_read = clipboard_sequence()
                text = read_clipboard(baseline[1])
                after_read = clipboard_sequence()
                fresh = before_read == after_read and capture_is_fresh(
                    baseline[0], after_read, baseline[1], foreground(), text
                )
            except Exception:
                fresh = False  # Clipboard contention is retried within the bounded capture window.
            if fresh:
                try:
                    text = normalize_text(text)
                except ValueError as exc:
                    self.notify(str(exc))
                    return
                self.card.present(text, point)
                self.translate(text)
                return
            if time.monotonic() < deadline:
                QTimer.singleShot(35, poll)
            else:
                self.notify("未获得新的可复制文字，请重新选中英文后按住 Ctrl 连按两次 C。")

        QTimer.singleShot(35, poll)

    def translate(self, text: str) -> None:
        if not text:
            return
        self.translation_token += 1
        token = self.translation_token
        settings = replace(self.settings)
        self.card.result = ""
        self.card.translation.clear()
        self.card.copy.setEnabled(False)
        self.card.retry.hide()
        self.card.status.setText("正在翻译…")
        self.translation_started = time.monotonic()
        try:
            key = get_key(settings.base_url)
        except RuntimeError as exc:
            self.card.error(str(exc))
            return

        async def translate():
            service = self.runner.translation_service()
            return await service.translate(
                text,
                settings,
                key,
                lambda chunk: self.runner.event.emit("translation:chunk", token, chunk),
            )

        self.runner.submit("translation", token, translate)

    def test_connection(self, settings: Settings, key: str) -> None:
        self.test_token += 1
        self.window.test_button.setEnabled(False)
        self.window.status.setText("正在测试翻译连接…")

        async def test():
            return await self.runner.translation_service().translate(
                "attention", settings, key, lambda _: None
            )

        self.runner.submit("test", self.test_token, test)

    def speak(self, text: str, settings: Settings) -> None:
        if not text:
            return
        self.stop_audio()
        self.audio_started = time.monotonic()
        if settings.speech_backend == "system":
            try:
                self.system.play(text, settings.system_voice, settings.rate)
                self._audio_status("正在使用系统语音朗读。")
            except Exception as exc:
                self._audio_status(
                    str(exc)
                    if isinstance(exc, RuntimeError)
                    else "系统语音启动失败，请重新选择英文声音。"
                )
            return
        self._audio_status("正在生成自然语音…")
        snapshot = replace(settings)
        self.runner.submit(
            "speech",
            self.audio_token,
            lambda: synthesize(text, snapshot, DATA_DIR / "audio"),
        )

    def stop_audio(self) -> None:
        self.audio_token += 1
        self.runner.cancel("speech")
        self.player.stop()
        self.player.setSource(QUrl())
        try:
            self.system.stop()
        except Exception:
            self._audio_status("系统语音停止失败，请退出小译后重新启动。")

    def _audio_status(self, message: str) -> None:
        if self.card.isVisible():
            self.card.status.setText(message)
        if self.window and self.window.isVisible():
            self.window.status.setText(message)

    def _playback_error(self, error, _message: str) -> None:
        if error != QMediaPlayer.Error.NoError:
            self._audio_status("音频播放失败，请清理音频缓存后重试，或切换系统语音。")

    def clear_audio_cache(self) -> None:
        self.stop_audio()

        async def clear():
            count = 0
            for file in (DATA_DIR / "audio").glob("*"):
                if file.suffix in {".mp3", ".part"}:
                    file.unlink(missing_ok=True)
                    count += 1
            return count

        self.runner.submit("clear", 0, clear)

    def dismiss(self) -> None:
        self.translation_token += 1
        self.runner.cancel("translation")
        self.stop_audio()

    def _event(self, kind: str, token: int, payload) -> None:
        if self.shutting_down:
            return
        if kind.startswith("translation:") and token == self.translation_token:
            if kind.endswith("chunk"):
                self.card.append(payload)
            elif kind.endswith("done"):
                self.card.finish(payload)
                elapsed = time.monotonic() - self.translation_started
                self.card.status.setText(f"翻译完成 · {elapsed:.2f} 秒 · 点击朗读原文")
            else:
                self.card.error(payload)
        elif kind.startswith("speech:") and token == self.audio_token:
            if kind.endswith("done"):
                self.player.setSource(QUrl.fromLocalFile(str(payload)))
                self.player.play()
                elapsed = time.monotonic() - self.audio_started
                self._audio_status(f"正在播放英文 · 音频就绪 {elapsed:.2f} 秒")
            else:
                self._audio_status(payload)
        elif kind.startswith("test:") and token == self.test_token:
            self.window.test_button.setEnabled(True)
            self.window.status.setText(
                "连接成功，测试译文：" + payload if kind.endswith("done") else payload
            )
        elif kind.startswith("clear:") and self.window:
            self.window.status.setText(
                f"已清理 {payload} 个音频缓存文件。" if kind.endswith("done") else payload
            )

    def shutdown(self) -> None:
        if self.shutting_down:
            return
        self.shutting_down = True
        self.hook.stop()
        self.stop_audio()
        self.runner.stop()
        self.tray.hide()
