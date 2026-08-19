"""Audio-track model and Red Book time conversion helpers."""

from __future__ import annotations

from dataclasses import dataclass, replace

CD_FRAMES_PER_SECOND = 75


@dataclass(slots=True, frozen=True)
class Track:
    """A single CDDA track.

    Sector values use the disc's logical frame offsets (75 frames per second).
    ``start_frame`` may be zero for tools that omit the standard 150-frame lead-in.
    """

    number: int
    title: str
    artist: str = "Unknown Artist"
    start_frame: int = 0
    frame_count: int = 0
    selected_for_ripping: bool = True
    ripped: bool = False

    def __post_init__(self) -> None:
        if self.number < 1:
            raise ValueError("track number must be positive")
        if self.start_frame < 0 or self.frame_count < 0:
            raise ValueError("CD frame values cannot be negative")

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / CD_FRAMES_PER_SECOND

    @property
    def duration_milliseconds(self) -> int:
        return round(self.duration_seconds * 1000)

    @property
    def duration_text(self) -> str:
        total = round(self.duration_seconds)
        hours, remainder = divmod(total, 3600)
        minutes, seconds = divmod(remainder, 60)
        return f"{hours:d}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:d}:{seconds:02d}"

    def with_metadata(self, *, title: str | None = None, artist: str | None = None) -> Track:
        return replace(self, title=title or self.title, artist=artist or self.artist)
