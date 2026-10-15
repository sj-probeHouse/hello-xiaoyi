"""Local preferences; credentials are stored only in Windows Credential Manager."""

import hashlib
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from urllib.parse import urlsplit

PRESETS = {
    "DeepSeek": ("https://api.deepseek.com", "deepseek-flash"),
    "MiMo": ("https://api.xiaomimimo.com/v1", "mimo-v2.6-flash"),
    "自定义": ("", ""),
}
DATA_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "HelloXiaoyi"


@dataclass
class Settings:
    provider: str = "DeepSeek"
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-flash"
    domain: str = "计算机 / AI / 电子工程"
    voice: str = "en-US-JennyNeural"
    rate: int = 0
    speech_backend: str = "online"
    system_voice: str = ""
    startup: bool = False

    def validate(self) -> None:
        url = urlsplit(self.base_url)
        if url.scheme != "https" or not url.hostname or url.username or url.password:
            raise ValueError("Base URL 必须是无用户名密码的 HTTPS 地址。")
        if url.query or url.fragment:
            raise ValueError("Base URL 不能包含查询参数或片段。")
        if not self.model.strip() or len(self.model) > 200:
            raise ValueError("请填写有效的模型名称。")
        if len(self.domain) > 500:
            raise ValueError("领域提示请控制在 500 字以内。")
        if not isinstance(self.rate, int) or not -50 <= self.rate <= 100:
            raise ValueError("语速范围为 -50% 至 +100%。")
        if self.speech_backend not in {"online", "system"}:
            raise ValueError("不支持的语音方式。")
        if not self.voice.startswith(("en-US-", "en-GB-")) or not self.voice.endswith("Neural"):
            raise ValueError("请选择美式或英式在线音色。")


def load_settings(path: Path = DATA_DIR / "settings.json") -> Settings:
    if not path.exists():
        return Settings()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("设置格式无效")
        valid = {f.name for f in fields(Settings)}
        settings = Settings(**{k: v for k, v in data.items() if k in valid})
        settings.validate()
        return settings
    except (OSError, TypeError, ValueError, AttributeError) as exc:
        raise ValueError("本地设置无法读取。请备份用户数据目录中的 settings.json 后重试。") from exc


def save_settings(settings: Settings, path: Path = DATA_DIR / "settings.json") -> None:
    settings.validate()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(asdict(settings), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    temporary.replace(path)


def credential_name(base_url: str) -> str:
    digest = hashlib.sha256(base_url.rstrip("/").encode()).hexdigest()
    return f"HelloXiaoyi/{digest}"


def get_key(base_url: str) -> str:
    import pywintypes
    import win32cred

    try:
        item = win32cred.CredRead(credential_name(base_url), win32cred.CRED_TYPE_GENERIC)
        return item["CredentialBlob"].decode("utf-16-le")
    except pywintypes.error as exc:
        if exc.winerror == 1168:  # ERROR_NOT_FOUND
            return ""
        raise RuntimeError("无法读取 Windows 凭据管理器。") from exc


def set_key(base_url: str, key: str) -> None:
    import pywintypes
    import win32cred

    name = credential_name(base_url)
    try:
        if not key:
            try:
                win32cred.CredDelete(name, win32cred.CRED_TYPE_GENERIC)
            except pywintypes.error as exc:
                if exc.winerror != 1168:
                    raise
            return
        win32cred.CredWrite(
            {
                "Type": win32cred.CRED_TYPE_GENERIC,
                "TargetName": name,
                "UserName": "api-key",
                "CredentialBlob": key,
                "Persist": win32cred.CRED_PERSIST_LOCAL_MACHINE,
            },
            0,
        )
    except pywintypes.error as exc:
        raise RuntimeError("无法保存密钥到 Windows 凭据管理器。") from exc


def set_startup(enabled: bool) -> None:
    import winreg

    with winreg.CreateKey(
        winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"
    ) as key:
        if enabled:
            if getattr(sys, "frozen", False):
                args = [sys.executable, "--background"]
            else:
                pythonw = str(Path(sys.executable).with_name("pythonw.exe"))
                args = [
                    pythonw,
                    str(Path(__file__).resolve().parents[1] / "main.py"),
                    "--background",
                ]
            winreg.SetValueEx(key, "HelloXiaoyi", 0, winreg.REG_SZ, subprocess.list2cmdline(args))
        else:
            try:
                winreg.DeleteValue(key, "HelloXiaoyi")
            except FileNotFoundError:
                pass
