import time
from dataclasses import replace

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest

from xiaoyi.config import Settings
from xiaoyi.ui import STYLE, SettingsWindow, TranslationCard


def test_card_user_journey(qapp):
    qapp.setStyleSheet(STYLE)
    card = TranslationCard()
    calls = []
    card.speak_requested.connect(lambda: calls.append("speak"))
    card.stop_requested.connect(lambda: calls.append("stop"))
    card.dismissed.connect(lambda: calls.append("close"))
    started = time.monotonic()
    card.present("attention", QPoint(300, 200))
    qapp.processEvents()
    assert card.isVisible()
    assert time.monotonic() - started < 0.2
    assert card.original.toPlainText() == "attention"
    assert not card.copy.isEnabled()
    card.append("注")
    card.append("意力")
    card.finish("注意力")
    QTest.mouseClick(card.copy, Qt.MouseButton.LeftButton)
    assert qapp.clipboard().text() == "注意力"
    QTest.mouseClick(card.speak, Qt.MouseButton.LeftButton)
    assert "speak" in calls
    QTest.mouseClick(card.pin, Qt.MouseButton.LeftButton)
    assert card.pin.isChecked()
    card.error("连接失败")
    assert card.retry.isVisible()
    card.close()
    assert not card.isVisible() and "close" in calls
    card.deleteLater()


def test_settings_form_and_preview_without_translation_key(qapp, monkeypatch):
    monkeypatch.setattr("xiaoyi.ui.get_key", lambda _: "")
    window = SettingsWindow(Settings(), [("voice-id", "English Voice")])
    saved, tested, previews = [], [], []
    window.save_requested.connect(lambda settings, key: saved.append((settings, key)))
    window.test_requested.connect(lambda settings, key: tested.append((settings, key)))
    window.preview_requested.connect(previews.append)
    window.show()
    window.provider.setCurrentText("MiMo")
    assert window.model.text() == "mimo-v2.6-flash"
    assert window.base.text() == "https://api.xiaomimimo.com/v1"
    window.key.setText("test-key")
    window._test()
    assert tested[0][1] == "test-key"
    window.rate.setValue(20)
    window.backend.setCurrentIndex(1)
    window._save()
    assert saved[0][0].speech_backend == "system"
    assert saved[0][0].system_voice == "voice-id"
    assert saved[0][0].rate == 20
    window.provider.setCurrentText("自定义")
    window._save()
    assert "HTTPS" in window.status.text()
    window._preview()
    assert previews[0].speech_backend == "system"
    window.close()
    assert not window.isVisible()
    window.deleteLater()


def test_settings_key_error_and_bad_model(qapp, monkeypatch):
    def fail(_):
        raise RuntimeError("credential error")

    monkeypatch.setattr("xiaoyi.ui.get_key", fail)
    window = SettingsWindow(replace(Settings(), system_voice="missing"), [])
    assert "credential error" in window.status.text()
    window.model.clear()
    window._test()
    assert "模型" in window.status.text()
    window.deleteLater()
