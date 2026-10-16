"""Async translation and online speech; no UI or native keyboard work."""

import asyncio
import hashlib
import json
import time
from collections import OrderedDict
from collections.abc import Callable
from pathlib import Path

import edge_tts
import httpx

from . import __version__
from .config import MIMO_PROVIDERS, Settings, validate_api_key
from .core import translation_prompt


class ServiceError(Exception):
    """Safe, user-facing service error (never include raw responses or credentials)."""


class TranslationService:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.cache: OrderedDict[tuple, str] = OrderedDict()

    async def translate(
        self,
        text: str,
        settings: Settings,
        key: str,
        emit: Callable[[str], None],
        *,
        use_cache: bool = True,
    ) -> str:
        if not key:
            raise ServiceError("尚未配置 API 密钥，请打开设置填写并测试连接。")
        settings.validate()
        try:
            validate_api_key(settings.base_url, key)
        except ValueError as exc:
            raise ServiceError(str(exc)) from exc
        cache_key = (
            settings.provider,
            settings.base_url,
            settings.model,
            settings.domain,
            text,
            hashlib.sha256(key.encode()).digest(),
        )
        if use_cache and cache_key in self.cache:
            self.cache.move_to_end(cache_key)
            emit(self.cache[cache_key])
            return self.cache[cache_key]
        payload = {
            "model": settings.model,
            "stream": True,
            "messages": [
                {"role": "system", "content": translation_prompt(text, settings.domain)},
                {"role": "user", "content": text},
            ],
        }
        if settings.provider == "DeepSeek" or settings.provider in MIMO_PROVIDERS:
            payload["thinking"] = {"type": "disabled"}
        headers = {"Authorization": f"Bearer {key}"}
        if settings.provider in MIMO_PROVIDERS:
            headers = {"api-key": key}
        parts = []
        completed = False
        try:
            async with asyncio.timeout(45):
                async with self.client.stream(
                    "POST",
                    settings.base_url.rstrip("/") + "/chat/completions",
                    headers=headers,
                    json=payload,
                ) as response:
                    if response.status_code != 200:
                        messages = {
                            401: "API 认证失败，请检查密钥及 Base URL。",
                            403: "服务拒绝访问，请检查账号权限和可用地区。",
                            404: "接口或模型不存在，请检查 Base URL 与模型名称。",
                            429: "请求受限或额度不足，请检查服务商账户，稍后重试。",
                        }
                        raise ServiceError(
                            messages.get(
                                response.status_code,
                                f"翻译服务暂不可用（HTTP {response.status_code}）。",
                            )
                        )
                    async for line in response.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if data == "[DONE]":
                            completed = True
                            break
                        if not data:
                            continue
                        try:
                            chunk = json.loads(data)
                            if "error" in chunk:
                                raise ServiceError("服务返回流式错误，请检查账户或模型后重试。")
                            choices = chunk.get("choices", [])
                            if not choices:
                                continue
                            choice = choices[0]
                            reason = choice.get("finish_reason")
                            if reason and reason != "stop":
                                raise ServiceError("译文被截断或过滤，请缩短选区后重试。")
                            value = choice.get("delta", {}).get("content")
                            if value:
                                if not isinstance(value, str):
                                    raise ValueError("invalid content")
                                parts.append(value)
                                emit(value)
                            if reason == "stop":
                                completed = True
                        except (ValueError, TypeError, KeyError, AttributeError, IndexError) as exc:
                            raise ServiceError("服务响应格式异常，请检查接口兼容性。") from exc
        except (TimeoutError, httpx.TimeoutException) as exc:
            raise ServiceError("翻译请求超时，请检查网络后重试。") from exc
        except httpx.HTTPError as exc:
            raise ServiceError("无法连接翻译服务，请检查网络、代理和 Base URL。") from exc
        result = "".join(parts).strip()
        if not completed or not result:
            raise ServiceError("译文未完整返回，请重新翻译。")
        self.cache[cache_key] = result
        while len(self.cache) > 128:
            self.cache.popitem(last=False)
        return result


def prepare_audio_cache(folder: Path) -> None:
    """Discard prior-release audio, leaving preferences and credentials untouched."""
    folder.mkdir(parents=True, exist_ok=True)
    marker = folder / ".version"
    if marker.exists() and marker.read_text(encoding="utf-8") == __version__:
        return
    for path in folder.iterdir():
        if path.is_file() and path.suffix in {".mp3", ".part"}:
            path.unlink()
    marker.write_text(__version__, encoding="utf-8")


async def synthesize(text: str, settings: Settings, folder: Path) -> Path:
    try:
        prepare_audio_cache(folder)
    except OSError as exc:
        raise ServiceError("无法清理旧版音频缓存，请退出其他小译实例后重试。") from exc
    digest = hashlib.sha256(f"{settings.voice}|{settings.rate}|{text}".encode()).hexdigest()
    path = folder / f"{digest}.mp3"
    if path.exists() and path.stat().st_size:
        path.touch()
        return path
    temporary = folder / f"{digest}.{time.time_ns()}.part"
    try:
        async with asyncio.timeout(30):
            await edge_tts.Communicate(text, settings.voice, rate=f"{settings.rate:+d}%").save(
                str(temporary)
            )
        if not temporary.stat().st_size:
            raise ServiceError("在线语音没有返回音频。")
        temporary.replace(path)
        # ponytail: bounded file scan; index only if cache sweeps become measurably slow.
        files = sorted(folder.glob("*.mp3"), key=lambda p: p.stat().st_mtime, reverse=True)
        total = 0
        for file in files:
            total += file.stat().st_size
            if total > 64 * 1024 * 1024 and file != path:
                try:
                    file.unlink()
                except PermissionError:
                    continue  # A currently playing file is retried on the next cache sweep.
        return path
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        raise ServiceError("在线语音不可用，请重试，或在设置中切换到系统语音。") from exc
    finally:
        temporary.unlink(missing_ok=True)
