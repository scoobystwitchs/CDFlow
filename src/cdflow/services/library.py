"""Embedded SQLite collection and metadata cache."""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cdflow.models.album import Album
from cdflow.models.track import Track

SCHEMA_VERSION = 1
DEFAULT_METADATA_MAX_AGE = timedelta(days=30)


def default_library_path() -> Path:
    data_home = os.environ.get("XDG_DATA_HOME")
    root = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return root / "cdflow" / "library.sqlite3"


@dataclass(frozen=True, slots=True)
class MetadataCacheEntry:
    disc_id: str
    payload: dict[str, Any]
    fetched_at: datetime
    etag: str = ""


class LibraryRepository:
    """Thread-safe local collection.

    One connection is shared behind a re-entrant lock.  SQLite WAL mode lets
    readers in other processes continue while CDFlow commits a small update.
    All public methods return detached model objects.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        raw_path = str(path) if path is not None else str(default_library_path())
        self.path = Path(raw_path) if raw_path != ":memory:" else Path(":memory:")
        if raw_path != ":memory:":
            self.path.expanduser().parent.mkdir(parents=True, exist_ok=True)
            raw_path = str(self.path.expanduser())
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(raw_path, timeout=5.0, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        self._connection.execute("PRAGMA journal_mode = WAL")
        self._migrate()

    def _migrate(self) -> None:
        with self._lock, self._connection:
            version = int(self._connection.execute("PRAGMA user_version").fetchone()[0])
            if version > SCHEMA_VERSION:
                raise RuntimeError(f"library schema {version} is newer than supported version {SCHEMA_VERSION}")
            if version < 1:
                self._connection.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS albums (
                        disc_id TEXT PRIMARY KEY,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        year TEXT NOT NULL DEFAULT '',
                        genre TEXT NOT NULL DEFAULT '',
                        label TEXT NOT NULL DEFAULT '',
                        artwork_path TEXT NOT NULL DEFAULT '',
                        last_inserted TEXT NOT NULL,
                        ripped INTEGER NOT NULL DEFAULT 0
                    );

                    CREATE TABLE IF NOT EXISTS tracks (
                        disc_id TEXT NOT NULL REFERENCES albums(disc_id) ON DELETE CASCADE,
                        number INTEGER NOT NULL,
                        title TEXT NOT NULL,
                        artist TEXT NOT NULL,
                        start_frame INTEGER NOT NULL DEFAULT 0,
                        frame_count INTEGER NOT NULL DEFAULT 0,
                        selected_for_ripping INTEGER NOT NULL DEFAULT 1,
                        ripped INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY (disc_id, number)
                    );

                    CREATE TABLE IF NOT EXISTS metadata_cache (
                        disc_id TEXT PRIMARY KEY,
                        payload TEXT NOT NULL,
                        fetched_at TEXT NOT NULL,
                        etag TEXT NOT NULL DEFAULT ''
                    );

                    CREATE INDEX IF NOT EXISTS albums_last_inserted_idx
                        ON albums(last_inserted DESC);
                    PRAGMA user_version = 1;
                    """
                )

    def close(self) -> None:
        with self._lock:
            self._connection.close()

    def __enter__(self) -> LibraryRepository:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def upsert_album(self, album: Album) -> None:
        if not album.disc_id:
            raise ValueError("cannot cache an album without a disc ID")
        inserted = _as_utc(album.last_inserted).isoformat()
        with self._lock, self._connection:
            existing_track_rows = self._connection.execute(
                "SELECT number, ripped FROM tracks WHERE disc_id = ?",
                (album.disc_id,),
            ).fetchall()
            existing_ripped = {int(row["number"]): bool(row["ripped"]) for row in existing_track_rows}
            self._connection.execute(
                """
                INSERT INTO albums (
                    disc_id, title, artist, year, genre, label, artwork_path,
                    last_inserted, ripped
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(disc_id) DO UPDATE SET
                    title = excluded.title,
                    artist = excluded.artist,
                    year = excluded.year,
                    genre = excluded.genre,
                    label = excluded.label,
                    artwork_path = excluded.artwork_path,
                    last_inserted = excluded.last_inserted,
                    ripped = MAX(albums.ripped, excluded.ripped)
                """,
                (
                    album.disc_id,
                    album.title,
                    album.artist,
                    album.year,
                    album.genre,
                    album.label,
                    album.artwork_path,
                    inserted,
                    int(album.ripped),
                ),
            )
            self._connection.execute("DELETE FROM tracks WHERE disc_id = ?", (album.disc_id,))
            self._connection.executemany(
                """
                INSERT INTO tracks (
                    disc_id, number, title, artist, start_frame, frame_count,
                    selected_for_ripping, ripped
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    (
                        album.disc_id,
                        track.number,
                        track.title,
                        track.artist,
                        track.start_frame,
                        track.frame_count,
                        int(track.selected_for_ripping),
                        int(track.ripped or existing_ripped.get(track.number, False)),
                    )
                    for track in album.tracks
                ],
            )

    def get_album(self, disc_id: str) -> Album | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM albums WHERE disc_id = ?", (disc_id,)).fetchone()
            if row is None:
                return None
            tracks = self._tracks_for(disc_id)
        return _album_from_row(row, tracks)

    def list_albums(self, *, limit: int = 500, offset: int = 0) -> list[Album]:
        if limit < 1 or offset < 0:
            raise ValueError("limit must be positive and offset cannot be negative")
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM albums ORDER BY last_inserted DESC, title COLLATE NOCASE LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
            albums = [_album_from_row(row, self._tracks_for(str(row["disc_id"]))) for row in rows]
        return albums

    def touch_album(self, disc_id: str, when: datetime | None = None) -> bool:
        timestamp = _as_utc(when or datetime.now(UTC)).isoformat()
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE albums SET last_inserted = ? WHERE disc_id = ?", (timestamp, disc_id)
            )
            return cursor.rowcount > 0

    def mark_ripped(self, disc_id: str, ripped: bool = True) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute("UPDATE albums SET ripped = ? WHERE disc_id = ?", (int(ripped), disc_id))
            return cursor.rowcount > 0

    def mark_track_ripped(self, disc_id: str, track_number: int, ripped: bool = True) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE tracks SET ripped = ? WHERE disc_id = ? AND number = ?",
                (int(ripped), disc_id, track_number),
            )
            if cursor.rowcount:
                remaining = self._connection.execute(
                    "SELECT COUNT(*) FROM tracks WHERE disc_id = ? AND ripped = 0", (disc_id,)
                ).fetchone()[0]
                if int(remaining) == 0:
                    self._connection.execute("UPDATE albums SET ripped = 1 WHERE disc_id = ?", (disc_id,))
            return cursor.rowcount > 0

    def set_artwork(self, disc_id: str, artwork_path: str | Path) -> bool:
        with self._lock, self._connection:
            cursor = self._connection.execute(
                "UPDATE albums SET artwork_path = ? WHERE disc_id = ?",
                (str(artwork_path), disc_id),
            )
            return cursor.rowcount > 0

    def put_metadata_cache(
        self,
        disc_id: str,
        payload: dict[str, Any],
        *,
        etag: str = "",
        fetched_at: datetime | None = None,
    ) -> None:
        if not disc_id:
            raise ValueError("disc ID cannot be empty")
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        timestamp = _as_utc(fetched_at or datetime.now(UTC)).isoformat()
        with self._lock, self._connection:
            self._connection.execute(
                """
                INSERT INTO metadata_cache (disc_id, payload, fetched_at, etag)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(disc_id) DO UPDATE SET
                    payload = excluded.payload,
                    fetched_at = excluded.fetched_at,
                    etag = excluded.etag
                """,
                (disc_id, encoded, timestamp, etag),
            )

    def get_metadata_cache(
        self,
        disc_id: str,
        *,
        max_age: timedelta | None = DEFAULT_METADATA_MAX_AGE,
    ) -> MetadataCacheEntry | None:
        with self._lock:
            row = self._connection.execute("SELECT * FROM metadata_cache WHERE disc_id = ?", (disc_id,)).fetchone()
        if row is None:
            return None
        try:
            fetched_at = _parse_datetime(str(row["fetched_at"]))
            payload = json.loads(str(row["payload"]))
        except (ValueError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        if max_age is not None and datetime.now(UTC) - fetched_at > max_age:
            return None
        return MetadataCacheEntry(disc_id, payload, fetched_at, str(row["etag"]))

    def _tracks_for(self, disc_id: str) -> list[Track]:
        rows = self._connection.execute("SELECT * FROM tracks WHERE disc_id = ? ORDER BY number", (disc_id,)).fetchall()
        return [
            Track(
                number=int(row["number"]),
                title=str(row["title"]),
                artist=str(row["artist"]),
                start_frame=int(row["start_frame"]),
                frame_count=int(row["frame_count"]),
                selected_for_ripping=bool(row["selected_for_ripping"]),
                ripped=bool(row["ripped"]),
            )
            for row in rows
        ]


def _album_from_row(row: sqlite3.Row, tracks: list[Track]) -> Album:
    return Album(
        disc_id=str(row["disc_id"]),
        title=str(row["title"]),
        artist=str(row["artist"]),
        year=str(row["year"]),
        genre=str(row["genre"]),
        label=str(row["label"]),
        artwork_path=str(row["artwork_path"]),
        tracks=tracks,
        last_inserted=_parse_datetime(str(row["last_inserted"])),
        ripped=bool(row["ripped"]),
    )


def _parse_datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _as_utc(parsed)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


__all__ = [
    "DEFAULT_METADATA_MAX_AGE",
    "LibraryRepository",
    "MetadataCacheEntry",
    "default_library_path",
]
