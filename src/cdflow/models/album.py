"""Cached album metadata model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from .track import Track


@dataclass(slots=True)
class Album:
    disc_id: str
    title: str = "Unknown Album"
    artist: str = "Unknown Artist"
    year: str = ""
    genre: str = ""
    label: str = ""
    artwork_path: str = ""
    tracks: list[Track] = field(default_factory=list)
    last_inserted: datetime = field(default_factory=lambda: datetime.now(UTC))
    ripped: bool = False

    @property
    def total_seconds(self) -> float:
        return sum(track.duration_seconds for track in self.tracks)

    @property
    def total_duration_text(self) -> str:
        total = round(self.total_seconds)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"
