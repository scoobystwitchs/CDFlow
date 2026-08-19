from __future__ import annotations

import json
from pathlib import Path

import pytest

from cdflow.app.constants import DEFAULT_ACCENT, DEFAULT_FILENAME_PATTERN, DEFAULT_MUSIC_DIR, DEFAULT_RIP_FORMAT
from cdflow.app.settings import Preferences, SettingsStore, default_cache_dir, default_config_dir, default_data_dir


def test_preferences_normalize_user_controlled_values() -> None:
    preferences = Preferences(
        theme="unknown",
        accent="pink",
        rip_format="MP3",
        default_volume=400,
        filename_pattern="   ",
        output_directory="",
        musicbrainz_contact="  maintainer@example.test\n",
    ).normalized()

    assert preferences.theme == "dark"
    assert preferences.accent == DEFAULT_ACCENT
    assert preferences.rip_format == "mp3"
    assert preferences.default_volume == 100
    assert preferences.filename_pattern == DEFAULT_FILENAME_PATTERN
    assert preferences.output_directory == str(DEFAULT_MUSIC_DIR)
    assert preferences.musicbrainz_contact == "maintainer@example.test"


def test_settings_round_trip_and_ignore_unknown_forward_fields(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "settings.json"
    store = SettingsStore(path)
    updated = store.update(accent="#123aBC", rip_format="WAV", default_volume=-5)

    payload = json.loads(path.read_text(encoding="utf-8"))
    payload["future_setting"] = "safe to ignore"
    path.write_text(json.dumps(payload), encoding="utf-8")
    loaded = SettingsStore(path).load()

    assert updated.rip_format == "wav"
    assert loaded.accent == "#123aBC"
    assert loaded.default_volume == 0
    assert not list(path.parent.glob(".settings-*.tmp"))


def test_malformed_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("{not JSON", encoding="utf-8")

    loaded = SettingsStore(path).load()

    assert loaded == Preferences()


def test_non_object_settings_fall_back_to_defaults(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text("[]", encoding="utf-8")

    assert SettingsStore(path).load() == Preferences()


def test_updating_an_unknown_preference_is_rejected_without_writing(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    store = SettingsStore(path)

    with pytest.raises(KeyError, match="unknown preferences: typo"):
        store.update(typo=True)

    assert not path.exists()


def test_xdg_locations_honor_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    config = tmp_path / "config"
    cache = tmp_path / "cache"
    data = tmp_path / "data"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    monkeypatch.setenv("XDG_DATA_HOME", str(data))

    assert default_config_dir() == config / "cdflow"
    assert default_cache_dir() == cache / "cdflow"
    assert default_data_dir() == data / "cdflow"


def test_missing_settings_file_uses_runtime_defaults(tmp_path: Path) -> None:
    loaded = SettingsStore(tmp_path / "missing.json").load()

    assert loaded.rip_format == DEFAULT_RIP_FORMAT
    assert loaded.output_directory == str(DEFAULT_MUSIC_DIR)
