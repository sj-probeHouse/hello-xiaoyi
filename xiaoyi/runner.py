"""One asyncio worker; cancellation and GUI delivery are scoped by request tokens."""

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any

import httpx
from PySide6.QtCore import QObject, Signal

from .services import ServiceError, TranslationService


class AsyncRunner(QObject):
    event = Signal(str, int, object)

    def __init__(self):
        super().__init__()
        self.loop = asyncio.new_event_loop()
        self.client = None
        self.translator = None
        self.futures: dict[str, Future] = {}
        self.thread = threading.Thread(target=self._run, name="xiaoyi-network", daemon=True)
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        self.loop.close()

    def translation_service(self) -> TranslationService:
        if self.client is None:
            self.client = httpx.AsyncClient(
                timeout=httpx.Timeout(20, connect=8),
                follow_redirects=False,
                limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
            )
            self.translator = TranslationService(self.client)
        return self.translator

    def cancel(self, channel: str) -> None:
        future = self.futures.pop(channel, None)
        if future:
            future.cancel()

    def submit(
        self, channel: str, token: int, factory: Callable[[], Coroutine[Any, Any, Any]]
    ) -> None:
        self.cancel(channel)

        async def execute():
            try:
                result = await factory()
                self.event.emit(channel + ":done", token, result)
            except asyncio.CancelledError:
                pass
            except (ServiceError, ValueError) as exc:
                self.event.emit(channel + ":error", token, str(exc))
            except Exception:
                self.event.emit(channel + ":error", token, "操作失败，请检查设置和网络后重试。")

        self.futures[channel] = asyncio.run_coroutine_threadsafe(execute(), self.loop)

    def stop(self) -> None:
        for channel in list(self.futures):
            self.cancel(channel)

        async def shutdown():
            tasks = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if self.client:
                await self.client.aclose()

        try:
            asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(timeout=4)
        finally:
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(timeout=2)
