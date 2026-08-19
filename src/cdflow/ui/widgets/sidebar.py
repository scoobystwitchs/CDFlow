"""Compact navigation, optical-drive selector, and media status sidebar."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget

from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.disc import Disc, Drive

from ..icons import symbolic_icon
from ..theme import DEFAULT_THEME
from .common import ElidedLabel, StatusDot

NAVIGATION: tuple[tuple[str, str, str], ...] = (
    ("now_playing", "Now Playing", "now-playing"),
    ("tracks", "Tracks", "tracks"),
    ("rip_cd", "Rip CD", "rip"),
    ("browse_files", "Browse Files", "folder"),
    ("disc_info", "Disc Info", "info"),
    ("collection", "Collection", "collection"),
    ("settings", "Settings", "settings"),
)


class Sidebar(QFrame):
    page_requested = Signal(str)
    drive_selected = Signal(str)
    eject_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("sidebar")
        self.setMinimumWidth(184)
        self.setMaximumWidth(224)
        self.setAccessibleName("Application navigation")
        self._drive_buttons: dict[str, QPushButton] = {}
        self.drive_group = QButtonGroup(self)
        self.drive_group.setExclusive(True)
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 15, 12, 12)
        root.setSpacing(8)
        header = QHBoxLayout()
        logo = QLabel()
        logo.setPixmap(symbolic_icon("disc", DEFAULT_THEME.accent, 22).pixmap(22, 22))
        logo.setAccessibleName("CDFlow logo")
        header.addWidget(logo)
        self.app_name = QLabel("CDFLOW")
        self.app_name.setObjectName("appName")
        header.addWidget(self.app_name)
        header.addStretch(1)
        root.addLayout(header)
        root.addSpacing(8)
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        self.nav_buttons: dict[str, QPushButton] = {}
        for index, (page_id, label, icon_name) in enumerate(NAVIGATION):
            button = QPushButton(label)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIcon(symbolic_icon(icon_name, DEFAULT_THEME.text_muted, 17))
            button.setToolTip(f"Open {label}")
            button.setAccessibleName(label)
            button.clicked.connect(lambda checked=False, key=page_id: self.page_requested.emit(key))
            self.nav_group.addButton(button, index)
            self.nav_buttons[page_id] = button
            root.addWidget(button)
        self.nav_buttons["now_playing"].setChecked(True)
        root.addSpacing(10)
        self.drives_heading = QLabel("DRIVES")
        self.drives_heading.setObjectName("faint")
        self.drives_heading.setStyleSheet("font-size: 10px; font-weight: 650; padding-left: 4px;")
        root.addWidget(self.drives_heading)
        self.drive_scroll = QScrollArea()
        self.drive_scroll.setWidgetResizable(True)
        self.drive_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.drive_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.drive_scroll.setMaximumHeight(132)
        self.drive_host = QWidget()
        self.drive_layout = QVBoxLayout(self.drive_host)
        self.drive_layout.setContentsMargins(0, 0, 0, 0)
        self.drive_layout.setSpacing(2)
        self.drive_layout.addStretch(1)
        self.drive_scroll.setWidget(self.drive_host)
        root.addWidget(self.drive_scroll)
        root.addStretch(1)
        self.status_card = QFrame()
        self.status_card.setObjectName("innerCard")
        status_layout = QVBoxLayout(self.status_card)
        status_layout.setContentsMargins(10, 9, 10, 9)
        status_layout.setSpacing(7)
        status_row = QHBoxLayout()
        self.status_dot = StatusDot()
        status_row.addWidget(self.status_dot)
        status_text = QVBoxLayout()
        status_text.setSpacing(1)
        self.status_title = ElidedLabel("No Drive")
        self.status_title.setObjectName("cardTitle")
        self.status_detail = ElidedLabel("Connect an optical drive")
        self.status_detail.setObjectName("muted")
        status_text.addWidget(self.status_title)
        status_text.addWidget(self.status_detail)
        status_row.addLayout(status_text, 1)
        status_layout.addLayout(status_row)
        self.eject_button = QPushButton("Eject Disc")
        self.eject_button.setIcon(symbolic_icon("eject", DEFAULT_THEME.text_muted, 16))
        self.eject_button.setToolTip("Eject the selected optical disc")
        self.eject_button.setAccessibleName("Eject selected disc")
        self.eject_button.clicked.connect(self.eject_requested)
        self.eject_button.setVisible(False)
        status_layout.addWidget(self.eject_button)
        root.addWidget(self.status_card)

    def set_current_page(self, page_id: str) -> None:
        button = self.nav_buttons.get(page_id)
        if button is not None:
            button.setChecked(True)

    def set_drives(self, drives: Iterable[Drive], selected_path: str = "") -> None:
        for button in self.drive_group.buttons():
            self.drive_group.removeButton(button)
        while self.drive_layout.count() > 1:
            item = self.drive_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._drive_buttons.clear()
        drives_list = list(drives)
        if not drives_list:
            empty = QLabel("No optical drives")
            empty.setObjectName("faint")
            empty.setContentsMargins(6, 6, 6, 6)
            self.drive_layout.insertWidget(0, empty)
        for drive in drives_list:
            device = drive.device or drive.block_path or "Optical drive"
            button = QPushButton(f"{drive.display_name}\n{device}")
            button.setObjectName("driveButton")
            button.setCheckable(True)
            button.setChecked(drive.object_path == selected_path)
            button.setIcon(symbolic_icon("drive", DEFAULT_THEME.text_muted, 16))
            button.setToolTip(f"Select {drive.display_name} ({device})")
            button.setAccessibleName(button.toolTip())
            button.clicked.connect(lambda checked=False, path=drive.object_path: self.drive_selected.emit(path))
            self.drive_group.addButton(button)
            self.drive_layout.insertWidget(self.drive_layout.count() - 1, button)
            self._drive_buttons[drive.object_path] = button
        self.drive_scroll.setVisible(bool(drives_list))

    def set_state(self, snapshot: StateSnapshot) -> None:
        self.set_drives(snapshot.drives, snapshot.selected_drive_path)
        title, detail, colour = self._status_parts(snapshot.status, snapshot.disc, snapshot.message)
        self.status_title.setText(title)
        self.status_detail.setText(detail)
        self.status_dot.set_color(colour)
        can_eject = snapshot.status in {
            AppStatus.EMPTY_DRIVE,
            AppStatus.AUDIO_CD,
            AppStatus.DATA_CD,
            AppStatus.LOADING_DISC,
            AppStatus.ERROR,
        }
        selected = next((drive for drive in snapshot.drives if drive.object_path == snapshot.selected_drive_path), None)
        self.eject_button.setVisible(bool(selected and selected.can_eject and can_eject))
        self.eject_button.setEnabled(snapshot.status not in {AppStatus.EJECTING, AppStatus.RIPPING})

    @staticmethod
    def _status_parts(status: AppStatus, disc: Disc | None, message: str) -> tuple[str, str, str]:
        if status == AppStatus.NO_DRIVE:
            return "No Drive", message or "Connect an optical drive", DEFAULT_THEME.text_faint
        if status == AppStatus.EMPTY_DRIVE:
            return "No Disc", message or "Drive is ready", DEFAULT_THEME.text_faint
        if status == AppStatus.LOADING_DISC:
            return "Reading Disc", message or "Loading media", DEFAULT_THEME.warning
        if status == AppStatus.RIPPING:
            return "Ripping CD", message or "Extraction in progress", DEFAULT_THEME.accent
        if status == AppStatus.EJECTING:
            return "Ejecting", message or "Waiting for drive", DEFAULT_THEME.warning
        if status == AppStatus.ERROR:
            return "Drive Error", message or "Unable to read media", DEFAULT_THEME.danger
        if disc is not None:
            detail = disc.album.title if disc.album else (disc.label or disc.media_type_text)
            return f"{disc.media_type_text} Detected", detail, DEFAULT_THEME.accent
        return "Disc Detected", message, DEFAULT_THEME.accent

    def set_compact(self, compact: bool) -> None:
        self.setFixedWidth(184 if compact else 210)
        self.app_name.setVisible(not compact)


__all__ = ["NAVIGATION", "Sidebar"]
