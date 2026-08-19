from __future__ import annotations

import pytest

from cdflow.models.album import Album
from cdflow.models.disc import Disc, DiscKind, Drive
from cdflow.models.track import CD_FRAMES_PER_SECOND, Track


def test_track_converts_red_book_frames_to_time() -> None:
    track = Track(number=1, title="Opening", frame_count=185 * CD_FRAMES_PER_SECOND)

    assert track.duration_seconds == 185
    assert track.duration_milliseconds == 185_000
    assert track.duration_text == "3:05"


def test_track_formats_hour_long_duration() -> None:
    track = Track(number=1, title="Long mix", frame_count=3_661 * CD_FRAMES_PER_SECOND)

    assert track.duration_text == "1:01:01"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"number": 0, "title": "Invalid"}, "track number"),
        ({"number": 1, "title": "Invalid", "start_frame": -1}, "cannot be negative"),
        ({"number": 1, "title": "Invalid", "frame_count": -1}, "cannot be negative"),
    ],
)
def test_track_rejects_invalid_cd_coordinates(kwargs: dict[str, object], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        Track(**kwargs)  # type: ignore[arg-type]


def test_track_metadata_update_preserves_sector_data_and_original() -> None:
    original = Track(number=2, title="Track 02", artist="Unknown Artist", start_frame=150, frame_count=750)

    renamed = original.with_metadata(title="Known title", artist="Known artist")

    assert renamed.title == "Known title"
    assert renamed.artist == "Known artist"
    assert renamed.start_frame == original.start_frame
    assert renamed.frame_count == original.frame_count
    assert original.title == "Track 02"


def test_album_sums_and_formats_track_durations() -> None:
    album = Album(
        disc_id="example",
        tracks=[
            Track(number=1, title="A", frame_count=125 * CD_FRAMES_PER_SECOND),
            Track(number=2, title="B", frame_count=120 * CD_FRAMES_PER_SECOND),
        ],
    )

    assert album.total_seconds == 245
    assert album.total_duration_text == "4:05"


def test_drive_display_name_is_clean_and_has_a_fallback() -> None:
    assert Drive(object_path="/drive/1", vendor=" HL-DT-ST ", model=" DVD-RW ").display_name == "HL-DT-ST DVD-RW"
    assert Drive(object_path="/drive/2", model="").display_name == "Optical Drive"


@pytest.mark.parametrize(
    ("kind", "label"),
    [
        (DiscKind.NONE, "No media"),
        (DiscKind.AUDIO, "Audio CD"),
        (DiscKind.DATA, "Data CD"),
        (DiscKind.MIXED, "Mixed-mode CD"),
        (DiscKind.UNSUPPORTED, "Unsupported media"),
    ],
)
def test_disc_kind_has_a_human_readable_label(kind: DiscKind, label: str) -> None:
    disc = Disc(kind=kind, drive=Drive(object_path="/drive/1"))

    assert disc.media_type_text == label


def test_disc_primary_mount_point_is_deterministic() -> None:
    drive = Drive(object_path="/drive/1")

    assert Disc(kind=DiscKind.DATA, drive=drive).primary_mount_point == ""
    assert (
        Disc(kind=DiscKind.DATA, drive=drive, mount_points=("/run/media/a", "/run/media/b")).primary_mount_point
        == "/run/media/a"
    )
