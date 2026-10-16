import time
from dataclasses import replace

import pytest
from PySide6.QtCore import QObject, QPoint, Signal
from PySide6.QtTest import QTest

from xiaoyi.config import Settings


class FakeHook(QObject):
    triggered = Signal(object)
    failed = Signal(str)
    escape_pressed = Signal()

    def __init__(self):
        super().__init__()
        import threading

        self.enabled = threading.Event()
        self.enabled.set()

    def start(self):
        pass

    def stop(self):
        pass


class FakeRunner(QObject):
    event = Signal(str, int, object)

    def __init__(self):
        super().__init__()
        self.submitted = []
        self.cancelled = []

    def submit(self, channel, token, factory):
        self.submitted.append((channel, token, factory))

    def cancel(self, channel):
        self.cancelled.append(channel)

    def stop(self):
        pass


class FakeSystem:
    def voices(self):
        return [("english", "English")]

    def play(self, *args):
        self.played = args

    def stop(self):
        pass

    def is_speaking(self):
        return True


@pytest.fixture
def desktop(qapp, monkeypatch):
    import xiaoyi.app as module

    monkeypatch.setattr(module, "KeyboardHook", FakeHook)
    monkeypatch.setattr(module, "AsyncRunner", FakeRunner)
    monkeypatch.setattr(module, "SystemSpeech", FakeSystem)
    monkeypatch.setattr(module, "get_key", lambda _: "test")
    monkeypatch.setattr("xiaoyi.ui.get_key", lambda _: "")
    item = module.Desktop(qapp, Settings())
    yield item
    item.shutdown()
    item.card.hide()
    if item.window:
        item.window.hide()
        item.window.deleteLater()
    item.card.deleteLater()
    qapp.processEvents()


def test_only_current_translation_changes_card(desktop):
    desktop.card.present("attention", QPoint(10, 10))
    desktop.translate("attention")
    old = desktop.translation_token
    desktop.translate("kernel")
    current = desktop.translation_token
    desktop._event("translation:chunk", old, "旧结果")
    assert desktop.card.result == ""
    desktop._event("translation:chunk", current, "内核")
    desktop._event("translation:done", current, "内核")
    assert desktop.card.result == "内核"
    assert desktop.card.copy.isEnabled()
    desktop._event("translation:error", current, "测试错误")
    assert desktop.card.status.text() == "测试错误"
    desktop.dismiss()
    desktop._event("translation:chunk", current, "关闭后结果")
    assert desktop.card.result == "内核"


def test_capture_fresh_text_then_rejects_stale_or_other_window(desktop, monkeypatch):
    monkeypatch.setattr("xiaoyi.app.process_id", lambda _: 999999)
    monkeypatch.setattr("xiaoyi.app.foreground", lambda: 101)
    monkeypatch.setattr("xiaoyi.app.clipboard_sequence", lambda: 21)
    monkeypatch.setattr("xiaoyi.app.read_clipboard", lambda _: "memory\nbandwidth")
    desktop.capture((20, 101))
    QTest.qWait(80)
    assert desktop.card.text == "memory bandwidth"
    assert desktop.card.isVisible()
    before = len(desktop.runner.submitted)
    desktop.capture((21, 101))
    QTest.qWait(950)
    assert len(desktop.runner.submitted) == before
    desktop.capture((20, 102))
    QTest.qWait(80)
    assert len(desktop.runner.submitted) == before


def test_capture_failure_and_pause(desktop, monkeypatch):
    monkeypatch.setattr("xiaoyi.app.process_id", lambda _: 999999)
    monkeypatch.setattr("xiaoyi.app.foreground", lambda: 101)
    monkeypatch.setattr("xiaoyi.app.clipboard_sequence", lambda: 21)
    monkeypatch.setattr("xiaoyi.app.read_clipboard", lambda _: "只有中文")
    notices = []
    monkeypatch.setattr(desktop, "notify", notices.append)
    desktop.capture((20, 101))
    QTest.qWait(70)
    assert "英文" in notices[-1]
    desktop.capture((20, 101))
    desktop.toggle(False)
    QTest.qWait(70)
    assert not desktop.hook.enabled.is_set()
    assert not desktop.card.isVisible()
    desktop.toggle(True)
    assert desktop.hook.enabled.is_set()
    desktop._hook_error("hook stopped")
    assert desktop.health_errors == ["hook stopped"]


def test_settings_save_test_speech_and_errors(desktop, monkeypatch, tmp_path):
    desktop.show_settings()
    saved = []
    monkeypatch.setattr("xiaoyi.app.set_key", lambda base, key: saved.append((base, key)))
    monkeypatch.setattr("xiaoyi.app.set_startup", lambda enabled: saved.append(enabled))
    monkeypatch.setattr("xiaoyi.app.save_settings", lambda settings: saved.append(settings))
    settings = replace(Settings(), rate=10)
    desktop.save(settings, "test")
    assert desktop.settings.rate == 10 and saved[0][1] == "test"
    desktop.test_connection(settings, "test")
    assert not desktop.window.test_button.isEnabled()
    desktop._event("test:done", desktop.test_token, "注意力")
    assert desktop.window.test_button.isEnabled()
    assert "连接成功" in desktop.window.status.text()
    desktop._event("test:error", desktop.test_token, "认证失败")
    assert desktop.window.status.text() == "认证失败"
    desktop.speak("word", replace(settings, speech_backend="system"))
    assert desktop.system.played[0] == "word"
    desktop.speak("word", settings)
    old = desktop.audio_token
    desktop.stop_audio()
    desktop._event("speech:error", old, "stale")
    assert "stale" not in desktop.window.status.text()
    desktop.speak("word", settings)
    desktop._event("speech:error", desktop.audio_token, "语音失败")
    assert desktop.window.status.text() == "语音失败"
    desktop.clear_audio_cache()
    desktop._event("clear:done", 0, 2)
    assert "2" in desktop.window.status.text()
    monkeypatch.setattr(
        desktop.system, "play", lambda *args: (_ for _ in ()).throw(RuntimeError("无声音"))
    )
    desktop.speak("word", replace(settings, speech_backend="system"))
    assert desktop.window.status.text() == "无声音"
    monkeypatch.setattr(
        "xiaoyi.app.save_settings", lambda _: (_ for _ in ()).throw(OSError("磁盘"))
    )
    desktop.save(settings, "test")
    assert "保存失败" in desktop.window.status.text()


def test_missing_credentials_and_invalid_clipboard(desktop, monkeypatch):
    def fail(_):
        raise RuntimeError("credential error")

    monkeypatch.setattr("xiaoyi.app.get_key", fail)
    desktop.translate("word")
    assert "credential error" in desktop.card.status.text()
    monkeypatch.setattr("xiaoyi.app.process_id", lambda _: 999999)
    monkeypatch.setattr("xiaoyi.app.foreground", lambda: 101)
    monkeypatch.setattr("xiaoyi.app.read_clipboard", fail)
    notices = []
    monkeypatch.setattr(desktop, "notify", notices.append)
    desktop.capture((20, 101))
    QTest.qWait(950)
    assert notices and "重新选中" in notices[-1]


def test_async_runner_cancels_old_tasks_and_reports_errors(qapp):
    import asyncio

    from xiaoyi.runner import AsyncRunner
    from xiaoyi.services import ServiceError

    runner = AsyncRunner()
    events = []
    runner.event.connect(lambda *args: events.append(args))

    async def delayed():
        await asyncio.sleep(0.3)
        return "old"

    async def latest():
        assert runner.translation_service() is runner.translation_service()
        return "new"

    async def failure():
        raise ServiceError("safe error")

    async def unexpected():
        raise RuntimeError("sensitive details")

    try:
        runner.submit("work", 1, delayed)
        runner.submit("work", 2, latest)
        deadline = time.monotonic() + 2
        while not events and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert events == [("work:done", 2, "new")]
        runner.submit("fail", 3, failure)
        runner.submit("unexpected", 4, unexpected)
        deadline = time.monotonic() + 2
        while len(events) < 3 and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.01)
        assert ("fail:error", 3, "safe error") in events
        assert "sensitive" not in repr(events)
    finally:
        runner.stop()
    assert not runner.thread.is_alive()


def test_unpinned_inactive_card_hides_on_foreground_switch(desktop, monkeypatch):
    desktop.source_window = 101
    desktop.card.present("word", QPoint(10, 10))
    monkeypatch.setattr("xiaoyi.app.foreground", lambda: 202)
    monkeypatch.setattr("xiaoyi.app.process_id", lambda _: 999999)
    desktop._watch_foreground()
    assert not desktop.card.isVisible()
    desktop.source_window = 101
    desktop.card.present("word", QPoint(10, 10))
    desktop.card.pin.setChecked(True)
    desktop._watch_foreground()
    assert desktop.card.isVisible()


@pytest.mark.parametrize("backend", ["online", "system"])
def test_repeated_read_request_does_not_interrupt_current_audio(desktop, monkeypatch, backend):
    desktop.card.present("First sentence. Second sentence.", QPoint(10, 10))
    settings = replace(Settings(), speech_backend=backend)
    desktop.speak(desktop.card.text, settings)
    token = desktop.audio_token
    submitted = len(desktop.runner.submitted)
    stops = []
    monkeypatch.setattr(desktop.player, "stop", lambda: stops.append(True))
    desktop.speak(desktop.card.text, settings)
    assert desktop.audio_token == token
    assert len(desktop.runner.submitted) == submitted
    assert not stops
    assert not desktop.card.speak.isEnabled()
    desktop.stop_audio()
    assert desktop.card.speak.isEnabled()


def test_playback_completion_and_unexpected_stop_are_visible(desktop):
    from PySide6.QtMultimedia import QMediaPlayer

    desktop.card.present("First sentence. Second sentence.", QPoint(10, 10))
    desktop.speak(desktop.card.text, Settings())
    desktop._media_status(QMediaPlayer.MediaStatus.EndOfMedia)
    assert desktop.card.speak.isEnabled()
    assert desktop.card.status.text() == "朗读完成。"
    desktop.speak(desktop.card.text, Settings())
    desktop._playback_state(QMediaPlayer.PlaybackState.PlayingState)
    desktop._playback_state(QMediaPlayer.PlaybackState.StoppedState)
    QTest.qWait(10)
    assert desktop.card.speak.isEnabled()
    assert "中断" in desktop.card.status.text()


def test_passive_card_hide_keeps_audio_until_explicit_stop(desktop, monkeypatch):
    desktop.card.present("First sentence. Second sentence.", QPoint(10, 10))
    desktop.speak(desktop.card.text, Settings())
    token = desktop.audio_token
    desktop.source_window = 101
    monkeypatch.setattr("xiaoyi.app.foreground", lambda: 202)
    monkeypatch.setattr("xiaoyi.app.process_id", lambda _: 999999)
    desktop._watch_foreground()
    assert not desktop.card.isVisible()
    assert desktop.audio_token == token
    assert "speech" not in desktop.runner.cancelled[-1:]
    desktop.escape()
    assert desktop.audio_token != token


def test_playback_progress_and_system_completion(desktop, monkeypatch):
    from PySide6.QtMultimedia import QMediaPlayer

    desktop.card.present("word", QPoint(10, 10))
    desktop.speak("word", Settings())
    desktop._playback_state(QMediaPlayer.PlaybackState.PlayingState)
    monkeypatch.setattr(desktop.player, "position", lambda: 2200)
    monkeypatch.setattr(desktop.player, "duration", lambda: 11400)
    desktop._audio_progress()
    assert "00:02 / 00:11" in desktop.card.status.text()
    desktop.speak("word", replace(Settings(), speech_backend="system"))
    monkeypatch.setattr(desktop.system, "is_speaking", lambda: False)
    desktop._audio_progress()
    assert desktop.card.status.text() == "朗读完成。"
    assert desktop.card.speak.isEnabled()


def test_old_deferred_stop_cannot_cancel_new_speech(desktop):
    from PySide6.QtMultimedia import QMediaPlayer

    desktop.speak("first", Settings())
    desktop._playback_state(QMediaPlayer.PlaybackState.PlayingState)
    desktop._playback_state(QMediaPlayer.PlaybackState.StoppedState)
    desktop.speak("second", Settings())
    QTest.qWait(10)
    assert desktop.audio_session[0] == "second"
    assert not desktop.card.speak.isEnabled()


def test_recover_audio_replaces_output_and_keeps_current_file(desktop, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from PySide6.QtCore import QUrl
    from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

    def output(*args):
        item = QAudioOutput()
        monkeypatch.setattr(
            item,
            "device",
            lambda: SimpleNamespace(isNull=lambda: False, description=lambda: "test"),
        )
        return item

    monkeypatch.setattr("xiaoyi.app.QAudioOutput", output)
    seeks = []
    monkeypatch.setattr(QMediaPlayer, "setPosition", lambda self, value: seeks.append(value))
    monkeypatch.setattr(QMediaPlayer, "play", lambda self: None)

    desktop.card.present("MDP instantiation. Let Ht denote the harness.", QPoint(10, 10))
    desktop.speak(desktop.card.text, Settings())
    desktop._playback_state(QMediaPlayer.PlaybackState.PlayingState)
    source = QUrl.fromLocalFile(str(tmp_path / "speech.mp3"))
    old_player, old_output = desktop.player, desktop.output
    monkeypatch.setattr(old_player, "source", lambda: source)
    monkeypatch.setattr(old_player, "position", lambda: 3200)
    submitted = len(desktop.runner.submitted)
    desktop.recover_audio()
    assert desktop.player is not old_player
    assert desktop.output is not old_output
    assert desktop.player.source() == source
    desktop.player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
    assert seeks == [2200]
    assert len(desktop.runner.submitted) == submitted
    assert desktop.audio_session is not None
    # An old backend can still emit queued signals after it was detached.
    old_player.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
    old_player.errorOccurred.emit(QMediaPlayer.Error.ResourceError, "old error")
    assert desktop.audio_session is not None


def test_recovery_is_unavailable_before_audio_or_for_system_voice(desktop):
    assert not desktop.card.recover.isEnabled()
    desktop.speak("word", Settings())
    player = desktop.player
    desktop.recover_audio()
    assert desktop.player is player
    desktop.speak("word", replace(Settings(), speech_backend="system"))
    desktop.recover_audio()
    assert desktop.player is player
    assert not desktop.card.recover.isEnabled()


def test_output_change_stops_audio_with_actionable_message(desktop, monkeypatch):
    from PySide6.QtMultimedia import QMediaPlayer

    desktop.card.present("word", QPoint(10, 10))
    desktop.speak("word", Settings())
    desktop._playback_state(QMediaPlayer.PlaybackState.PlayingState)
    monkeypatch.setattr("xiaoyi.app.QMediaDevices.audioOutputs", lambda: [])
    desktop._output_devices_changed()
    assert desktop.audio_session is None
    assert "音频设备" in desktop.card.status.text()
    assert desktop.card.speak.isEnabled()


@pytest.mark.parametrize("event", ["end", "error", "loaded", "playing"])
@pytest.mark.parametrize("backend", ["online", "system"])
def test_previous_player_events_do_not_affect_new_synthesis(desktop, event, backend):
    from PySide6.QtMultimedia import QMediaPlayer

    desktop.speak("first", Settings())
    previous = desktop.player
    desktop.speak("second", replace(Settings(), speech_backend=backend))
    if event == "end":
        previous.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.EndOfMedia)
    elif event == "error":
        previous.errorOccurred.emit(QMediaPlayer.Error.ResourceError, "late error")
    elif event == "loaded":
        previous.mediaStatusChanged.emit(QMediaPlayer.MediaStatus.LoadedMedia)
    else:
        previous.playbackStateChanged.emit(QMediaPlayer.PlaybackState.PlayingState)
    assert desktop.audio_session[0] == "second"
    assert desktop.audio_phase == ("generating" if backend == "online" else "playing")
    assert not desktop.card.speak.isEnabled()
