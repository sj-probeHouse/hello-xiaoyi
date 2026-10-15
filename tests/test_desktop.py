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
