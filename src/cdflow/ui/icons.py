"""Small dependency-free symbolic icon set drawn with QPainter."""

from __future__ import annotations

from functools import lru_cache

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from .theme import DEFAULT_THEME


@lru_cache(maxsize=256)
def symbolic_icon(name: str, color: str = DEFAULT_THEME.text_muted, size: int = 20) -> QIcon:
    """Return a crisp monochrome icon without loading image resources."""

    pixel_size = max(12, size)
    pixmap = QPixmap(pixel_size, pixel_size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    scale = pixel_size / 24.0
    painter.scale(scale, scale)
    pen = QPen(QColor(color), 1.75, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.BrushStyle.NoBrush)

    def line(*coords: float) -> None:
        painter.drawLine(QPointF(coords[0], coords[1]), QPointF(coords[2], coords[3]))

    if name in {"now-playing", "home"}:
        path = QPainterPath(QPointF(4, 11))
        path.lineTo(12, 4)
        path.lineTo(20, 11)
        path.lineTo(18, 11)
        path.lineTo(18, 20)
        path.lineTo(6, 20)
        path.lineTo(6, 11)
        painter.drawPath(path)
        line(10, 20, 10, 14)
        line(14, 14, 14, 20)
    elif name in {"tracks", "music"}:
        line(9, 5, 19, 3)
        line(9, 5, 9, 16)
        line(19, 3, 19, 14)
        line(9, 8, 19, 6)
        painter.drawEllipse(QRectF(4, 15, 5, 4))
        painter.drawEllipse(QRectF(14, 13, 5, 4))
    elif name == "rip":
        painter.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        painter.drawEllipse(QRectF(9.5, 9.5, 5, 5))
        line(12, 3.5, 12, 7)
        line(12, 17, 12, 21)
        line(17, 12, 21, 12)
        line(18.5, 9.8, 21, 12)
        line(18.5, 14.2, 21, 12)
    elif name == "folder":
        path = QPainterPath(QPointF(3, 7))
        path.lineTo(9, 7)
        path.lineTo(11, 9)
        path.lineTo(21, 9)
        path.lineTo(19, 19)
        path.lineTo(3, 19)
        path.closeSubpath()
        painter.drawPath(path)
        line(3, 7, 3, 5)
        line(3, 5, 10, 5)
        line(10, 5, 12, 7)
        line(12, 7, 20, 7)
    elif name == "info":
        painter.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        line(12, 10.5, 12, 17)
        line(12, 7.2, 12, 7.3)
    elif name == "collection":
        painter.drawRoundedRect(QRectF(4, 4, 7, 7), 1, 1)
        painter.drawRoundedRect(QRectF(13, 4, 7, 7), 1, 1)
        painter.drawRoundedRect(QRectF(4, 13, 7, 7), 1, 1)
        painter.drawRoundedRect(QRectF(13, 13, 7, 7), 1, 1)
    elif name == "settings":
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        painter.drawEllipse(QRectF(4.5, 4.5, 15, 15))
        for a, b, c, d in (
            (12, 2, 12, 5),
            (12, 19, 12, 22),
            (2, 12, 5, 12),
            (19, 12, 22, 12),
            (4.9, 4.9, 7, 7),
            (17, 17, 19.1, 19.1),
            (19.1, 4.9, 17, 7),
            (7, 17, 4.9, 19.1),
        ):
            line(a, b, c, d)
    elif name == "eject":
        painter.drawPolygon(QPolygonF([QPointF(5, 15), QPointF(12, 6), QPointF(19, 15)]))
        line(5, 19, 19, 19)
    elif name == "play":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(8, 5), QPointF(19, 12), QPointF(8, 19)]))
    elif name == "pause":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(7, 5, 3.5, 14), 1, 1)
        painter.drawRoundedRect(QRectF(13.5, 5, 3.5, 14), 1, 1)
    elif name == "stop":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawRoundedRect(QRectF(6, 6, 12, 12), 2, 2)
    elif name == "previous":
        line(6, 5, 6, 19)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(18, 5), QPointF(8, 12), QPointF(18, 19)]))
    elif name == "next":
        line(18, 5, 18, 19)
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawPolygon(QPolygonF([QPointF(6, 5), QPointF(16, 12), QPointF(6, 19)]))
    elif name == "volume":
        painter.drawPolygon(
            QPolygonF([QPointF(4, 10), QPointF(8, 10), QPointF(13, 6), QPointF(13, 18), QPointF(8, 14), QPointF(4, 14)])
        )
        painter.drawArc(QRectF(10, 7, 8, 10), -65 * 16, 130 * 16)
        painter.drawArc(QRectF(9, 4, 13, 16), -60 * 16, 120 * 16)
    elif name == "mute":
        painter.drawPolygon(
            QPolygonF([QPointF(4, 10), QPointF(8, 10), QPointF(13, 6), QPointF(13, 18), QPointF(8, 14), QPointF(4, 14)])
        )
        line(16, 9, 21, 14)
        line(21, 9, 16, 14)
    elif name == "shuffle":
        path = QPainterPath(QPointF(3, 7))
        path.cubicTo(8, 7, 9, 17, 15, 17)
        path.lineTo(20, 17)
        painter.drawPath(path)
        path = QPainterPath(QPointF(3, 17))
        path.cubicTo(8, 17, 9, 7, 15, 7)
        path.lineTo(20, 7)
        painter.drawPath(path)
        line(17, 4.5, 20, 7)
        line(17, 9.5, 20, 7)
        line(17, 14.5, 20, 17)
        line(17, 19.5, 20, 17)
    elif name == "repeat":
        path = QPainterPath(QPointF(6, 7))
        path.lineTo(18, 7)
        path.cubicTo(21, 7, 21, 11, 19, 12)
        painter.drawPath(path)
        path = QPainterPath(QPointF(18, 17))
        path.lineTo(6, 17)
        path.cubicTo(3, 17, 3, 13, 5, 12)
        painter.drawPath(path)
        line(16, 4.5, 18.5, 7)
        line(16, 9.5, 18.5, 7)
        line(8, 14.5, 5.5, 17)
        line(8, 19.5, 5.5, 17)
    elif name in {"disc", "drive"}:
        painter.drawEllipse(QRectF(3, 3, 18, 18))
        painter.drawEllipse(QRectF(9, 9, 6, 6))
        line(12, 3, 12, 6)
    elif name == "search":
        painter.drawEllipse(QRectF(4, 4, 11, 11))
        line(14, 14, 20, 20)
    elif name in {"chevron-left", "chevron-right"}:
        if name == "chevron-left":
            line(15, 5, 8, 12)
            line(8, 12, 15, 19)
        else:
            line(9, 5, 16, 12)
            line(16, 12, 9, 19)
    elif name == "more":
        painter.setBrush(QColor(color))
        painter.setPen(Qt.PenStyle.NoPen)
        for x in (6, 12, 18):
            painter.drawEllipse(QRectF(x - 1.2, 10.8, 2.4, 2.4))
    elif name == "refresh":
        painter.drawArc(QRectF(4, 4, 16, 16), 35 * 16, 285 * 16)
        line(17.5, 3.5, 20, 7)
        line(20, 7, 16, 7.5)
    elif name in {"close", "cancel"}:
        line(6, 6, 18, 18)
        line(18, 6, 6, 18)
    elif name == "error":
        painter.drawEllipse(QRectF(3.5, 3.5, 17, 17))
        line(12, 7, 12, 14)
        line(12, 17, 12, 17.1)
    elif name == "check":
        path = QPainterPath(QPointF(4, 12))
        path.lineTo(9.5, 17)
        path.lineTo(20, 6)
        painter.drawPath(path)
    else:
        painter.drawRoundedRect(QRectF(5, 5, 14, 14), 3, 3)

    painter.end()
    return QIcon(pixmap)


__all__ = ["symbolic_icon"]
