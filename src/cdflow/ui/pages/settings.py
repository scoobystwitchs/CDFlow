"""Minimal local preferences editor aligned with :mod:`cdflow.app.settings`."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from cdflow.app.constants import DEFAULT_ACCENT, DEFAULT_FILENAME_PATTERN, DEFAULT_MUSIC_DIR
from cdflow.app.state import StateSnapshot

from ..widgets.common import Card, PageHeader
from .base import StatefulPage

ACCENTS = ("#F43F86", "#EE5E5E", "#F0AD43", "#48C78E", "#38BDF8", "#8B7CF6")


class SettingsSection(Card):
    def __init__(self, title: str, description: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(16, 14, 16, 16)
        self.layout.setSpacing(10)
        heading = QLabel(title)
        heading.setObjectName("sectionTitle")
        self.layout.addWidget(heading)
        if description:
            detail = QLabel(description)
            detail.setObjectName("muted")
            detail.setWordWrap(True)
            self.layout.addWidget(detail)


class SettingsPage(StatefulPage):
    settings_changed = Signal(dict)
    accent_changed = Signal(str)
    destination_requested = Signal(str)
    always_available = True

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Settings")
        self._accent = DEFAULT_ACCENT
        self._loading = False
        self.header = PageHeader("Settings", "Preferences are stored only on this computer.")
        self.content_layout.addWidget(self.header)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        host = QWidget()
        grid = QGridLayout(host)
        grid.setContentsMargins(0, 0, 8, 8)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(12)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self._build_appearance(grid)
        self._build_metadata(grid)
        self._build_ripping(grid)
        self._build_playback(grid)
        self._build_behaviour(grid)
        grid.setRowStretch(3, 1)
        scroll.setWidget(host)
        self.content_layout.addWidget(scroll, 1)
        self._connect_changes()

    def _build_appearance(self, grid: QGridLayout) -> None:
        section = SettingsSection("Appearance")
        form = QFormLayout()
        form.setHorizontalSpacing(18)
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("Dark", "dark")
        self.theme_combo.setAccessibleName("Application theme")
        form.addRow("Theme", self.theme_combo)
        swatches_widget = QWidget()
        swatches = QHBoxLayout(swatches_widget)
        swatches.setContentsMargins(0, 0, 0, 0)
        swatches.setSpacing(7)
        self.accent_buttons: dict[str, QPushButton] = {}
        for colour in ACCENTS:
            button = QPushButton()
            button.setObjectName("accentSwatch")
            button.setCheckable(True)
            button.setStyleSheet(
                f"QPushButton {{ background: {colour}; border: 2px solid transparent; }} "
                "QPushButton:checked { border-color: white; }"
            )
            button.setToolTip(f"Use accent colour {colour}")
            button.setAccessibleName(button.toolTip())
            button.clicked.connect(lambda checked=False, value=colour: self._choose_accent(value))
            swatches.addWidget(button)
            self.accent_buttons[colour] = button
        swatches.addStretch(1)
        form.addRow("Accent", swatches_widget)
        section.layout.addLayout(form)
        self._choose_accent(DEFAULT_ACCENT, emit=False)
        grid.addWidget(section, 0, 0)

    def _build_metadata(self, grid: QGridLayout) -> None:
        section = SettingsSection("Metadata", "Lookup is optional; generic track names remain usable offline.")
        self.metadata_enabled = QCheckBox("Enable metadata lookup")
        self.metadata_enabled.setChecked(True)
        section.layout.addWidget(self.metadata_enabled)
        self.artwork_enabled = QCheckBox("Fetch album artwork")
        self.artwork_enabled.setChecked(True)
        section.layout.addWidget(self.artwork_enabled)
        provider_row = QHBoxLayout()
        provider_row.addWidget(QLabel("Provider"))
        self.provider_combo = QComboBox()
        self.provider_combo.addItem("MusicBrainz")
        self.provider_combo.setEnabled(False)
        self.provider_combo.setToolTip("MusicBrainz is currently the supported metadata provider")
        provider_row.addWidget(self.provider_combo, 1)
        section.layout.addLayout(provider_row)
        contact_row = QHBoxLayout()
        contact_row.addWidget(QLabel("Contact"))
        self.musicbrainz_contact = QLineEdit()
        self.musicbrainz_contact.setPlaceholderText("Email or project URL")
        self.musicbrainz_contact.setAccessibleName("MusicBrainz maintainer contact")
        self.musicbrainz_contact.setToolTip(
            "MusicBrainz requires an identifying contact in API requests; it is not used for an account"
        )
        contact_row.addWidget(self.musicbrainz_contact, 1)
        section.layout.addLayout(contact_row)
        grid.addWidget(section, 0, 1)

    def _build_ripping(self, grid: QGridLayout) -> None:
        section = SettingsSection("Ripping Defaults")
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(18)
        self.rip_format = QComboBox()
        self.rip_format.addItems(["FLAC", "WAV", "MP3"])
        self.rip_format.setAccessibleName("Default rip format")
        form.addRow("Format", self.rip_format)
        self.rip_quality = QComboBox()
        self.rip_quality.setEditable(True)
        self.rip_quality.addItems(["Lossless", "320 kbps", "256 kbps", "192 kbps"])
        self.rip_quality.setAccessibleName("Default rip quality")
        form.addRow("Quality", self.rip_quality)
        destination = QHBoxLayout()
        destination.setSpacing(6)
        self.output_directory = QLineEdit(str(DEFAULT_MUSIC_DIR))
        self.output_directory.setAccessibleName("Default output directory")
        destination.addWidget(self.output_directory, 1)
        browse = QPushButton("Browse…")
        browse.setToolTip("Choose the default output folder")
        browse.clicked.connect(lambda: self.destination_requested.emit(self.output_directory.text()))
        destination.addWidget(browse)
        form.addRow("Destination", destination)
        self.filename_pattern = QLineEdit(DEFAULT_FILENAME_PATTERN)
        self.filename_pattern.setToolTip("Available fields: {track}, {title}, {artist}, {album}")
        form.addRow("File naming", self.filename_pattern)
        section.layout.addLayout(form)
        self.embed_metadata = QCheckBox("Embed metadata")
        self.embed_metadata.setChecked(True)
        section.layout.addWidget(self.embed_metadata)
        self.embed_artwork = QCheckBox("Embed artwork when supported")
        self.embed_artwork.setChecked(True)
        section.layout.addWidget(self.embed_artwork)
        grid.addWidget(section, 1, 0, 1, 2)

    def _build_playback(self, grid: QGridLayout) -> None:
        section = SettingsSection("Playback")
        volume_row = QHBoxLayout()
        volume_row.addWidget(QLabel("Default volume"))
        self.default_volume = QSlider(Qt.Orientation.Horizontal)
        self.default_volume.setRange(0, 100)
        self.default_volume.setValue(72)
        self.default_volume.setAccessibleName("Default playback volume")
        volume_row.addWidget(self.default_volume, 1)
        self.volume_value = QLabel("72%")
        self.volume_value.setObjectName("muted")
        self.volume_value.setFixedWidth(38)
        volume_row.addWidget(self.volume_value)
        section.layout.addLayout(volume_row)
        self.remember_volume = QCheckBox("Remember the last volume")
        self.remember_volume.setChecked(True)
        section.layout.addWidget(self.remember_volume)
        grid.addWidget(section, 2, 0)

    def _build_behaviour(self, grid: QGridLayout) -> None:
        section = SettingsSection("Behaviour")
        self.remember_geometry = QCheckBox("Remember window size and position")
        self.remember_geometry.setChecked(True)
        section.layout.addWidget(self.remember_geometry)
        self.auto_load_disc = QCheckBox("Automatically load inserted discs")
        self.auto_load_disc.setChecked(True)
        section.layout.addWidget(self.auto_load_disc)
        self.auto_metadata = QCheckBox("Look up metadata automatically")
        self.auto_metadata.setChecked(True)
        section.layout.addWidget(self.auto_metadata)
        grid.addWidget(section, 2, 1)

    def values(self) -> dict:
        return {
            "theme": str(self.theme_combo.currentData()),
            "accent": self._accent,
            "metadata_enabled": self.metadata_enabled.isChecked(),
            "artwork_enabled": self.artwork_enabled.isChecked(),
            "musicbrainz_contact": self.musicbrainz_contact.text().strip(),
            "rip_format": self.rip_format.currentText().lower(),
            "rip_quality": self.rip_quality.currentText(),
            "output_directory": self.output_directory.text(),
            "filename_pattern": self.filename_pattern.text().strip() or DEFAULT_FILENAME_PATTERN,
            "embed_metadata": self.embed_metadata.isChecked(),
            "embed_artwork": self.embed_artwork.isChecked(),
            "default_volume": self.default_volume.value(),
            "remember_volume": self.remember_volume.isChecked(),
            "auto_load_disc": self.auto_load_disc.isChecked(),
            "auto_metadata": self.auto_metadata.isChecked(),
            "remember_window_geometry": self.remember_geometry.isChecked(),
        }

    def set_values(self, values: Mapping[str, Any] | object) -> None:
        getter = values.get if isinstance(values, Mapping) else lambda key, default=None: getattr(values, key, default)
        self._loading = True
        theme = str(getter("theme", "dark"))
        index = self.theme_combo.findData(theme)
        self.theme_combo.setCurrentIndex(max(0, index))
        self._choose_accent(str(getter("accent", DEFAULT_ACCENT)), emit=False)
        self.musicbrainz_contact.setText(str(getter("musicbrainz_contact", "")))
        for key, widget in (
            ("metadata_enabled", self.metadata_enabled),
            ("artwork_enabled", self.artwork_enabled),
            ("embed_metadata", self.embed_metadata),
            ("embed_artwork", self.embed_artwork),
            ("remember_volume", self.remember_volume),
            ("auto_load_disc", self.auto_load_disc),
            ("auto_metadata", self.auto_metadata),
            ("remember_window_geometry", self.remember_geometry),
        ):
            widget.setChecked(bool(getter(key, widget.isChecked())))
        self.rip_format.setCurrentText(str(getter("rip_format", "flac")).upper())
        self.rip_quality.setCurrentText(str(getter("rip_quality", "Lossless")))
        self.output_directory.setText(str(getter("output_directory", DEFAULT_MUSIC_DIR)))
        self.output_directory.setCursorPosition(0)
        self.filename_pattern.setText(str(getter("filename_pattern", DEFAULT_FILENAME_PATTERN)))
        self.default_volume.setValue(int(getter("default_volume", 72)))
        self.volume_value.setText(f"{self.default_volume.value()}%")
        self._loading = False

    def set_destination(self, path: str) -> None:
        self.output_directory.setText(path)
        self.output_directory.setCursorPosition(0)
        self._emit_settings()

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        del snapshot

    def _connect_changes(self) -> None:
        self.default_volume.valueChanged.connect(lambda value: self.volume_value.setText(f"{value}%"))
        widgets = (
            self.theme_combo,
            self.metadata_enabled,
            self.artwork_enabled,
            self.musicbrainz_contact,
            self.rip_format,
            self.rip_quality,
            self.output_directory,
            self.filename_pattern,
            self.embed_metadata,
            self.embed_artwork,
            self.default_volume,
            self.remember_volume,
            self.auto_load_disc,
            self.auto_metadata,
            self.remember_geometry,
        )
        for widget in widgets:
            if isinstance(widget, QComboBox):
                widget.currentIndexChanged.connect(self._emit_settings)
                if widget.isEditable():
                    widget.currentTextChanged.connect(self._emit_settings)
            elif isinstance(widget, QLineEdit):
                widget.editingFinished.connect(self._emit_settings)
            elif isinstance(widget, QSlider):
                widget.sliderReleased.connect(self._emit_settings)
            elif isinstance(widget, QCheckBox):
                widget.toggled.connect(self._emit_settings)

    def _choose_accent(self, colour: str, *, emit: bool = True) -> None:
        if colour not in self.accent_buttons:
            colour = DEFAULT_ACCENT
        self._accent = colour
        for value, button in self.accent_buttons.items():
            button.setChecked(value == colour)
        if emit and not self._loading:
            self.accent_changed.emit(colour)
            self._emit_settings()

    def _emit_settings(self, *args) -> None:
        del args
        if not self._loading:
            self.settings_changed.emit(self.values())


__all__ = ["ACCENTS", "SettingsPage", "SettingsSection"]
