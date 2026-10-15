import os
from pathlib import Path

from scripts.build import build_environment


def test_packager_does_not_resolve_dlls_from_unrelated_applications(monkeypatch):
    monkeypatch.setenv("PATH", r"D:\UnrelatedApp\poppler;D:\OtherApp\Qt")
    env = build_environment()
    assert "UnrelatedApp" not in env["PATH"]
    assert "OtherApp" not in env["PATH"]
    assert str(Path(os.environ["SystemRoot"]) / "System32") in env["PATH"]
