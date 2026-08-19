"""Full, searchable audio-track table."""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLineEdit, QWidget

from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.disc import DiscKind

from ..icons import symbolic_icon
from ..widgets.common import Card, PageHeader
from ..widgets.track_table import TrackTable
from .base import StatefulPage


class TracksPage(StatefulPage):
    track_activated = Signal(int)
    rip_track_requested = Signal(int)
    track_info_requested = Signal(int)
    available_statuses = {AppStatus.AUDIO_CD, AppStatus.RIPPING}
    available_disc_kinds = {DiscKind.MIXED}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Tracks")
        self.header = PageHeader("Tracks", "Audio CD · 0 tracks · 0:00")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tracks…")
        self.search.setClearButtonEnabled(True)
        self.search.setAccessibleName("Search tracks")
        self.search.setMaximumWidth(260)
        self.search.addAction(symbolic_icon("search"), QLineEdit.ActionPosition.LeadingPosition)
        self.header.actions.addWidget(self.search)
        self.content_layout.addWidget(self.header)
        card = Card()
        layout = QHBoxLayout(card)
        layout.setContentsMargins(0, 0, 0, 0)
        self.track_table = TrackTable(show_status=True)
        self.track_table.track_activated.connect(self.track_activated)
        self.track_table.rip_track_requested.connect(self.rip_track_requested)
        self.track_table.track_info_requested.connect(self.track_info_requested)
        self.search.textChanged.connect(self.track_table.set_filter_text)
        layout.addWidget(self.track_table)
        self.content_layout.addWidget(card, 1)

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        album = snapshot.disc.album if snapshot.disc else None
        if album is None:
            self.track_table.set_tracks(())
            self.header.set_subtitle("Audio CD")
            return
        self.track_table.set_tracks(album.tracks)
        self.track_table.setEnabled(snapshot.status != AppStatus.RIPPING)
        self.track_table.setToolTip(
            "Playback is unavailable while ripping"
            if snapshot.status == AppStatus.RIPPING
            else "Double-click a track to play it"
        )
        count = len(album.tracks)
        self.header.set_subtitle(
            f"{album.title} · {count} {'track' if count == 1 else 'tracks'} · {album.total_duration_text}"
        )

    def set_current_track(self, track_number: int) -> None:
        self.track_table.set_current_track(track_number)


__all__ = ["TracksPage"]
