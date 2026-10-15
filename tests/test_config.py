import json
from dataclasses import replace

import pytest

from xiaoyi.config import Settings, credential_name, get_key, load_settings, save_settings, set_key


def test_settings_roundtrip_and_unknown_fields(tmp_path):
    path = tmp_path / "prefs.json"
    assert load_settings(path) == Settings()
    settings = replace(Settings(), rate=15, domain="Computer architecture")
    save_settings(settings, path)
    assert load_settings(path) == settings
    data = json.loads(path.read_text(encoding="utf-8"))
    assert not any("key" in key.lower() for key in data)
    data["future_field"] = 1
    path.write_text(json.dumps(data), encoding="utf-8")
    assert load_settings(path) == settings


@pytest.mark.parametrize("content", ["{broken", "[]", '{"rate": "fast"}', '{"voice": null}'])
def test_corrupt_settings_are_not_overwritten(tmp_path, content):
    path = tmp_path / "prefs.json"
    path.write_text(content, encoding="utf-8")
    with pytest.raises(ValueError, match="备份"):
        load_settings(path)
    assert path.read_text(encoding="utf-8") == content


@pytest.mark.parametrize(
    "change",
    [
        {"base_url": "http://example.com"},
        {"base_url": "https://key@example.com"},
        {"base_url": "https://example.com?key=secret"},
        {"base_url": "https://example.com/#secret"},
        {"model": ""},
        {"domain": "a" * 501},
        {"rate": 101},
        {"speech_backend": "unknown"},
        {"voice": "untrusted"},
    ],
)
def test_invalid_settings_rejected(change):
    with pytest.raises(ValueError):
        replace(Settings(), **change).validate()


def test_credentials_roundtrip_isolated_from_real_providers():
    # Uses a dedicated test target, removed in finally. Never reads the user's provider credentials.
    base = "https://hello-xiaoyi-unit-test.invalid/v1"
    try:
        set_key(base, "测试-only-not-a-real-api-key")
        assert get_key(base) == "测试-only-not-a-real-api-key"
        assert credential_name(base) == credential_name(base + "/")
        assert credential_name(base) != credential_name("https://other.invalid")
        set_key(base, "")
        assert get_key(base) == ""
        set_key(base, "")  # deleting an absent target is harmless
    finally:
        set_key(base, "")
