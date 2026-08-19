from __future__ import annotations

import json
from pathlib import Path

from cdflow.app.demo import demo_audio_disc
from cdflow.app.settings import SettingsStore
from cdflow.app.state import ApplicationState, AppStatus
from cdflow.services.library import LibraryRepository


def test_type_corrupt_settings_fall_back_field_by_field(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    path.write_text(
        json.dumps(
            {
                "rip_format": ["flac"],
                "default_volume": {"loud": True},
                "filename_pattern": None,
                "output_directory": 42,
                "metadata_enabled": "false",
                "window_geometry": [],
            }
        ),
        encoding="utf-8",
    )

    preferences = SettingsStore(path).load()
    assert preferences.rip_format == "flac"
    assert preferences.default_volume == 72
    assert preferences.filename_pattern == "{track:02d} - {title}"
    assert preferences.output_directory.endswith("Music/CDFlow")
    assert preferences.metadata_enabled is True
    assert preferences.window_geometry == ""


def test_same_state_transition_supports_metadata_enrichment() -> None:
    state = ApplicationState()
    disc = demo_audio_disc()
    state.set_drives([disc.drive])
    state.transition(AppStatus.LOADING_DISC)
    first = state.transition(AppStatus.AUDIO_CD, disc=disc, message="generic")
    enriched = state.transition(AppStatus.AUDIO_CD, disc=disc, message="metadata loaded")

    assert enriched.generation == first.generation + 1
    assert enriched.disc is disc
    assert enriched.message == "metadata loaded"


def test_metadata_upsert_does_not_erase_existing_rip_markers(tmp_path: Path) -> None:
    disc = demo_audio_disc()
    assert disc.album is not None
    with LibraryRepository(tmp_path / "library.sqlite3") as library:
        library.upsert_album(disc.album)
        library.mark_track_ripped(disc.album.disc_id, 1)
        library.upsert_album(disc.album)
        loaded = library.get_album(disc.album.disc_id)

    assert loaded is not None
    assert loaded.tracks[0].ripped
