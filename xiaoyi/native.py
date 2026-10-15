"""Windows keyboard hook. The hook never suppresses or synthesizes keystrokes."""

import ctypes
import threading
import time
from ctypes import wintypes

from PySide6.QtCore import QObject, Signal

from .core import CopyGesture

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
LRESULT = ctypes.c_ssize_t
HOOKPROC = ctypes.WINFUNCTYPE(LRESULT, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t)


class KeyboardData(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = ctypes.c_void_p
user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_size_t, ctypes.c_ssize_t]
user32.CallNextHookEx.restype = LRESULT
user32.UnhookWindowsHookEx.argtypes = [ctypes.c_void_p]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetClipboardOwner.restype = wintypes.HWND
user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.PostThreadMessageW.argtypes = [
    wintypes.DWORD,
    wintypes.UINT,
    ctypes.c_size_t,
    ctypes.c_ssize_t,
]
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.GetCurrentThreadId.restype = wintypes.DWORD


def foreground() -> int:
    return user32.GetForegroundWindow() or 0


def clipboard_sequence() -> int:
    return user32.GetClipboardSequenceNumber()


def process_id(hwnd: int) -> int:
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def read_clipboard(source: int) -> str:
    import win32clipboard
    import win32con

    owner = user32.GetClipboardOwner()
    if owner and process_id(owner) != process_id(source):
        return ""
    win32clipboard.OpenClipboard()
    try:
        if not win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return ""
        return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


class KeyboardHook(QObject):
    triggered = Signal(object)  # (clipboard sequence before first C, source HWND)
    failed = Signal(str)
    escape_pressed = Signal()

    def __init__(self):
        super().__init__()
        self.enabled = threading.Event()
        self.enabled.set()
        self.thread_id = 0
        self.thread = threading.Thread(target=self._run, name="xiaoyi-keyboard", daemon=True)
        self.ready = threading.Event()

    def start(self) -> None:
        self.thread.start()

    def stop(self) -> None:
        self.ready.wait(1)
        if self.thread_id:
            user32.PostThreadMessageW(self.thread_id, 0x0012, 0, 0)  # WM_QUIT
        self.thread.join(timeout=2)

    def _run(self) -> None:
        self.thread_id = kernel32.GetCurrentThreadId()
        gesture = CopyGesture()
        controls: set[int] = set()
        baseline = (0, 0)

        def callback(code: int, message: int, pointer: int) -> int:
            nonlocal baseline
            try:
                if code >= 0:
                    data = ctypes.cast(pointer, ctypes.POINTER(KeyboardData)).contents
                    if not data.flags & 0x10:  # Ignore injected keystrokes.
                        down = message in (0x0100, 0x0104)
                        if not self.enabled.is_set():
                            gesture.reset()
                            controls.clear()
                        elif data.vkCode in (0x11, 0xA2, 0xA3):
                            if down:
                                controls.add(data.vkCode)
                            else:
                                controls.discard(data.vkCode)
                            gesture.feed("ctrl", bool(controls), time.monotonic())
                        else:
                            now = time.monotonic()
                            if data.vkCode == 0x1B and down:
                                self.escape_pressed.emit()
                            if data.vkCode == 0x43:
                                # Ignore Shift/Alt/Win combinations, including held modifiers.
                                modified = any(
                                    user32.GetAsyncKeyState(key) & 0x8000
                                    for key in (0x10, 0x12, 0x5B, 0x5C)
                                )
                                if modified:
                                    gesture.reset()
                                else:
                                    if (
                                        down
                                        and not gesture.c_down
                                        and (gesture.first is None or now - gesture.first > 0.6)
                                    ):
                                        baseline = (clipboard_sequence(), foreground())
                                    if gesture.feed("c", down, now):
                                        self.triggered.emit(baseline)
                            else:
                                gesture.feed("other", down, now)
            except Exception:
                gesture.reset()
                self.failed.emit("键盘监听出现异常，请退出后重新启动小译。")
            return user32.CallNextHookEx(None, code, message, pointer)

        self._callback = HOOKPROC(callback)
        hook = user32.SetWindowsHookExW(13, self._callback, kernel32.GetModuleHandleW(None), 0)
        if not hook:
            self.ready.set()
            self.failed.emit("无法开启全局快捷键，请退出后重试。")
            return
        message = wintypes.MSG()
        user32.PeekMessageW(ctypes.byref(message), None, 0, 0, 0)  # Create thread message queue.
        self.ready.set()
        try:
            while True:
                result = user32.GetMessageW(ctypes.byref(message), None, 0, 0)
                if result <= 0:
                    if result == -1:
                        self.failed.emit("全局快捷键监听已中断，请重启小译。")
                    break
                user32.TranslateMessage(ctypes.byref(message))
                user32.DispatchMessageW(ctypes.byref(message))
        finally:
            user32.UnhookWindowsHookEx(hook)


class SystemSpeech:
    """SAPI async playback on the GUI's COM apartment."""

    def __init__(self):
        self.speaker = None

    def _speaker(self):
        if self.speaker is None:
            import win32com.client

            self.speaker = win32com.client.Dispatch("SAPI.SpVoice")
        return self.speaker

    def voices(self) -> list[tuple[str, str]]:
        return [
            (voice.Id, voice.GetDescription())
            for voice in self._speaker().GetVoices()
            if any(
                language.lower().lstrip("0") in {"409", "809", "c09", "1009", "1409", "1809"}
                for language in voice.GetAttribute("Language").split(";")
            )
        ]

    def play(self, text: str, voice_id: str, rate: int) -> None:
        speaker = self._speaker()
        voices = self.voices()
        if not voices:
            raise RuntimeError(
                "未找到英文系统声音。请在 Windows 设置 → 时间和语言 → 语音中安装英文语音。"
            )
        wanted = voice_id or voices[0][0]
        for voice in speaker.GetVoices():
            if voice.Id == wanted and any(item[0] == wanted for item in voices):
                speaker.Voice = voice
                break
        else:
            raise RuntimeError("所选系统声音已不可用，请在设置中重新选择。")
        speaker.Rate = max(-10, min(10, round(rate / 10)))
        speaker.Speak(text, 1 | 2 | 16)  # Async, purge old speech, plain text (not SSML).

    def stop(self) -> None:
        if self.speaker is not None:
            self.speaker.Speak("", 1 | 2 | 16)

    def is_speaking(self) -> bool:
        return self.speaker is not None and self.speaker.Status.RunningState == 2
