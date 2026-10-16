"""Desktop orchestration. All widget mutations occur on the Qt GUI thread."""

import os
import time
from dataclasses import replace

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QAction, QCursor
from PySide6.QtMultimedia import QAudioOutput, QMediaDevices, QMediaPlayer
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
        self.source_window = 0
        self.translation_started = 0.0
        self.audio_resume_position = 0
        self.audio_session: tuple | None = None
        self.audio_phase = "idle"
        self.shutting_down = False
        self.health_errors: list[str] = []
        self.runner = AsyncRunner()
        self.runner.event.connect(self._event)
        self.system = SystemSpeech()
        self._replace_player()
        self.media_devices = QMediaDevices(app)
        self.media_devices.audioOutputsChanged.connect(self._output_devices_changed)
        self.card = TranslationCard()
        self.card.speak_requested.connect(lambda: self.speak(self.card.text, self.settings))
        self.card.stop_requested.connect(self.stop_audio)
        self.card.recover_requested.connect(self.recover_audio)
        self.card.settings_requested.connect(self.show_settings)
        self.card.retry_requested.connect(lambda: self.translate(self.card.text))
        self.card.dismissed.connect(self.dismiss)
        self.card.auto_hidden.connect(self.cancel_translation)
        self.audio_timer = QTimer(self.card)
        self.audio_timer.setInterval(250)
        self.audio_timer.timeout.connect(self._audio_progress)
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
        menu.addAction("停止朗读", self.stop_audio)
        menu.addSeparator()
        menu.addAction("退出你好，小译", app.quit)
        self.menu = menu
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._tray_activated)
        self.tray.show()
        self.hook = KeyboardHook()
        self.hook.triggered.connect(self.capture)
        self.hook.failed.connect(self._hook_error)
        self.hook.escape_pressed.connect(self.escape)
        self.hook.start()
        self.foreground_timer = QTimer(self.card)
        self.foreground_timer.setInterval(150)
        self.foreground_timer.timeout.connect(self._watch_foreground)
        self.foreground_timer.start()
        app.aboutToQuit.connect(self.shutdown)

    def _replace_player(self) -> None:
        old_player = getattr(self, "player", None)
        old_output = getattr(self, "output", None)
        player = QMediaPlayer()
        self.player = player
        self.output = QAudioOutput(QMediaDevices.defaultAudioOutput())
        player.setAudioOutput(self.output)
        self.output.setVolume(1)
        token = self.audio_token

        def current() -> bool:
            # stop_audio invalidates this binding even while the next MP3 is downloading.
            return self.player is player and token == self.audio_token

        player.errorOccurred.connect(
            lambda error, message: self._playback_error(error, message) if current() else None
        )
        player.mediaStatusChanged.connect(
            lambda status: self._media_status(status) if current() else None
        )
        player.playbackStateChanged.connect(
            lambda state: self._playback_state(state) if current() else None
        )
        if old_player is not None:
            old_player.stop()
            old_player.setAudioOutput(None)
            old_player.setSource(QUrl())
            old_player.deleteLater()
            old_output.deleteLater()

    def recover_audio(self) -> None:
        if (
            not self.audio_session
            or self.audio_session[1] != "online"
            or self.audio_phase != "playing"
            or self.player.source().isEmpty()
        ):
            return
        source = self.player.source()
        position = max(0, self.player.position() - 1000)
        self._start_playback(source, position)

    def _start_playback(self, source: QUrl, position: int = 0) -> None:
        self.audio_phase = "generating"
        self.audio_timer.stop()
        self.card.recover.setEnabled(False)
        self._replace_player()
        if self.output.device().isNull():
            self._finish_audio()
            self._audio_status("未找到音频设备，请连接耳机或扬声器后重新朗读。")
            return
        self.audio_resume_position = position
        self.player.setSource(source)
        if self.audio_session:
            self._audio_status(f"正在连接音频输出：{self.output.device().description()}")

    def _output_devices_changed(self) -> None:
        if not self.audio_session or self.audio_session[1] != "online":
            return
        if self.audio_phase != "playing":
            return  # A pending download binds the current device when it is ready.
        device = self.output.device()
        available = {bytes(item.id()) for item in QMediaDevices.audioOutputs()}
        if (
            bytes(device.id()) not in available
            or device.id() != QMediaDevices.defaultAudioOutput().id()
        ):
            self.stop_audio()
            self._audio_status("音频设备已断开或切换，请确认耳机连接后重新朗读。")

    def _watch_foreground(self) -> None:
        if not self.card.isVisible() or self.card.pin.isChecked() or not self.source_window:
            return
        current = foreground()
        if current and current != self.source_window and process_id(current) != os.getpid():
            self.card.hide_passively()

    def escape(self) -> None:
        self.capture_token += 1
        self.dismiss()
        self.card.hide()

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
            self.dismiss()
            self.card.hide()
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
                self.source_window = baseline[1]
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
        self.runner.cancel("translation")
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
                "attention", settings, key, lambda _: None, use_cache=False
            )

        self.runner.submit("test", self.test_token, test)

    def speak(self, text: str, settings: Settings) -> None:
        if not text:
            return
        session = (
            text,
            settings.speech_backend,
            settings.voice,
            settings.rate,
            settings.system_voice,
        )
        if self.audio_session == session:
            return
        self.stop_audio()
        self.audio_session = session
        self.audio_phase = "generating"
        self.card.speak.setEnabled(False)
        if settings.speech_backend == "system":
            try:
                self.system.play(text, settings.system_voice, settings.rate)
                self.audio_phase = "playing"
                self.audio_timer.start()
                self._audio_status("正在使用系统语音朗读。")
            except Exception as exc:
                self._finish_audio()
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
        was_active = self.audio_session is not None
        self._finish_audio()
        self.runner.cancel("speech")
        self.player.stop()
        self.player.setSource(QUrl())
        try:
            self.system.stop()
        except Exception:
            self._audio_status("系统语音停止失败，请退出小译后重新启动。")
            return
        if was_active:
            self._audio_status("朗读已停止。")

    def _finish_audio(self) -> None:
        self.audio_session = None
        self.audio_phase = "idle"
        self.audio_timer.stop()
        self.card.speak.setEnabled(True)
        self.card.recover.setEnabled(False)

    def _media_status(self, status) -> None:
        if self.audio_session and status == QMediaPlayer.MediaStatus.LoadedMedia:
            # Seeking before LoadedMedia can be silently ignored by the backend.
            self.player.setPosition(self.audio_resume_position)
            self.player.play()
        if self.audio_session and status == QMediaPlayer.MediaStatus.EndOfMedia:
            self._finish_audio()
            self._audio_status("朗读完成。")

    def _playback_state(self, state) -> None:
        if not self.audio_session:
            return
        if state == QMediaPlayer.PlaybackState.PlayingState:
            self.audio_phase = "playing"
            self.card.recover.setEnabled(True)
            self.audio_timer.start()
        elif state == QMediaPlayer.PlaybackState.StoppedState and self.audio_phase == "playing":
            token = self.audio_token
            player = self.player

            def check_stopped():
                if token != self.audio_token or self.player is not player or not self.audio_session:
                    return
                # Qt can emit StoppedState before EndOfMedia in the same event loop turn.
                if self.player.mediaStatus() == QMediaPlayer.MediaStatus.EndOfMedia:
                    self._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
                elif self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState:
                    self._finish_audio()
                    self._audio_status("朗读意外中断，请点击朗读重试。")

            QTimer.singleShot(0, check_stopped)

    def _audio_progress(self) -> None:
        if not self.audio_session or self.audio_phase != "playing":
            return
        if self.audio_session[1] == "system":
            try:
                if not self.system.is_speaking():
                    self._finish_audio()
                    self._audio_status("朗读完成。")
            except Exception:
                self.stop_audio()
                self._audio_status("无法读取系统语音状态，请重新选择英文声音。")
            return
        position = self.player.position() // 1000
        duration = self.player.duration() // 1000
        self._audio_status(
            f"正在朗读 {position // 60:02d}:{position % 60:02d}"
            f" / {duration // 60:02d}:{duration % 60:02d}"
            f" · 输出：{self.output.device().description()}"
        )

    def _audio_status(self, message: str) -> None:
        if self.card.isVisible():
            self.card.status.setText(message)
        if self.window and self.window.isVisible():
            self.window.status.setText(message)

    def _playback_error(self, error, _message: str) -> None:
        if self.audio_session and error != QMediaPlayer.Error.NoError:
            self._finish_audio()
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

    def cancel_translation(self) -> None:
        self.translation_token += 1
        self.runner.cancel("translation")

    def dismiss(self) -> None:
        self.cancel_translation()
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
                self._start_playback(QUrl.fromLocalFile(str(payload)))
            else:
                self._finish_audio()
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
        self.foreground_timer.stop()
        self.hook.stop()
        self.stop_audio()
        self.runner.stop()
        self.media_devices.audioOutputsChanged.disconnect(self._output_devices_changed)
        self.media_devices.deleteLater()
        self.player.deleteLater()
        self.output.deleteLater()
        self.tray.hide()
