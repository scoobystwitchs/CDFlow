"""Audio-CD overview and compact complete track list."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.album import Album
from cdflow.models.disc import DiscKind

from ..icons import symbolic_icon
from ..theme import DEFAULT_THEME
from ..widgets.artwork import DiscArtwork
from ..widgets.common import Badge, Card, ElidedLabel
from ..widgets.track_table import TrackTable
from .base import StatefulPage


class NowPlayingPage(StatefulPage):
    track_activated = Signal(int)
    rip_clicked = Signal()
    disc_info_clicked = Signal()
    available_statuses = {AppStatus.AUDIO_CD, AppStatus.RIPPING}
    available_disc_kinds = {DiscKind.MIXED}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Now Playing")
        self.hero = Card()
        hero_layout = QHBoxLayout(self.hero)
        hero_layout.setContentsMargins(14, 14, 16, 14)
        hero_layout.setSpacing(16)
        self.artwork = DiscArtwork(preferred_size=148)
        self.artwork.setMinimumSize(122, 122)
        self.artwork.setMaximumSize(164, 164)
        hero_layout.addWidget(self.artwork, 0, Qt.AlignmentFlag.AlignVCenter)

        summary = QVBoxLayout()
        summary.setSpacing(5)
        summary.addStretch(1)
        self.album_title = ElidedLabel("Unknown Album")
        self.album_title.setObjectName("albumTitle")
        summary.addWidget(self.album_title)
        self.artist_label = ElidedLabel("Unknown Artist")
        self.artist_label.setObjectName("accent")
        summary.addWidget(self.artist_label)
        meta_row = QHBoxLayout()
        meta_row.setSpacing(7)
        self.summary_label = QLabel("0 Tracks · 0:00")
        self.summary_label.setObjectName("muted")
        meta_row.addWidget(self.summary_label)
        self.media_badge = Badge("Audio CD")
        meta_row.addWidget(self.media_badge)
        meta_row.addStretch(1)
        summary.addLayout(meta_row)
        summary.addSpacing(6)
        action_row = QHBoxLayout()
        action_row.setSpacing(7)
        self.rip_button = QPushButton("Rip CD")
        self.rip_button.setObjectName("primaryButton")
        self.rip_button.setIcon(symbolic_icon("rip", "#FFFFFF", 16))
        self.rip_button.setToolTip("Choose tracks and rip this Audio CD")
        self.rip_button.clicked.connect(self.rip_clicked)
        action_row.addWidget(self.rip_button)
        self.info_button = QPushButton("Disc Info")
        self.info_button.setIcon(symbolic_icon("info", DEFAULT_THEME.text_muted, 16))
        self.info_button.clicked.connect(self.disc_info_clicked)
        action_row.addWidget(self.info_button)
        action_row.addStretch(1)
        summary.addLayout(action_row)
        summary.addStretch(1)
        hero_layout.addLayout(summary, 3)

        self.info_panel = QWidget()
        info = QGridLayout(self.info_panel)
        info.setContentsMargins(16, 2, 0, 2)
        info.setHorizontalSpacing(14)
        info.setVerticalSpacing(8)
        self.info_values: dict[str, QLabel] = {}
        for row, (key, label) in enumerate(
            (
                ("artist", "Artist"),
                ("album", "Album"),
                ("year", "Year"),
                ("genre", "Genre"),
                ("label", "Label"),
            )
        ):
            name = QLabel(label)
            name.setObjectName("muted")
            info.addWidget(name, row, 0)
            value = ElidedLabel("—")
            value.setMinimumWidth(130)
            self.info_values[key] = value
            info.addWidget(value, row, 1)
        hero_layout.addWidget(self.info_panel, 2)
        self.content_layout.addWidget(self.hero, 0)

        tracks_card = Card()
        tracks_layout = QVBoxLayout(tracks_card)
        tracks_layout.setContentsMargins(0, 0, 0, 0)
        tracks_layout.setSpacing(0)
        heading_row = QHBoxLayout()
        heading_row.setContentsMargins(13, 8, 13, 7)
        heading = QLabel("TRACKS")
        heading.setObjectName("muted")
        heading.setStyleSheet("font-size: 10px; font-weight: 650;")
        heading_row.addWidget(heading)
        heading_row.addStretch(1)
        self.track_count_label = QLabel("0 tracks")
        self.track_count_label.setObjectName("muted")
        heading_row.addWidget(self.track_count_label)
        tracks_layout.addLayout(heading_row)
        self.track_table = TrackTable(show_status=False)
        self.track_table.track_activated.connect(self.track_activated)
        tracks_layout.addWidget(self.track_table, 1)
        self.content_layout.addWidget(tracks_card, 1)

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        disc = snapshot.disc
        album = disc.album if disc else None
        if album is None:
            self._set_album(None)
            return
        self._set_album(album)
        self.media_badge.setText(disc.media_type_text)
        self.track_table.setEnabled(snapshot.status != AppStatus.RIPPING)
        self.rip_button.setEnabled(snapshot.status != AppStatus.RIPPING)
        if snapshot.status == AppStatus.RIPPING:
            self.rip_button.setText("Ripping…")
        else:
            self.rip_button.setText("Rip CD")

    def _set_album(self, album: Album | None) -> None:
        if album is None:
            self.album_title.setText("Unknown Album")
            self.artist_label.setText("Unknown Artist")
            self.summary_label.setText("0 Tracks · 0:00")
            self.track_count_label.setText("0 tracks")
            self.artwork.clear()
            self.track_table.set_tracks(())
            for value in self.info_values.values():
                value.setText("—")
            return
        self.album_title.setText(album.title)
        self.artist_label.setText(album.artist)
        count = len(album.tracks)
        self.summary_label.setText(f"{count} {'Track' if count == 1 else 'Tracks'} · {album.total_duration_text}")
        self.track_count_label.setText(f"{count} {'track' if count == 1 else 'tracks'}")
        self.artwork.set_artwork(album.artwork_path)
        self.track_table.set_tracks(album.tracks)
        for key, text in {
            "artist": album.artist,
            "album": album.title,
            "year": album.year,
            "genre": album.genre,
            "label": album.label,
        }.items():
            self.info_values[key].setText(text or "—")

    def set_current_track(self, track_number: int) -> None:
        self.track_table.set_current_track(track_number)

    def set_compact(self, compact: bool) -> None:
        self.info_panel.setVisible(not compact)
        self.artwork.setMaximumSize(130 if compact else 164, 130 if compact else 164)


__all__ = ["NowPlayingPage"]
