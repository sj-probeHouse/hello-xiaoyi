import asyncio
import json

import httpx
import pytest

from xiaoyi.config import Settings
from xiaoyi.services import ServiceError, TranslationService


def stream_response(text="注意力"):
    body = "".join(
        "data: " + json.dumps({"choices": [{"delta": {"content": char}}]}) + "\n\n" for char in text
    )
    return httpx.Response(200, text=body + "data: [DONE]\n\n")


def test_stream_cache_and_configuration_isolation():
    async def run():
        requests = []

        def handle(request):
            requests.append(request)
            return stream_response()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            service = TranslationService(client)
            settings = Settings()
            chunks = []
            assert (
                await service.translate("attention", settings, "test-key", chunks.append)
                == "注意力"
            )
            assert chunks == ["注", "意", "力"]
            await service.translate("attention", settings, "test-key", lambda _: None)
            assert len(requests) == 1
            settings.domain = "医学"
            await service.translate("attention", settings, "test-key", lambda _: None)
            await service.translate("attention", settings, "other-key", lambda _: None)
            assert len(requests) == 3
            payload = json.loads(requests[0].content)
            assert payload["stream"] is True
            assert payload["thinking"] == {"type": "disabled"}

    asyncio.run(run())


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_api_errors_do_not_expose_response_or_key(status):
    async def run():
        transport = httpx.MockTransport(lambda _: httpx.Response(status, text="SECRET-RESPONSE"))
        async with httpx.AsyncClient(transport=transport) as client:
            with pytest.raises(ServiceError) as caught:
                await TranslationService(client).translate("word", Settings(), "SECRET-KEY", print)
            assert "SECRET" not in str(caught.value)

    asyncio.run(run())


def test_missing_key_and_incomplete_stream():
    async def run():
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(lambda _: httpx.Response(200, text="data: {broken}\n\n"))
        ) as client:
            service = TranslationService(client)
            with pytest.raises(ServiceError, match="密钥"):
                await service.translate("word", Settings(), "", print)
            with pytest.raises(ServiceError):
                await service.translate("word", Settings(), "key", print)

    asyncio.run(run())


def test_explicit_connection_test_bypasses_cached_translation():
    async def run():
        calls = []

        def handle(request):
            calls.append(request)
            return stream_response() if len(calls) == 1 else httpx.Response(401)

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            service = TranslationService(client)
            await service.translate("attention", Settings(), "key", lambda _: None)
            with pytest.raises(ServiceError, match="认证"):
                await service.translate(
                    "attention", Settings(), "key", lambda _: None, use_cache=False
                )
            assert len(calls) == 2

    asyncio.run(run())
