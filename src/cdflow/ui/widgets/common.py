"""Small reusable building blocks shared by CDFlow pages."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from cdflow.app.state import AppStatus

from ..icons import symbolic_icon
from ..theme import DEFAULT_THEME


def format_bytes(value: int | float) -> str:
    """Format a byte count compactly for file and disc information."""

    size = max(0.0, float(value))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return "0 B"


def format_time(seconds: float | int) -> str:
    total = max(0, round(float(seconds)))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:d}:{minutes:02d}:{secs:02d}" if hours else f"{minutes:d}:{secs:02d}"


class Card(QFrame):
    def __init__(self, parent: QWidget | None = None, *, inner: bool = False) -> None:
        super().__init__(parent)
        self.setObjectName("innerCard" if inner else "card")


class Separator(QFrame):
    def __init__(self, orientation: Qt.Orientation = Qt.Orientation.Horizontal, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("separator")
        self.setFrameShape(QFrame.Shape.HLine if orientation == Qt.Orientation.Horizontal else QFrame.Shape.VLine)
        if orientation == Qt.Orientation.Horizontal:
            self.setFixedHeight(1)
        else:
            self.setFixedWidth(1)


class IconButton(QToolButton):
    """Consistently-sized accessible symbolic button."""

    def __init__(self, icon_name: str, tooltip: str, parent: QWidget | None = None, *, size: int = 18) -> None:
        super().__init__(parent)
        self._icon_name = icon_name
        self._icon_size = size
        self.setObjectName("iconButton")
        self.setIcon(symbolic_icon(icon_name, size=size))
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def set_symbol(self, icon_name: str, *, color: str = DEFAULT_THEME.text_muted) -> None:
        self._icon_name = icon_name
        self.setIcon(symbolic_icon(icon_name, color, self._icon_size))


class Badge(QLabel):
    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(text, parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background: {DEFAULT_THEME.raised}; color: {DEFAULT_THEME.text_muted}; "
            f"border: 1px solid {DEFAULT_THEME.border}; border-radius: 5px; padding: 3px 7px; font-size: 11px;"
        )
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)


class StatusDot(QWidget):
    """A static status indicator; it intentionally has no animation/timer."""

    def __init__(self, color: str = DEFAULT_THEME.text_faint, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._color = QColor(color)
        self.setFixedSize(18, 18)
        self.setAccessibleName("Status indicator")

    def set_color(self, color: str) -> None:
        self._color = QColor(color)
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802 - Qt virtual method
        del event
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setPen(Qt.PenStyle.NoPen)
        halo = QColor(self._color)
        halo.setAlpha(45)
        painter.setBrush(halo)
        painter.drawEllipse(1, 1, 16, 16)
        painter.setBrush(self._color)
        painter.drawEllipse(6, 6, 6, 6)


class ElidedLabel(QLabel):
    """A label that elides a long single line instead of forcing layout growth."""

    def __init__(self, text: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._full_text = text
        super().setText(text)
        self.setToolTip(text)
        self.setMinimumWidth(0)

    def setText(self, text: str) -> None:  # noqa: N802 - Qt API
        self._full_text = text
        self.setToolTip(text)
        self._refresh()

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._refresh()

    def _refresh(self) -> None:
        width = max(0, self.contentsRect().width())
        elided = QFontMetrics(self.font()).elidedText(self._full_text, Qt.TextElideMode.ElideRight, width)
        super().setText(elided)


class PageHeader(QWidget):
    """Title, optional subtitle, and an action area."""

    def __init__(self, title: str, subtitle: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(12)
        labels = QVBoxLayout()
        labels.setSpacing(2)
        self.title_label = QLabel(title)
        self.title_label.setObjectName("pageTitle")
        labels.addWidget(self.title_label)
        self.subtitle_label = QLabel(subtitle)
        self.subtitle_label.setObjectName("muted")
        self.subtitle_label.setVisible(bool(subtitle))
        labels.addWidget(self.subtitle_label)
        row.addLayout(labels, 1)
        self.actions = QHBoxLayout()
        self.actions.setSpacing(8)
        row.addLayout(self.actions)

    def set_subtitle(self, text: str) -> None:
        self.subtitle_label.setText(text)
        self.subtitle_label.setVisible(bool(text))


class EmptyState(QWidget):
    """Reusable idle/loading/error state shown inside a page."""

    action_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(28, 28, 28, 28)
        outer.addStretch(1)
        center = QVBoxLayout()
        center.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        center.setSpacing(10)
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.icon_label.setFixedSize(76, 76)
        center.addWidget(self.icon_label, 0, Qt.AlignmentFlag.AlignHCenter)
        self.title_label = QLabel("No Disc Inserted")
        self.title_label.setObjectName("emptyTitle")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        center.addWidget(self.title_label)
        self.body_label = QLabel("Insert an Audio CD or Data CD\nto get started.")
        self.body_label.setObjectName("emptyBody")
        self.body_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.body_label.setWordWrap(True)
        center.addWidget(self.body_label)
        self.action_button = QPushButton("Try Again")
        self.action_button.clicked.connect(self.action_requested)
        self.action_button.setVisible(False)
        center.addWidget(self.action_button, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addLayout(center)
        outer.addStretch(1)
        self.setMinimumHeight(260)
        self.set_state(AppStatus.EMPTY_DRIVE)

    def set_message(self, title: str, body: str, *, icon: str = "disc", action: str = "") -> None:
        self.title_label.setText(title)
        self.body_label.setText(body)
        self.icon_label.setPixmap(symbolic_icon(icon, DEFAULT_THEME.accent, 64).pixmap(64, 64))
        self.icon_label.setAccessibleName(title)
        self.action_button.setText(action)
        self.action_button.setVisible(bool(action))

    def set_state(self, status: AppStatus, message: str = "") -> None:
        if status == AppStatus.NO_DRIVE:
            self.set_message("No Optical Drive", message or "Connect an optical drive to get started.", icon="drive")
        elif status == AppStatus.LOADING_DISC:
            self.set_message("Reading Disc", message or "CDFlow is reading the disc table of contents.", icon="disc")
        elif status == AppStatus.EJECTING:
            self.set_message("Ejecting Disc", message or "Waiting for the optical drive.", icon="eject")
        elif status == AppStatus.ERROR:
            self.set_message(
                "Something Went Wrong", message or "The disc could not be read.", icon="error", action="Try Again"
            )
        else:
            self.set_message(
                "No Disc Inserted",
                "Insert an Audio CD or Data CD\nto get started.",
                icon="disc",
            )


class InlineNotice(QFrame):
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("innerCard")
        row = QHBoxLayout(self)
        row.setContentsMargins(10, 7, 8, 7)
        self.icon_label = QLabel()
        row.addWidget(self.icon_label)
        self.label = QLabel()
        self.label.setWordWrap(True)
        row.addWidget(self.label, 1)
        close = IconButton("close", "Dismiss")
        close.clicked.connect(self.dismissed)
        close.clicked.connect(self.hide)
        row.addWidget(close)
        self.hide()

    def show_message(self, text: str, *, level: str = "info") -> None:
        colour = {
            "error": DEFAULT_THEME.danger,
            "warning": DEFAULT_THEME.warning,
            "success": DEFAULT_THEME.success,
        }.get(level, DEFAULT_THEME.accent)
        icon = "check" if level == "success" else "error" if level in {"error", "warning"} else "info"
        self.icon_label.setPixmap(symbolic_icon(icon, colour, 18).pixmap(18, 18))
        self.label.setText(text)
        self.setAccessibleName(f"{level.title()}: {text}")
        self.show()


__all__ = [
    "Badge",
    "Card",
    "ElidedLabel",
    "EmptyState",
    "IconButton",
    "InlineNotice",
    "PageHeader",
    "Separator",
    "StatusDot",
    "format_bytes",
    "format_time",
]
