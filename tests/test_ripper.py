from __future__ import annotations

from pathlib import Path

import pytest

from cdflow.models import Album, Track
from cdflow.services.ripper import (
    RipFormat,
    RipJob,
    RipOptions,
    _flac_quality_args,
    _mp3_quality_args,
    estimate_required_space,
    parse_ffmpeg_audio_encoders,
    render_filename,
    sanitize_filename_component,
    unique_output_path,
)


def album_and_tracks() -> tuple[Album, tuple[Track, ...]]:
    tracks = (
        Track(1, "A / B", artist="Artist", frame_count=75_000),
        Track(2, "Second", artist="Artist", frame_count=37_500, selected_for_ripping=False),
    )
    return Album("disc", title="Album", artist="Artist", year="2000", tracks=list(tracks)), tracks


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("../A/B\\C", "_A_B_C"),
        ("  many\t spaces  ", "many spaces"),
        ("CON", "_CON"),
        ("\x00\x01", "Untitled"),
        ("normal title", "normal title"),
    ],
)
def test_filename_component_is_safe(raw: str, expected: str) -> None:
    assert sanitize_filename_component(raw) == expected


def test_filename_component_respects_utf8_byte_limit() -> None:
    result = sanitize_filename_component("é" * 200, max_bytes=31)
    assert len(result.encode()) <= 31
    assert result


def test_filename_pattern_renders_documented_fields_without_traversal() -> None:
    album, tracks = album_and_tracks()
    assert render_filename("{track:02d} - {title} - {album}", tracks[0], album) == "01 - A _ B - Album"
    with pytest.raises(ValueError, match="unknown filename field"):
        render_filename("{title.__class__}", tracks[0], album)
    with pytest.raises(ValueError, match="nested"):
        render_filename("{title:{track}}", tracks[0], album)
    with pytest.raises(ValueError, match="unsupported filename format"):
        render_filename("{title:>100000000}", tracks[0], album)


def test_unique_output_path_never_silently_overwrites(tmp_path: Path) -> None:
    original = tmp_path / "track.flac"
    original.write_bytes(b"existing")
    reserved = {tmp_path / "track (2).flac"}
    assert unique_output_path(original, reserved=reserved) == tmp_path / "track (3).flac"
    assert original.read_bytes() == b"existing"


def test_rip_job_selection_and_space_estimate() -> None:
    album, tracks = album_and_tracks()
    job = RipJob("/dev/sr9", album, tracks, RipOptions(format=RipFormat.FLAC))
    assert [track.number for track in job.selected_tracks] == [1]
    assert estimate_required_space(job) > tracks[0].frame_count * 2352


def test_rip_job_rejects_empty_device_and_duplicate_tracks() -> None:
    album, tracks = album_and_tracks()
    with pytest.raises(ValueError, match="device path"):
        RipJob("", album, tracks)
    with pytest.raises(ValueError, match="duplicate"):
        RipJob("/dev/sr0", album, (tracks[0], tracks[0]))
    with pytest.raises(ValueError, match="too long"):
        RipOptions(filename_pattern="x" * 513)


def test_ffmpeg_audio_encoder_parser_ignores_video_and_headers() -> None:
    output = """
 Encoders:
 V....D h264 Encoder
 A....D flac FLAC encoder
 A..... libmp3lame MP3 encoder
 """

    assert parse_ffmpeg_audio_encoders(output) == {"flac", "libmp3lame"}


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Lossless (Fast)", ["-compression_level", "3"]),
        ("Lossless (Level 5)", ["-compression_level", "5"]),
        ("Lossless (Maximum)", ["-compression_level", "12"]),
    ],
)
def test_flac_quality_labels_match_the_ui(label: str, expected: list[str]) -> None:
    assert _flac_quality_args(label) == expected


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("320 kbps", ["-b:a", "320k"]),
        ("V0 Variable", ["-q:a", "0"]),
        ("V9", ["-q:a", "9"]),
    ],
)
def test_mp3_quality_labels_match_the_ui(label: str, expected: list[str]) -> None:
    assert _mp3_quality_args(label) == expected
