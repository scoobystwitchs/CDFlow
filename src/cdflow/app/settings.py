"""Small JSON-backed settings store with atomic writes and sane validation."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any

from .constants import (
    DEFAULT_ACCENT,
    DEFAULT_FILENAME_PATTERN,
    DEFAULT_MUSIC_DIR,
    DEFAULT_RIP_FORMAT,
    DEFAULT_RIP_QUALITY,
    DEFAULT_THEME,
)

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class Preferences:
    theme: str = DEFAULT_THEME
    accent: str = DEFAULT_ACCENT
    metadata_enabled: bool = True
    artwork_enabled: bool = True
    musicbrainz_contact: str = ""
    rip_format: str = DEFAULT_RIP_FORMAT
    rip_quality: str = DEFAULT_RIP_QUALITY
    output_directory: str = str(DEFAULT_MUSIC_DIR)
    filename_pattern: str = DEFAULT_FILENAME_PATTERN
    embed_metadata: bool = True
    embed_artwork: bool = True
    default_volume: int = 72
    remember_volume: bool = True
    auto_load_disc: bool = True
    auto_metadata: bool = True
    remember_window_geometry: bool = True
    window_geometry: str = ""

    def normalized(self) -> Preferences:
        defaults = Preferences()
        self.theme = self.theme if isinstance(self.theme, str) and self.theme in {"dark"} else DEFAULT_THEME
        if not _valid_hex_color(self.accent):
            self.accent = DEFAULT_ACCENT
        rip_format = self.rip_format.lower() if isinstance(self.rip_format, str) else ""
        self.rip_format = rip_format if rip_format in {"flac", "wav", "mp3"} else DEFAULT_RIP_FORMAT
        self.rip_quality = (
            self.rip_quality if isinstance(self.rip_quality, str) and self.rip_quality.strip() else DEFAULT_RIP_QUALITY
        )
        try:
            self.default_volume = max(0, min(100, int(self.default_volume)))
        except (TypeError, ValueError):
            self.default_volume = defaults.default_volume
        if not isinstance(self.filename_pattern, str) or not self.filename_pattern.strip():
            self.filename_pattern = DEFAULT_FILENAME_PATTERN
        if not isinstance(self.output_directory, str) or not self.output_directory.strip():
            self.output_directory = str(DEFAULT_MUSIC_DIR)
        if not isinstance(self.window_geometry, str):
            self.window_geometry = ""
        if not isinstance(self.musicbrainz_contact, str):
            self.musicbrainz_contact = ""
        else:
            self.musicbrainz_contact = " ".join(self.musicbrainz_contact.split())[:256]
        for name in (
            "metadata_enabled",
            "artwork_enabled",
            "embed_metadata",
            "embed_artwork",
            "remember_volume",
            "auto_load_disc",
            "auto_metadata",
            "remember_window_geometry",
        ):
            if not isinstance(getattr(self, name), bool):
                setattr(self, name, getattr(defaults, name))
        return self


class SettingsStore:
    """Persist user preferences without requiring a service or registry."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_config_dir() / "settings.json"
        self.preferences = Preferences()

    def load(self) -> Preferences:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("settings root is not an object")
            allowed = {item.name for item in fields(Preferences)}
            values = {key: value for key, value in raw.items() if key in allowed}
            self.preferences = Preferences(**values).normalized()
        except FileNotFoundError:
            self.preferences = Preferences()
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            LOGGER.warning("Could not read preferences; defaults will be used: %s", exc)
            self.preferences = Preferences()
        return self.preferences

    def update(self, **changes: Any) -> Preferences:
        known = {item.name for item in fields(Preferences)}
        unknown = set(changes) - known
        if unknown:
            raise KeyError(f"unknown preferences: {', '.join(sorted(unknown))}")
        for key, value in changes.items():
            setattr(self.preferences, key, value)
        self.preferences.normalized()
        self.save()
        return self.preferences

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(asdict(self.preferences.normalized()), indent=2, sort_keys=True) + "\n"
        temporary_name = ""
        try:
            with tempfile.NamedTemporaryFile(
                "w", encoding="utf-8", dir=self.path.parent, prefix=".settings-", suffix=".tmp", delete=False
            ) as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_name = handle.name
            os.replace(temporary_name, self.path)
        finally:
            if temporary_name:
                with suppress(OSError):
                    Path(temporary_name).unlink(missing_ok=True)


def default_config_dir() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    return Path(config_home) / "cdflow" if config_home else Path.home() / ".config" / "cdflow"


def default_cache_dir() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    return Path(cache_home) / "cdflow" if cache_home else Path.home() / ".cache" / "cdflow"


def default_data_dir() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    return Path(data_home) / "cdflow" if data_home else Path.home() / ".local" / "share" / "cdflow"


def _valid_hex_color(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 7 or not value.startswith("#"):
        return False
    try:
        int(value[1:], 16)
    except ValueError:
        return False
    return True
