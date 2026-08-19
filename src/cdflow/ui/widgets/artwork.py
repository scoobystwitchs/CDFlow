"""Programmatically rendered artwork used when a cover is unavailable."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import (
    QColor,
    QConicalGradient,
    QLinearGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
    QRadialGradient,
)
from PySide6.QtWidgets import QSizePolicy, QWidget

from ..theme import DEFAULT_THEME


class DiscArtwork(QWidget):
    """Cover-art widget with a lightweight, painted optical-disc fallback."""

    def __init__(self, parent: QWidget | None = None, *, preferred_size: int = 148) -> None:
        super().__init__(parent)
        self._preferred_size = preferred_size
        self._pixmap = QPixmap()
        self._artwork_path = ""
        self.setMinimumSize(64, 64)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Preferred)
        self.setAccessibleName("Album artwork")

    def sizeHint(self) -> QSize:  # noqa: N802
        return QSize(self._preferred_size, self._preferred_size)

    def minimumSizeHint(self) -> QSize:  # noqa: N802
        return QSize(64, 64)

    @property
    def artwork_path(self) -> str:
        return self._artwork_path

    def set_artwork(self, path: str | Path | None) -> None:
        requested_path = str(path or "")
        if requested_path == self._artwork_path:
            return
        self._artwork_path = requested_path
        candidate = QPixmap(self._artwork_path) if self._artwork_path else QPixmap()
        self._pixmap = candidate if not candidate.isNull() else QPixmap()
        self.update()

    def clear(self) -> None:
        self.set_artwork(None)

    def paintEvent(self, event) -> None:  # noqa: N802
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        side = min(self.width(), self.height())
        rect = QRectF((self.width() - side) / 2 + 1, (self.height() - side) / 2 + 1, side - 2, side - 2)
        path = QPainterPath()
        path.addRoundedRect(rect, max(5.0, side * 0.055), max(5.0, side * 0.055))
        painter.setClipPath(path)

        if not self._pixmap.isNull():
            scaled = self._pixmap.scaled(
                int(rect.width()),
                int(rect.height()),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            source = QRectF(
                max(0, (scaled.width() - rect.width()) / 2),
                max(0, (scaled.height() - rect.height()) / 2),
                rect.width(),
                rect.height(),
            )
            painter.drawPixmap(rect, scaled, source)
        else:
            background = QLinearGradient(rect.topLeft(), rect.bottomRight())
            background.setColorAt(0, QColor("#252C37"))
            background.setColorAt(1, QColor("#0B0F15"))
            painter.fillPath(path, background)
            margin = side * 0.09
            disc = rect.adjusted(margin, margin, -margin, -margin)
            spectrum = QConicalGradient(disc.center(), -30)
            colours = ["#F3A3CB", "#D9E6FF", "#9DE8D5", "#F5D999", "#EAA2C7", "#A7C9EC", "#F3A3CB"]
            for index, colour in enumerate(colours):
                spectrum.setColorAt(index / (len(colours) - 1), QColor(colour))
            painter.setBrush(spectrum)
            painter.setPen(QPen(QColor("#66717F"), 1))
            painter.drawEllipse(disc)
            shine = QRadialGradient(disc.center() - QPointF(side * 0.12, side * 0.12), disc.width() * 0.62)
            shine.setColorAt(0, QColor(255, 255, 255, 95))
            shine.setColorAt(0.38, QColor(255, 255, 255, 10))
            shine.setColorAt(1, QColor(0, 0, 0, 110))
            painter.setBrush(shine)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawEllipse(disc)
            ring = disc.adjusted(side * 0.32, side * 0.32, -side * 0.32, -side * 0.32)
            painter.setBrush(QColor("#0A0D12"))
            painter.setPen(QPen(QColor("#69717C"), 1))
            painter.drawEllipse(ring)
            hole = ring.adjusted(side * 0.065, side * 0.065, -side * 0.065, -side * 0.065)
            painter.setBrush(QColor("#171C24"))
            painter.setPen(QPen(self.palette().highlight().color(), max(1.0, side * 0.009)))
            painter.drawEllipse(hole)

        painter.setClipping(False)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(DEFAULT_THEME.border), 1))
        painter.drawRoundedRect(rect, max(5.0, side * 0.055), max(5.0, side * 0.055))


__all__ = ["DiscArtwork"]
