from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from cdflow.models.album import Album
from cdflow.models.track import Track
from cdflow.services.library import LibraryRepository, default_library_path


def make_album(
    disc_id: str = "disc-1",
    *,
    title: str = "Album",
    when: datetime | None = None,
    tracks: int = 2,
) -> Album:
    return Album(
        disc_id=disc_id,
        title=title,
        artist="Artist",
        year="2001",
        genre="Rock",
        label="Label",
        tracks=[
            Track(
                number=number,
                title=f"Track {number:02d}",
                artist="Artist",
                start_frame=(number - 1) * 7_500,
                frame_count=7_500,
                selected_for_ripping=number % 2 == 1,
            )
            for number in range(1, tracks + 1)
        ],
        last_inserted=when or datetime(2026, 1, 1, tzinfo=UTC),
    )


def test_album_and_tracks_round_trip_through_embedded_database(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "library.sqlite3"
    album = make_album()

    with LibraryRepository(path) as library:
        library.upsert_album(album)
        loaded = library.get_album(album.disc_id)

    assert loaded is not None
    assert loaded is not album
    assert loaded.title == album.title
    assert loaded.artist == album.artist
    assert loaded.last_inserted == album.last_inserted
    assert [(track.number, track.title) for track in loaded.tracks] == [(1, "Track 01"), (2, "Track 02")]
    assert loaded.tracks[0].selected_for_ripping is True
    assert loaded.tracks[1].selected_for_ripping is False


def test_upsert_replaces_stale_track_rows(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    with LibraryRepository(path) as library:
        library.upsert_album(make_album(tracks=3))
        library.upsert_album(make_album(title="Renamed", tracks=1))

        loaded = library.get_album("disc-1")

    assert loaded is not None
    assert loaded.title == "Renamed"
    assert [track.number for track in loaded.tracks] == [1]


def test_collection_is_persistent_and_sorted_by_last_insertion(tmp_path: Path) -> None:
    path = tmp_path / "library.sqlite3"
    with LibraryRepository(path) as library:
        library.upsert_album(make_album("older", title="Older", when=datetime(2025, 1, 1, tzinfo=UTC)))
        library.upsert_album(make_album("newer", title="Newer", when=datetime(2026, 1, 1, tzinfo=UTC)))

    with LibraryRepository(path) as reopened:
        albums = reopened.list_albums(limit=1)

    assert [album.disc_id for album in albums] == ["newer"]


@pytest.mark.parametrize(("limit", "offset"), [(0, 0), (-1, 0), (10, -1)])
def test_collection_pagination_rejects_invalid_ranges(tmp_path: Path, limit: int, offset: int) -> None:
    with (
        LibraryRepository(tmp_path / "library.sqlite3") as library,
        pytest.raises(ValueError, match="limit must be positive"),
    ):
        library.list_albums(limit=limit, offset=offset)


def test_rip_markers_only_complete_album_after_every_track(tmp_path: Path) -> None:
    with LibraryRepository(tmp_path / "library.sqlite3") as library:
        library.upsert_album(make_album())

        assert library.mark_track_ripped("disc-1", 1)
        assert library.get_album("disc-1").ripped is False  # type: ignore[union-attr]
        assert library.mark_track_ripped("disc-1", 2)
        assert library.get_album("disc-1").ripped is True  # type: ignore[union-attr]
        assert not library.mark_track_ripped("missing", 1)
        assert library.mark_ripped("disc-1", False)
        assert library.get_album("disc-1").ripped is False  # type: ignore[union-attr]


def test_artwork_update_and_unknown_album_result(tmp_path: Path) -> None:
    with LibraryRepository(tmp_path / "library.sqlite3") as library:
        library.upsert_album(make_album())

        assert library.set_artwork("disc-1", tmp_path / "cover.jpg")
        assert library.get_album("disc-1").artwork_path == str(tmp_path / "cover.jpg")  # type: ignore[union-attr]
        assert not library.set_artwork("missing", tmp_path / "cover.jpg")


def test_metadata_cache_round_trip_preserves_unicode_and_etag(tmp_path: Path) -> None:
    fetched_at = datetime(2026, 8, 18, 12, tzinfo=UTC)
    payload = {"artist": "Beyoncé", "releases": [{"id": "one"}]}

    with LibraryRepository(tmp_path / "library.sqlite3") as library:
        library.put_metadata_cache("disc-1", payload, etag='"revision-1"', fetched_at=fetched_at)
        entry = library.get_metadata_cache("disc-1", max_age=None)

    assert entry is not None
    assert entry.payload == payload
    assert entry.payload is not payload
    assert entry.fetched_at == fetched_at
    assert entry.etag == '"revision-1"'


def test_expired_metadata_cache_is_a_miss(tmp_path: Path) -> None:
    with LibraryRepository(tmp_path / "library.sqlite3") as library:
        library.put_metadata_cache(
            "disc-1",
            {"title": "Old"},
            fetched_at=datetime.now(UTC) - timedelta(days=2),
        )

        assert library.get_metadata_cache("disc-1", max_age=timedelta(hours=1)) is None
        assert library.get_metadata_cache("disc-1", max_age=None) is not None


def test_metadata_cache_rejects_an_empty_identifier(tmp_path: Path) -> None:
    with (
        LibraryRepository(tmp_path / "library.sqlite3") as library,
        pytest.raises(ValueError, match="disc ID cannot be empty"),
    ):
        library.put_metadata_cache("", {})


def test_future_schema_is_not_opened_by_an_older_application(tmp_path: Path) -> None:
    path = tmp_path / "future.sqlite3"
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA user_version = 999")
    connection.close()

    with pytest.raises(RuntimeError, match="newer than supported"):
        LibraryRepository(path)


def test_default_library_path_honors_xdg_data_home(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    assert default_library_path() == tmp_path / "data" / "cdflow" / "library.sqlite3"
