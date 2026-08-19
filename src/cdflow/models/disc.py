"""Optical drive and inserted-disc domain models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from .album import Album


class DiscKind(StrEnum):
    NONE = "none"
    AUDIO = "audio"
    DATA = "data"
    MIXED = "mixed"
    UNSUPPORTED = "unsupported"


@dataclass(slots=True, frozen=True)
class Drive:
    object_path: str
    block_path: str = ""
    device: str = ""
    model: str = "Optical Drive"
    vendor: str = ""
    connection_bus: str = ""
    media_available: bool = False
    media_name: str = ""
    audio_tracks: int = 0
    data_tracks: int = 0
    can_eject: bool = True

    @property
    def display_name(self) -> str:
        return " ".join(part for part in (self.vendor.strip(), self.model.strip()) if part) or "Optical Drive"


@dataclass(slots=True)
class Disc:
    kind: DiscKind
    drive: Drive
    disc_id: str = ""
    label: str = ""
    filesystem_type: str = ""
    mount_points: tuple[str, ...] = ()
    capacity: int = 0
    album: Album | None = None
    warnings: list[str] = field(default_factory=list)

    @property
    def media_type_text(self) -> str:
        return {
            DiscKind.AUDIO: "Audio CD",
            DiscKind.DATA: "Data CD",
            DiscKind.MIXED: "Mixed-mode CD",
            DiscKind.UNSUPPORTED: "Unsupported media",
            DiscKind.NONE: "No media",
        }[self.kind]

    @property
    def primary_mount_point(self) -> str:
        return self.mount_points[0] if self.mount_points else ""
