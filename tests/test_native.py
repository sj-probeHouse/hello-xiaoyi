import ctypes
from types import SimpleNamespace

import pytest

from xiaoyi import native


def test_hook_native_dispatch_does_not_suppress_input(qapp, monkeypatch):
    results, escaped = [], []
    hook = native.KeyboardHook()
    hook.triggered.connect(results.append)
    hook.escape_pressed.connect(lambda: escaped.append(True))
    monkeypatch.setattr(native.user32, "SetWindowsHookExW", lambda *args: 123)
    monkeypatch.setattr(native.user32, "CallNextHookEx", lambda *args: 77)
    monkeypatch.setattr(native.user32, "UnhookWindowsHookEx", lambda *args: True)
    monkeypatch.setattr(native.user32, "PeekMessageW", lambda *args: 0)
    monkeypatch.setattr(native.user32, "GetAsyncKeyState", lambda key: 0)
    monkeypatch.setattr(native, "foreground", lambda: 12345)
    monkeypatch.setattr(native, "clipboard_sequence", lambda: 99)

    def feed(vk, down, flags=0):
        data = native.KeyboardData(vkCode=vk, flags=flags)
        assert hook._callback(0, 0x0100 if down else 0x0101, ctypes.addressof(data)) == 77

    def messages(*args):
        feed(0xA2, True)
        feed(0x43, True)
        feed(0x43, True)  # autorepeat
        feed(0x43, False)
        feed(0x43, True)
        feed(0x43, False)
        feed(0xA2, False)
        feed(0x1B, True)
        # Injected key events never initiate a translation.
        feed(0xA2, True, 0x10)
        feed(0x43, True, 0x10)
        feed(0x43, False, 0x10)
        feed(0x43, True, 0x10)
        hook.enabled.clear()
        feed(0x43, True)
        return 0

    monkeypatch.setattr(native.user32, "GetMessageW", messages)
    hook._run()
    assert results == [(99, 12345)]
    assert escaped == [True]
    assert hook.ready.is_set()


def test_hook_failure_is_reported(qapp, monkeypatch):
    hook = native.KeyboardHook()
    errors = []
    hook.failed.connect(errors.append)
    monkeypatch.setattr(native.user32, "SetWindowsHookExW", lambda *args: None)
    hook._run()
    assert errors and "无法开启" in errors[0]


def test_actual_hook_can_start_and_stop(qapp):
    hook = native.KeyboardHook()
    try:
        hook.start()
        assert hook.ready.wait(2)
        assert hook.thread.is_alive()
    finally:
        hook.stop()
    assert not hook.thread.is_alive()


def test_native_clipboard_owner_and_formats(monkeypatch):
    import win32clipboard

    monkeypatch.setattr(native.user32, "GetClipboardOwner", lambda: 101)
    monkeypatch.setattr(native, "process_id", lambda hwnd: hwnd)
    assert native.read_clipboard(102) == ""
    opened = []
    monkeypatch.setattr(win32clipboard, "OpenClipboard", lambda: opened.append(True))
    monkeypatch.setattr(win32clipboard, "CloseClipboard", lambda: opened.append(False))
    monkeypatch.setattr(win32clipboard, "IsClipboardFormatAvailable", lambda _: True)
    monkeypatch.setattr(win32clipboard, "GetClipboardData", lambda _: "attention")
    assert native.read_clipboard(101) == "attention"
    assert opened == [True, False]
    monkeypatch.setattr(win32clipboard, "IsClipboardFormatAvailable", lambda _: False)
    assert native.read_clipboard(101) == ""


def test_system_voice_selection_and_plain_text_playback():
    def voice(identifier, language):
        return SimpleNamespace(
            Id=identifier, GetDescription=lambda: identifier, GetAttribute=lambda _: language
        )

    calls = []
    english, chinese = voice("English", "409"), voice("Chinese", "804")
    speaker = SimpleNamespace(
        GetVoices=lambda: [english, chinese], Speak=lambda *args: calls.append(args)
    )
    speech = native.SystemSpeech()
    assert not speech.is_speaking()
    speech.speaker = speaker
    speaker.Status = SimpleNamespace(RunningState=2)
    assert speech.is_speaking()
    speaker.Status.RunningState = 1
    assert not speech.is_speaking()
    assert speech.voices() == [("English", "English")]
    speech.play("<word>", "", 20)
    assert speaker.Voice is english
    assert speaker.Rate == 2
    assert calls[-1] == ("<word>", 19)
    speech.stop()
    assert calls[-1][0] == ""
    with pytest.raises(RuntimeError, match="不可用"):
        speech.play("word", "missing", 0)
    speaker.GetVoices = lambda: [chinese]
    with pytest.raises(RuntimeError, match="安装英文"):
        speech.play("word", "", 0)


def test_startup_quotes_paths_and_removes_entry(monkeypatch):
    import winreg

    from xiaoyi.config import set_startup

    class Key:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    calls = []
    monkeypatch.setattr(winreg, "CreateKey", lambda *args: Key())
    monkeypatch.setattr(winreg, "SetValueEx", lambda *args: calls.append(args[-1]))
    monkeypatch.setattr(winreg, "DeleteValue", lambda *args: calls.append("deleted"))
    monkeypatch.setattr("sys.frozen", True, raising=False)
    monkeypatch.setattr("sys.executable", r"C:\Folder With Spaces\HelloXiaoyi.exe")
    set_startup(True)
    assert calls[-1] == '"C:\\Folder With Spaces\\HelloXiaoyi.exe" --background'
    set_startup(False)
    assert calls[-1] == "deleted"
