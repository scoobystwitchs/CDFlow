"""Responsive grid of locally remembered physical albums."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeyEvent, QMouseEvent
from PySide6.QtWidgets import QFrame, QGridLayout, QScrollArea, QVBoxLayout, QWidget

from cdflow.app.state import StateSnapshot
from cdflow.models.album import Album

from ..widgets.artwork import DiscArtwork
from ..widgets.common import ElidedLabel, EmptyState, PageHeader
from .base import StatefulPage


class AlbumCard(QFrame):
    activated = Signal(str)

    def __init__(self, album: Album, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.album = album
        self.setObjectName("albumCard")
        self.setProperty("card", True)
        self.setFixedSize(176, 238)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAccessibleName(f"{album.title} by {album.artist}")
        self.setToolTip(f"Open cached information for {album.title} by {album.artist}")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 11)
        layout.setSpacing(4)
        artwork = DiscArtwork(preferred_size=156)
        artwork.setFixedSize(156, 156)
        artwork.set_artwork(album.artwork_path)
        layout.addWidget(artwork)
        title = ElidedLabel(album.title)
        title.setObjectName("cardTitle")
        layout.addWidget(title)
        artist = ElidedLabel(album.artist)
        artist.setObjectName("muted")
        layout.addWidget(artist)
        footer = "Ripped" if album.ripped else (album.year or "In collection")
        status = ElidedLabel(footer)
        status.setObjectName("accent" if album.ripped else "faint")
        layout.addWidget(status)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.activated.emit(self.album.disc_id)

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        if event.key() in {Qt.Key.Key_Return, Qt.Key.Key_Enter, Qt.Key.Key_Space}:
            self.activated.emit(self.album.disc_id)
            event.accept()
            return
        super().keyPressEvent(event)


class CollectionPage(StatefulPage):
    album_selected = Signal(str)
    always_available = True

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("CD Collection")
        self._albums: list[Album] = []
        self._cards: list[AlbumCard] = []
        self._columns = 0
        self.header = PageHeader("My Collection", "CDs you have previously inserted appear here.")
        self.content_layout.addWidget(self.header)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 2, 8, 8)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.grid.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft)
        self.empty_collection = EmptyState()
        self.empty_collection.set_message(
            "Your Collection Is Empty",
            "Recognized CDs are remembered locally and will appear here.",
            icon="collection",
        )
        self.grid.addWidget(self.empty_collection, 0, 0)
        self.scroll.setWidget(self.grid_host)
        self.content_layout.addWidget(self.scroll, 1)

    def set_albums(self, albums: Iterable[Album]) -> None:
        self._albums = sorted(list(albums), key=lambda album: album.last_inserted, reverse=True)
        for card in self._cards:
            self.grid.removeWidget(card)
            card.deleteLater()
        self._cards.clear()
        for album in self._albums:
            card = AlbumCard(album)
            card.activated.connect(self.album_selected)
            self._cards.append(card)
        self.empty_collection.setVisible(not self._cards)
        count = len(self._cards)
        if count:
            self.header.set_subtitle(f"{count} {'disc' if count == 1 else 'discs'} remembered locally")
        else:
            self.header.set_subtitle("CDs you have previously inserted appear here.")
        self._columns = 0
        self._relayout()

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        del snapshot

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._relayout()

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._columns = 0
        self._relayout()

    def _relayout(self) -> None:
        available = max(176, self.scroll.viewport().width() - 8)
        columns = max(1, available // 188)
        if columns == self._columns and self.grid.count() > 0:
            return
        self._columns = columns
        for card in self._cards:
            self.grid.removeWidget(card)
        for index, card in enumerate(self._cards):
            self.grid.addWidget(card, index // columns, index % columns)
        if not self._cards:
            self.grid.addWidget(self.empty_collection, 0, 0, 1, columns)
        for column in range(columns):
            self.grid.setColumnStretch(column, 0)
        self.grid.setColumnStretch(columns, 1)


__all__ = ["AlbumCard", "CollectionPage"]
