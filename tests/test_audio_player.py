from __future__ import annotations

from typing import Any

import pytest

import cdflow.services.audio_player as audio_player_module
from cdflow.services.audio_player import AudioPlayer


class _SourceOnlyFactory:
    @staticmethod
    def find(name: str) -> object | None:
        return object() if name == "cdparanoiasrc" else None

    @staticmethod
    def make(*_args: Any) -> None:
        return None


class _SourceOnlyGst:
    ElementFactory = _SourceOnlyFactory


def test_audio_backend_requires_a_supported_output_sink(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(audio_player_module, "_load_gstreamer", lambda: _SourceOnlyGst)
    player = AudioPlayer()

    assert not player.available
