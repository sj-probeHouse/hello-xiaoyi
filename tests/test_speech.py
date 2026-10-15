import asyncio
from dataclasses import replace

import pytest

from xiaoyi.config import Settings
from xiaoyi.services import ServiceError, synthesize


def test_audio_cache_keys_and_cleanup(tmp_path, monkeypatch):
    calls = []

    class FakeSpeech:
        def __init__(self, text, voice, rate):
            calls.append((text, voice, rate))

        async def save(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"fake-mp3")

    monkeypatch.setattr("xiaoyi.services.edge_tts.Communicate", FakeSpeech)

    async def run():
        settings = Settings()
        first = await synthesize("attention", settings, tmp_path)
        assert first.read_bytes() == b"fake-mp3"
        assert await synthesize("attention", settings, tmp_path) == first
        assert len(calls) == 1
        other = await synthesize("attention", replace(settings, rate=10), tmp_path)
        assert first != other
        assert calls[-1][2] == "+10%"
        assert not list(tmp_path.glob("*.part"))

    asyncio.run(run())


@pytest.mark.parametrize("cancel", [False, True])
def test_speech_failure_or_cancellation_leaves_no_partial_file(tmp_path, monkeypatch, cancel):
    class BrokenSpeech:
        def __init__(self, *args, **kwargs):
            pass

        async def save(self, path):
            from pathlib import Path

            Path(path).write_bytes(b"partial")
            if cancel:
                raise asyncio.CancelledError()
            raise RuntimeError("remote secret failure")

    monkeypatch.setattr("xiaoyi.services.edge_tts.Communicate", BrokenSpeech)

    async def run():
        with pytest.raises(asyncio.CancelledError if cancel else ServiceError):
            await synthesize("word", Settings(), tmp_path)
        assert not list(tmp_path.iterdir())

    asyncio.run(run())
