"""Two-column ripping configuration with an in-place progress state."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdflow.app.constants import DEFAULT_FILENAME_PATTERN, DEFAULT_MUSIC_DIR, DEFAULT_RIP_FORMAT, DEFAULT_RIP_QUALITY
from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.disc import DiscKind

from ..icons import symbolic_icon
from ..theme import DEFAULT_THEME
from ..widgets.common import Card, ElidedLabel, PageHeader, format_time
from ..widgets.track_table import TrackTable
from .base import StatefulPage


class RipCDPage(StatefulPage):
    """Collect rip options and display worker progress without owning a worker."""

    rip_requested = Signal(dict)
    cancel_rip_requested = Signal()
    destination_requested = Signal(str)
    configuration_changed = Signal(dict)
    available_statuses = {AppStatus.AUDIO_CD, AppStatus.RIPPING}
    available_disc_kinds = {DiscKind.MIXED}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Rip CD")
        self._disc_id = ""
        self.header = PageHeader("Rip Audio CD", "Choose the tracks and lossless-quality settings you want.")
        self.content_layout.addWidget(self.header)
        self.mode_stack = QStackedWidget()
        self.content_layout.addWidget(self.mode_stack, 1)
        self._build_configuration_view()
        self._build_progress_view()
        self.mode_stack.setCurrentWidget(self.configuration_view)

    def _build_configuration_view(self) -> None:
        self.configuration_view = QWidget()
        columns = QHBoxLayout(self.configuration_view)
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(12)

        settings_card = Card()
        settings_card.setMinimumWidth(300)
        settings_card.setMaximumWidth(410)
        settings = QVBoxLayout(settings_card)
        settings.setContentsMargins(16, 15, 16, 16)
        settings.setSpacing(12)
        title = QLabel("Rip Settings")
        title.setObjectName("sectionTitle")
        settings.addWidget(title)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        form.setFormAlignment(Qt.AlignmentFlag.AlignTop)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["FLAC", "WAV", "MP3"])
        self.format_combo.setCurrentText(DEFAULT_RIP_FORMAT.upper())
        self.format_combo.setAccessibleName("Output format")
        form.addRow("Output format", self.format_combo)
        self.quality_combo = QComboBox()
        self.quality_combo.setAccessibleName("Encoding quality")
        form.addRow("Quality", self.quality_combo)
        destination_row = QHBoxLayout()
        destination_row.setSpacing(6)
        compact_destination = str(DEFAULT_MUSIC_DIR).replace(str(Path.home()), "~", 1)
        self.destination_edit = QLineEdit(compact_destination)
        self.destination_edit.setAccessibleName("Rip destination folder")
        self.destination_edit.setToolTip("Files are organized beneath this folder")
        destination_row.addWidget(self.destination_edit, 1)
        self.destination_button = QPushButton("Browse…")
        self.destination_button.setToolTip("Choose an output folder")
        self.destination_button.clicked.connect(lambda: self.destination_requested.emit(self.destination_edit.text()))
        destination_row.addWidget(self.destination_button)
        form.addRow("Destination", destination_row)
        self.pattern_edit = QLineEdit(DEFAULT_FILENAME_PATTERN)
        self.pattern_edit.setPlaceholderText("{track:02d} - {title}")
        self.pattern_edit.setAccessibleName("Filename pattern")
        self.pattern_edit.setToolTip("Available fields: {track}, {title}, {artist}, {album}")
        form.addRow("File naming", self.pattern_edit)
        settings.addLayout(form)
        self.embed_metadata = QCheckBox("Embed track and album metadata")
        self.embed_metadata.setChecked(True)
        settings.addWidget(self.embed_metadata)
        self.embed_artwork = QCheckBox("Embed album artwork when supported")
        self.embed_artwork.setChecked(True)
        settings.addWidget(self.embed_artwork)
        self.organize_folders = QCheckBox("Organize into Artist / Album folders")
        self.organize_folders.setChecked(True)
        settings.addWidget(self.organize_folders)
        settings.addStretch(1)
        self.rip_button = QPushButton("Rip Selected Tracks")
        self.rip_button.setObjectName("primaryButton")
        self.rip_button.setIcon(symbolic_icon("rip", "#FFFFFF", 17))
        self.rip_button.setToolTip("Start secure audio extraction")
        self.rip_button.clicked.connect(self._request_rip)
        settings.addWidget(self.rip_button)
        columns.addWidget(settings_card, 4)

        tracks_card = Card()
        tracks = QVBoxLayout(tracks_card)
        tracks.setContentsMargins(0, 0, 0, 0)
        tracks.setSpacing(0)
        track_header = QHBoxLayout()
        track_header.setContentsMargins(13, 9, 13, 8)
        heading = QLabel("Tracks to Rip")
        heading.setObjectName("sectionTitle")
        track_header.addWidget(heading)
        track_header.addStretch(1)
        self.selection_summary = QLabel("0 selected")
        self.selection_summary.setObjectName("muted")
        track_header.addWidget(self.selection_summary)
        self.select_all = QCheckBox("Select All")
        self.select_all.setChecked(True)
        self.select_all.toggled.connect(self._select_all_toggled)
        track_header.addWidget(self.select_all)
        tracks.addLayout(track_header)
        self.track_table = TrackTable(checkable=True, show_status=False)
        self.track_table.rip_selection_changed.connect(self._selection_changed)
        tracks.addWidget(self.track_table, 1)
        columns.addWidget(tracks_card, 7)
        self.mode_stack.addWidget(self.configuration_view)

        self.format_combo.currentTextChanged.connect(self._format_changed)
        self.format_combo.currentTextChanged.connect(self._emit_configuration)
        self.quality_combo.currentTextChanged.connect(self._emit_configuration)
        self.destination_edit.textChanged.connect(self._emit_configuration)
        self.pattern_edit.textChanged.connect(self._emit_configuration)
        self.embed_metadata.toggled.connect(self._emit_configuration)
        self.embed_artwork.toggled.connect(self._emit_configuration)
        self.organize_folders.toggled.connect(self._emit_configuration)
        self._format_changed(self.format_combo.currentText())

    def _build_progress_view(self) -> None:
        self.progress_view = QWidget()
        outer = QVBoxLayout(self.progress_view)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        card = Card()
        card.setMaximumWidth(720)
        card.setMinimumWidth(480)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(12)
        heading_row = QHBoxLayout()
        self.progress_icon = QLabel()
        self.progress_icon.setPixmap(symbolic_icon("rip", DEFAULT_THEME.accent, 26).pixmap(26, 26))
        heading_row.addWidget(self.progress_icon)
        heading_labels = QVBoxLayout()
        self.progress_title = QLabel("Ripping Audio CD")
        self.progress_title.setObjectName("albumTitle")
        heading_labels.addWidget(self.progress_title)
        self.progress_message = QLabel("Preparing extraction…")
        self.progress_message.setObjectName("muted")
        heading_labels.addWidget(self.progress_message)
        heading_row.addLayout(heading_labels, 1)
        layout.addLayout(heading_row)
        layout.addSpacing(6)
        self.current_track_label = ElidedLabel("Preparing first track")
        self.current_track_label.setObjectName("cardTitle")
        layout.addWidget(self.current_track_label)
        self.track_progress = QProgressBar()
        self.track_progress.setRange(0, 1000)
        self.track_progress.setAccessibleName("Current track progress")
        layout.addWidget(self.track_progress)
        detail_row = QHBoxLayout()
        self.elapsed_label = QLabel("Elapsed 0:00")
        self.elapsed_label.setObjectName("muted")
        detail_row.addWidget(self.elapsed_label)
        detail_row.addStretch(1)
        self.track_percent_label = QLabel("0%")
        self.track_percent_label.setObjectName("muted")
        detail_row.addWidget(self.track_percent_label)
        layout.addLayout(detail_row)
        layout.addSpacing(8)
        overall_title = QLabel("Overall Progress")
        overall_title.setObjectName("cardTitle")
        layout.addWidget(overall_title)
        self.overall_progress = QProgressBar()
        self.overall_progress.setRange(0, 1000)
        self.overall_progress.setAccessibleName("Overall rip progress")
        layout.addWidget(self.overall_progress)
        self.destination_label = ElidedLabel("Destination: —")
        self.destination_label.setObjectName("muted")
        layout.addWidget(self.destination_label)
        actions = QHBoxLayout()
        actions.addStretch(1)
        self.cancel_button = QPushButton("Cancel Ripping")
        self.cancel_button.setObjectName("dangerButton")
        self.cancel_button.setIcon(symbolic_icon("cancel", DEFAULT_THEME.danger, 15))
        self.cancel_button.clicked.connect(self.cancel_rip_requested)
        actions.addWidget(self.cancel_button)
        self.done_button = QPushButton("Back to Rip Settings")
        self.done_button.clicked.connect(lambda: self.mode_stack.setCurrentWidget(self.configuration_view))
        self.done_button.setVisible(False)
        actions.addWidget(self.done_button)
        layout.addLayout(actions)
        outer.addWidget(card, 0, Qt.AlignmentFlag.AlignHCenter)
        outer.addStretch(1)
        self.mode_stack.addWidget(self.progress_view)

    def configuration(self) -> dict:
        """Return a serializable snapshot suitable for the ripping service."""

        return {
            "format": self.format_combo.currentText().lower(),
            "quality": self.quality_combo.currentText(),
            "destination": str(Path(self.destination_edit.text()).expanduser()),
            "filename_pattern": self.pattern_edit.text().strip() or DEFAULT_FILENAME_PATTERN,
            "embed_metadata": self.embed_metadata.isChecked(),
            "embed_artwork": self.embed_artwork.isChecked(),
            "organize_folders": self.organize_folders.isChecked(),
            "tracks": self.track_table.checked_track_numbers(),
        }

    def set_configuration(self, values: Mapping[str, object]) -> None:
        if "format" in values:
            self.format_combo.setCurrentText(str(values["format"]).upper())
        if "quality" in values:
            self.quality_combo.setCurrentText(str(values["quality"]))
        if "destination" in values:
            self.destination_edit.setText(str(values["destination"]))
            self.destination_edit.setCursorPosition(0)
        if "filename_pattern" in values:
            self.pattern_edit.setText(str(values["filename_pattern"]))
        for key, widget in (
            ("embed_metadata", self.embed_metadata),
            ("embed_artwork", self.embed_artwork),
            ("organize_folders", self.organize_folders),
        ):
            if key in values:
                widget.setChecked(bool(values[key]))

    def set_destination(self, path: str) -> None:
        self.destination_edit.setText(path)
        self.destination_edit.setCursorPosition(0)

    def set_rip_progress(
        self,
        *,
        current_track: str = "",
        track_progress: float = 0.0,
        overall_progress: float = 0.0,
        elapsed_seconds: float = 0.0,
        destination: str = "",
        message: str = "",
        active: bool = True,
        completed: bool = False,
        error: str = "",
    ) -> None:
        self.mode_stack.setCurrentWidget(self.progress_view)
        self.current_track_label.setText(current_track or "Preparing extraction")
        track_value = max(0, min(1000, round(track_progress * 1000 if track_progress <= 1 else track_progress * 10)))
        overall_value = max(
            0, min(1000, round(overall_progress * 1000 if overall_progress <= 1 else overall_progress * 10))
        )
        self.track_progress.setValue(track_value)
        self.overall_progress.setValue(overall_value)
        self.track_percent_label.setText(f"{track_value / 10:.0f}%")
        self.elapsed_label.setText(f"Elapsed {format_time(elapsed_seconds)}")
        self.destination_label.setText(f"Destination: {destination or self.destination_edit.text()}")
        if error:
            self.progress_title.setText("Rip Failed")
            self.progress_message.setText(error)
            self.progress_message.setObjectName("danger")
            self.progress_icon.setPixmap(symbolic_icon("error", DEFAULT_THEME.danger, 26).pixmap(26, 26))
        elif completed:
            self.progress_title.setText("Rip Complete")
            self.progress_message.setText(message or "Selected tracks were saved successfully.")
            self.progress_message.setObjectName("muted")
            self.progress_icon.setPixmap(symbolic_icon("check", DEFAULT_THEME.success, 26).pixmap(26, 26))
        elif not active:
            self.progress_title.setText("Ripping Stopped")
            self.progress_message.setText(message or "The extraction has stopped.")
            self.progress_message.setObjectName("muted")
            self.progress_icon.setPixmap(symbolic_icon("info", DEFAULT_THEME.text_muted, 26).pixmap(26, 26))
        else:
            self.progress_title.setText("Ripping Audio CD")
            self.progress_message.setText(message or "Secure extraction is in progress.")
            self.progress_message.setObjectName("muted")
            self.progress_icon.setPixmap(symbolic_icon("rip", DEFAULT_THEME.accent, 26).pixmap(26, 26))
        self.progress_message.style().unpolish(self.progress_message)
        self.progress_message.style().polish(self.progress_message)
        self.cancel_button.setVisible(active and not completed and not error)
        self.done_button.setVisible(completed or bool(error) or not active)

    def reset_progress(self) -> None:
        self.track_progress.setValue(0)
        self.overall_progress.setValue(0)
        self.mode_stack.setCurrentWidget(self.configuration_view)

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        album = snapshot.disc.album if snapshot.disc else None
        tracks = album.tracks if album else []
        disc_id = snapshot.disc.disc_id if snapshot.disc else ""
        same_disc = bool(disc_id and disc_id == self._disc_id)
        existing = set(self.track_table.checked_track_numbers()) if same_disc else set()
        self._disc_id = disc_id
        self.track_table.set_tracks(tracks, preserve_checks=same_disc)
        if existing:
            # Preserve user choices across metadata refreshes.
            for row, track in enumerate(self.track_table.track_model.tracks):
                desired = track.number in existing
                index = self.track_table.track_model.index(row, 0)
                self.track_table.track_model.setData(
                    index,
                    Qt.CheckState.Checked if desired else Qt.CheckState.Unchecked,
                    Qt.ItemDataRole.CheckStateRole,
                )
        self._update_selection_summary()
        if album:
            self.header.set_subtitle(f"{album.title} · {album.artist} · {len(tracks)} tracks")
        if snapshot.status == AppStatus.RIPPING and self.mode_stack.currentWidget() is self.configuration_view:
            self.set_rip_progress(message=snapshot.message, active=True)

    def _format_changed(self, output_format: str) -> None:
        current = self.quality_combo.currentText()
        qualities = {
            "FLAC": ["Lossless (Level 5)", "Lossless (Fast)", "Lossless (Maximum)"],
            "WAV": ["PCM 16-bit / 44.1 kHz"],
            "MP3": ["320 kbps", "256 kbps", "192 kbps", "V0 Variable"],
        }.get(output_format, [DEFAULT_RIP_QUALITY])
        self.quality_combo.blockSignals(True)
        self.quality_combo.clear()
        self.quality_combo.addItems(qualities)
        if current in qualities:
            self.quality_combo.setCurrentText(current)
        self.quality_combo.blockSignals(False)

    def _select_all_toggled(self, checked: bool) -> None:
        self.track_table.set_all_checked(checked)
        self._update_selection_summary()

    def _selection_changed(self, track_number: int, checked: bool) -> None:
        del track_number, checked
        self._update_selection_summary()
        self._emit_configuration()

    def _update_selection_summary(self) -> None:
        selected = len(self.track_table.checked_track_numbers())
        total = len(self.track_table.track_model.tracks)
        self.selection_summary.setText(f"{selected} of {total} selected")
        self.rip_button.setEnabled(selected > 0)
        self.select_all.blockSignals(True)
        self.select_all.setChecked(total > 0 and selected == total)
        self.select_all.blockSignals(False)

    def _request_rip(self) -> None:
        config = self.configuration()
        if config["tracks"]:
            self.rip_requested.emit(config)

    def _emit_configuration(self, *args) -> None:
        del args
        self.configuration_changed.emit(self.configuration())


__all__ = ["RipCDPage"]
