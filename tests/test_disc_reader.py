from __future__ import annotations

import pytest

from cdflow.services.disc_reader import (
    DiscReadError,
    DiscTOC,
    TocEntry,
    musicbrainz_disc_id,
    parse_cd_info_output,
)

CD_INFO_AUDIO = """
CD-ROM Track List (1 - 2)
  #: MSF       LSN    Type   Green? Copy?
  1: 00:02:00  000000 audio  false  no
  2: 03:07:00  013875 audio  false  no
170: 06:00:00  026850 leadout (505 MB raw, 447 MB formatted)
"""


def test_cd_info_parser_builds_absolute_offsets_and_track_durations() -> None:
    toc = parse_cd_info_output(CD_INFO_AUDIO)

    assert toc.first_track == 1
    assert toc.last_track == 2
    assert [entry.offset_frame for entry in toc.entries] == [150, 14_025]
    assert toc.leadout_frame == 27_000
    assert [track.frame_count for track in toc.to_tracks()] == [13_875, 12_975]
    assert [track.start_frame for track in toc.to_tracks()] == [0, 13_875]
    assert toc.musicbrainz_toc == "1+2+27000+150+14025"


def test_cd_info_parser_classifies_mixed_mode_tracks() -> None:
    output = CD_INFO_AUDIO.replace("2: 03:07:00  013875 audio", "2: 03:07:00  013875 mode 1 data")
    toc = parse_cd_info_output(output)

    assert toc.audio_track_count == 1
    assert toc.data_track_count == 1
    assert [track.number for track in toc.to_tracks()] == [1]


def test_cd_info_parser_rejects_an_incomplete_table() -> None:
    with pytest.raises(DiscReadError, match="complete track table"):
        parse_cd_info_output("1: 00:02:00 000000 audio")


def test_toc_rejects_nonconsecutive_or_nonincreasing_tracks() -> None:
    with pytest.raises(ValueError, match="consecutive"):
        DiscTOC((TocEntry(1, 150), TocEntry(3, 10_000)), 20_000)
    with pytest.raises(ValueError, match="increase"):
        DiscTOC((TocEntry(1, 150), TocEntry(2, 150)), 20_000)


def test_musicbrainz_disc_id_is_stable_and_url_safe() -> None:
    first = musicbrainz_disc_id(1, 2, 27_000, (150, 14_025))
    second = musicbrainz_disc_id(1, 2, 27_000, [150, 14_025])

    assert first == second == "vZqvB8Fxkr7NphatNf692p5MaEw-"
    assert len(first) == 28
    assert "+" not in first and "/" not in first and "=" not in first


@pytest.mark.parametrize(
    ("first", "last", "offsets"),
    [(0, 1, (150,)), (2, 1, (150,)), (1, 2, (150,))],
)
def test_musicbrainz_disc_id_rejects_invalid_ranges(
    first: int,
    last: int,
    offsets: tuple[int, ...],
) -> None:
    with pytest.raises(ValueError):
        musicbrainz_disc_id(first, last, 10_000, offsets)
