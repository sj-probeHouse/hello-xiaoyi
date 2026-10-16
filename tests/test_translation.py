import asyncio
import json
from dataclasses import replace

import httpx
import pytest

from xiaoyi.config import Settings
from xiaoyi.services import ServiceError, TranslationService


@pytest.mark.parametrize("region", ["中国", "新加坡", "欧洲"])
def test_token_plan_uses_own_endpoint_and_mimo_auth(region):
    from xiaoyi.config import PRESETS

    provider = f"MiMo Token Plan · {region}"
    base, model = PRESETS[provider]

    async def run():
        requests = []

        def handle(request):
            requests.append(request)
            return stream_response()

        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as client:
            settings = replace(Settings(), provider=provider, base_url=base, model=model)
            await TranslationService(client).translate(
                "word", settings, "tp-example", lambda _: None
            )
        assert str(requests[0].url) == base + "/chat/completions"
        assert requests[0].headers["api-key"] == "tp-example"
        assert "authorization" not in requests[0].headers
        assert json.loads(requests[0].content)["thinking"] == {"type": "disabled"}

    asyncio.run(run())


@pytest.mark.parametrize(
    "base,key,hint",
    [
        ("https://api.xiaomimimo.com/v1", "tp-example", "Token Plan"),
        ("https://api.xiaomimimo.com/v1", "ttp-example", "Token Plan"),
        ("https://token-plan-cn.xiaomimimo.com/v1", "sk-example", "按量"),
        ("https://token-plan-sgp.xiaomimimo.com/v1", "sk-example", "按量"),
        ("https://token-plan-ams.xiaomimimo.com/v1", "sk-example", "按量"),
        ("https://token-plan-cn.xiaomimimo.com/v1", "MiMokey:tp-example", "MiMokey"),
        ("https://token-plan-cn.xiaomimimo.com/v1", "tp-exam ple", "空格"),
    ],
)
def test_bad_key_configuration_is_rejected_without_sending(base, key, hint):
    async def run():
        requests = []
        transport = httpx.MockTransport(lambda r: requests.append(r) or stream_response())
        async with httpx.AsyncClient(transport=transport) as client:
            settings = replace(Settings(), provider="MiMo", base_url=base)
            with pytest.raises(ServiceError, match=hint) as caught:
                await TranslationService(client).translate("word", settings, key, lambda _: None)
        assert not requests
        assert key not in str(caught.value)

    asyncio.run(run())


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
