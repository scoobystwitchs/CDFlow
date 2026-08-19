"""Media, album, filesystem, and drive details for the inserted disc."""

from __future__ import annotations

from collections.abc import Mapping

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.album import Album
from cdflow.models.disc import Disc, DiscKind

from ..icons import symbolic_icon
from ..theme import DEFAULT_THEME
from ..widgets.artwork import DiscArtwork
from ..widgets.common import Card, ElidedLabel, InlineNotice, PageHeader, format_bytes
from .base import StatefulPage


class InfoSection(Card):
    """A compact two-column field card that hides empty rows."""

    def __init__(self, title: str, fields: tuple[tuple[str, str], ...], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 16)
        layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        layout.addWidget(heading)
        grid = QGridLayout()
        grid.setHorizontalSpacing(22)
        grid.setVerticalSpacing(9)
        grid.setColumnStretch(1, 1)
        self.rows: dict[str, tuple[QLabel, QLabel]] = {}
        for row, (key, label) in enumerate(fields):
            name = QLabel(label)
            name.setObjectName("muted")
            value = ElidedLabel()
            value.setTextInteractionFlags(value.textInteractionFlags() | Qt.TextInteractionFlag.TextSelectableByMouse)
            grid.addWidget(name, row, 0)
            grid.addWidget(value, row, 1)
            self.rows[key] = (name, value)
        layout.addLayout(grid)
        layout.addStretch(1)

    def set_values(self, values: Mapping[str, str]) -> None:
        for key, (name, value) in self.rows.items():
            text = str(values.get(key, "") or "")
            visible = bool(text)
            name.setVisible(visible)
            value.setVisible(visible)
            value.setText(text)


class DiscInfoPage(StatefulPage):
    metadata_refresh_requested = Signal()
    available_statuses = {AppStatus.AUDIO_CD, AppStatus.DATA_CD, AppStatus.RIPPING}
    available_disc_kinds = {DiscKind.AUDIO, DiscKind.DATA, DiscKind.MIXED, DiscKind.UNSUPPORTED}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Disc Information")
        self.header = PageHeader("Disc Information", "Technical and album details for the inserted media.")
        self.refresh_button = QPushButton("Refresh Metadata")
        self.refresh_button.setIcon(symbolic_icon("refresh", DEFAULT_THEME.text_muted, 16))
        self.refresh_button.setToolTip("Look up album metadata again")
        self.refresh_button.clicked.connect(self.metadata_refresh_requested)
        self.header.actions.addWidget(self.refresh_button)
        self.content_layout.addWidget(self.header)
        self.notice = InlineNotice()
        self.content_layout.addWidget(self.notice)

        top_card = Card()
        top = QHBoxLayout(top_card)
        top.setContentsMargins(15, 15, 18, 15)
        top.setSpacing(18)
        self.artwork = DiscArtwork(preferred_size=128)
        self.artwork.setFixedSize(128, 128)
        top.addWidget(self.artwork)
        summary = QVBoxLayout()
        summary.addStretch(1)
        self.disc_title = ElidedLabel("Disc")
        self.disc_title.setObjectName("albumTitle")
        summary.addWidget(self.disc_title)
        self.disc_artist = ElidedLabel("")
        self.disc_artist.setObjectName("accent")
        summary.addWidget(self.disc_artist)
        self.disc_summary = QLabel()
        self.disc_summary.setObjectName("muted")
        summary.addWidget(self.disc_summary)
        summary.addStretch(1)
        top.addLayout(summary, 1)
        self.content_layout.addWidget(top_card)

        sections = QHBoxLayout()
        sections.setSpacing(12)
        self.media_section = InfoSection(
            "Disc",
            (
                ("media_type", "Media Type"),
                ("label", "Label"),
                ("artist", "Artist"),
                ("album", "Album"),
                ("year", "Year"),
                ("genre", "Genre"),
                ("track_count", "Tracks"),
                ("duration", "Total Length"),
                ("filesystem", "Filesystem"),
                ("capacity", "Capacity"),
                ("mount_point", "Mount Point"),
                ("disc_id", "Disc ID"),
            ),
        )
        sections.addWidget(self.media_section, 3)
        self.drive_section = InfoSection(
            "Optical Drive",
            (
                ("drive_name", "Drive Name"),
                ("device", "Device Path"),
                ("block_path", "UDisks Block"),
                ("connection", "Connection"),
                ("can_eject", "Tray Control"),
            ),
        )
        sections.addWidget(self.drive_section, 2)
        self.content_layout.addLayout(sections, 1)

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        disc = snapshot.disc
        if disc is None:
            self._clear()
            return
        self._set_disc(disc)
        self.refresh_button.setVisible(bool(disc.album))
        if disc.warnings:
            self.notice.show_message(" · ".join(disc.warnings), level="warning")
        else:
            self.notice.hide()

    def set_cached_album(self, album: Album) -> None:
        """Show locally cached album information without pretending a disc is loaded."""

        self.disc_title.setText(album.title)
        self.disc_artist.setText(album.artist)
        count = len(album.tracks)
        self.disc_summary.setText(f"Cached Audio CD · {count} tracks · {album.total_duration_text}")
        self.artwork.set_artwork(album.artwork_path)
        self.media_section.set_values(
            {
                "media_type": "Cached Audio CD",
                "artist": album.artist,
                "album": album.title,
                "year": album.year,
                "genre": album.genre,
                "label": album.label,
                "track_count": str(count),
                "duration": album.total_duration_text,
                "disc_id": album.disc_id,
            }
        )
        self.drive_section.set_values({})
        self.refresh_button.hide()
        self.notice.show_message("This information is stored locally from a previously inserted CD.")
        self.show_content()

    def _set_disc(self, disc: Disc) -> None:
        album = disc.album
        self.disc_title.setText(album.title if album else (disc.label or disc.media_type_text))
        self.disc_artist.setText(album.artist if album else disc.media_type_text)
        summary: list[str] = [disc.media_type_text]
        if album and album.tracks:
            summary.extend([f"{len(album.tracks)} tracks", album.total_duration_text])
        elif disc.capacity:
            summary.append(format_bytes(disc.capacity))
        self.disc_summary.setText(" · ".join(summary))
        self.artwork.set_artwork(album.artwork_path if album else "")
        self.media_section.set_values(
            {
                "media_type": disc.media_type_text,
                "label": disc.label or (album.label if album else ""),
                "artist": album.artist if album else "",
                "album": album.title if album else "",
                "year": album.year if album else "",
                "genre": album.genre if album else "",
                "track_count": str(len(album.tracks)) if album else "",
                "duration": album.total_duration_text if album else "",
                "filesystem": disc.filesystem_type.upper() if disc.filesystem_type else "",
                "capacity": format_bytes(disc.capacity) if disc.capacity else "",
                "mount_point": disc.primary_mount_point,
                "disc_id": disc.disc_id,
            }
        )
        drive = disc.drive
        self.drive_section.set_values(
            {
                "drive_name": drive.display_name,
                "device": drive.device,
                "block_path": drive.block_path,
                "connection": drive.connection_bus.upper() if drive.connection_bus else "",
                "can_eject": "Supported" if drive.can_eject else "Not supported",
            }
        )

    def _clear(self) -> None:
        self.disc_title.setText("Disc")
        self.disc_artist.setText("")
        self.disc_summary.setText("")
        self.artwork.clear()
        self.media_section.set_values({})
        self.drive_section.set_values({})
        self.refresh_button.hide()
        self.notice.hide()


__all__ = ["DiscInfoPage", "InfoSection"]
