from __future__ import annotations

import os
import sys

import pytest

from cdflow.services.subprocess_env import host_process_environment


def test_source_process_environment_is_preserved(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/custom/libs")
    monkeypatch.setenv("GST_PLUGIN_PATH", "/custom/plugins")

    environment = host_process_environment(gstreamer=True)

    assert environment["LD_LIBRARY_PATH"] == "/custom/libs"
    assert environment["GST_PLUGIN_PATH"] == "/custom/plugins"


def test_frozen_host_environment_restores_loader_and_gstreamer_paths(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/libs")
    monkeypatch.setenv("LD_LIBRARY_PATH_ORIG", "/user/libs")
    for name in ("GST_PLUGIN_PATH", "GST_PLUGIN_SYSTEM_PATH", "GST_REGISTRY", "GST_REGISTRY_FORK"):
        monkeypatch.setenv(name, f"/bundle/{name.casefold()}")

    environment = host_process_environment(gstreamer=True)

    assert environment["LD_LIBRARY_PATH"] == "/user/libs"
    assert "LD_LIBRARY_PATH_ORIG" not in environment
    assert not any(name.startswith("GST_") for name in environment)


def test_frozen_host_environment_removes_bundle_loader_without_original(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("LD_LIBRARY_PATH", "/bundle/libs")
    monkeypatch.delenv("LD_LIBRARY_PATH_ORIG", raising=False)

    environment = host_process_environment()

    assert "LD_LIBRARY_PATH" not in environment
    assert environment.get("PATH") == os.environ.get("PATH")
