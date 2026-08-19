"""Persistent transport controls shown below every content page."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from cdflow.models.album import Album
from cdflow.models.track import Track

from ..icons import symbolic_icon
from .artwork import DiscArtwork
from .common import Card, ElidedLabel, IconButton, format_time


class PlayerBar(Card):
    """Presentation-only player bar with explicit transport signals."""

    play_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    previous_requested = Signal()
    next_requested = Signal()
    seek_requested = Signal(int)
    volume_changed = Signal(int)
    mute_toggled = Signal(bool)
    shuffle_toggled = Signal(bool)
    repeat_toggled = Signal(bool)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Playback controls")
        self.setMinimumHeight(82)
        self.setMaximumHeight(96)
        self._playing = False
        self._muted = False
        self._duration_seconds = 0
        self._updating_volume = False
        self._track_signature: tuple[object, ...] = ()

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 9, 12, 9)
        root.setSpacing(14)
        self.artwork = DiscArtwork(preferred_size=58)
        self.artwork.setFixedSize(58, 58)
        root.addWidget(self.artwork)

        metadata = QVBoxLayout()
        metadata.setSpacing(2)
        self.track_label = ElidedLabel("Nothing playing")
        self.track_label.setObjectName("cardTitle")
        self.artist_label = ElidedLabel("Insert an Audio CD")
        self.artist_label.setObjectName("muted")
        metadata.addWidget(self.track_label)
        metadata.addWidget(self.artist_label)
        metadata.addStretch(1)
        self.metadata_widget = QWidget()
        self.metadata_widget.setLayout(metadata)
        self.metadata_widget.setMinimumWidth(145)
        self.metadata_widget.setMaximumWidth(230)
        root.addWidget(self.metadata_widget, 2)

        transport = QVBoxLayout()
        transport.setSpacing(4)
        buttons = QHBoxLayout()
        buttons.setSpacing(5)
        buttons.addStretch(1)
        self.shuffle_button = IconButton("shuffle", "Shuffle")
        self.shuffle_button.setCheckable(True)
        self.shuffle_button.toggled.connect(self.shuffle_toggled)
        buttons.addWidget(self.shuffle_button)
        self.previous_button = IconButton("previous", "Previous track")
        self.previous_button.clicked.connect(self.previous_requested)
        buttons.addWidget(self.previous_button)
        self.stop_button = IconButton("stop", "Stop playback", size=15)
        self.stop_button.clicked.connect(self.stop_requested)
        buttons.addWidget(self.stop_button)
        self.play_button = QPushButton()
        self.play_button.setObjectName("playButton")
        self.play_button.setIcon(symbolic_icon("play", "#FFFFFF", 18))
        self.play_button.setToolTip("Play")
        self.play_button.setAccessibleName("Play")
        self.play_button.clicked.connect(self._request_play_pause)
        buttons.addWidget(self.play_button)
        self.next_button = IconButton("next", "Next track")
        self.next_button.clicked.connect(self.next_requested)
        buttons.addWidget(self.next_button)
        self.repeat_button = IconButton("repeat", "Repeat")
        self.repeat_button.setCheckable(True)
        self.repeat_button.toggled.connect(self.repeat_toggled)
        buttons.addWidget(self.repeat_button)
        buttons.addStretch(1)
        transport.addLayout(buttons)

        progress = QHBoxLayout()
        progress.setSpacing(8)
        self.elapsed_label = QLabel("0:00")
        self.elapsed_label.setObjectName("muted")
        self.elapsed_label.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.elapsed_label.setFixedWidth(42)
        progress.addWidget(self.elapsed_label)
        self.position_slider = QSlider(Qt.Orientation.Horizontal)
        self.position_slider.setRange(0, 0)
        self.position_slider.setToolTip("Playback position")
        self.position_slider.setAccessibleName("Playback position")
        self.position_slider.sliderReleased.connect(self._seek)
        progress.addWidget(self.position_slider, 1)
        self.duration_label = QLabel("0:00")
        self.duration_label.setObjectName("muted")
        self.duration_label.setFixedWidth(42)
        progress.addWidget(self.duration_label)
        transport.addLayout(progress)
        root.addLayout(transport, 6)

        volume = QHBoxLayout()
        volume.setSpacing(6)
        self.mute_button = IconButton("volume", "Mute")
        self.mute_button.clicked.connect(self._toggle_mute)
        volume.addWidget(self.mute_button)
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(75)
        self.volume_slider.setFixedWidth(100)
        self.volume_slider.setToolTip("Volume")
        self.volume_slider.setAccessibleName("Playback volume")
        self.volume_slider.valueChanged.connect(self._volume_changed)
        volume.addWidget(self.volume_slider)
        root.addLayout(volume)
        self.set_audio_enabled(False)

    def set_audio_enabled(self, enabled: bool) -> None:
        for widget in (
            self.shuffle_button,
            self.previous_button,
            self.stop_button,
            self.play_button,
            self.next_button,
            self.repeat_button,
            self.position_slider,
        ):
            widget.setEnabled(enabled)
        if not enabled:
            self.set_playing(False)
            self.set_position(0, 0, seekable=False)

    def set_track(self, track: Track | None, album: Album | None = None) -> None:
        signature = (
            track.number if track else 0,
            track.title if track else "",
            track.artist if track else "",
            album.disc_id if album else "",
            album.artist if album else "",
            album.artwork_path if album else "",
        )
        if signature == self._track_signature:
            return
        self._track_signature = signature
        if track is None:
            self.track_label.setText("Nothing playing")
            self.artist_label.setText(album.artist if album else "Insert an Audio CD")
            self.artwork.set_artwork(album.artwork_path if album else "")
            return
        self.track_label.setText(track.title)
        self.artist_label.setText(track.artist or (album.artist if album else "Unknown Artist"))
        self.track_label.setAccessibleName(f"Current track: {track.title}")
        self.artwork.set_artwork(album.artwork_path if album else "")
        self.set_position(0, track.duration_seconds, seekable=True)

    def set_playing(self, playing: bool) -> None:
        self._playing = bool(playing)
        name = "pause" if self._playing else "play"
        label = "Pause" if self._playing else "Play"
        self.play_button.setIcon(symbolic_icon(name, "#FFFFFF", 18))
        self.play_button.setToolTip(label)
        self.play_button.setAccessibleName(label)

    def set_position(
        self, elapsed_seconds: float, duration_seconds: float | None = None, *, seekable: bool = True
    ) -> None:
        if duration_seconds is not None:
            self._duration_seconds = max(0, round(duration_seconds))
            self.position_slider.setRange(0, self._duration_seconds)
            self.duration_label.setText(format_time(self._duration_seconds))
        elapsed = min(max(0, round(elapsed_seconds)), self._duration_seconds)
        if not self.position_slider.isSliderDown():
            self.position_slider.setValue(elapsed)
        self.elapsed_label.setText(format_time(elapsed))
        self.position_slider.setEnabled(seekable and self._duration_seconds > 0 and self.play_button.isEnabled())

    def set_volume(self, volume: int, muted: bool = False) -> None:
        self._updating_volume = True
        self.volume_slider.setValue(max(0, min(100, int(volume))))
        self._updating_volume = False
        self._muted = bool(muted)
        self.mute_button.set_symbol("mute" if self._muted or volume == 0 else "volume")
        self.mute_button.setToolTip("Unmute" if self._muted else "Mute")
        self.mute_button.setAccessibleName(self.mute_button.toolTip())

    def set_modes(self, *, shuffle: bool | None = None, repeat: bool | None = None) -> None:
        if shuffle is not None:
            self.shuffle_button.setChecked(shuffle)
        if repeat is not None:
            self.repeat_button.setChecked(repeat)

    def set_compact(self, compact: bool) -> None:
        self.shuffle_button.setVisible(not compact)
        self.repeat_button.setVisible(not compact)
        self.stop_button.setVisible(not compact)
        self.artist_label.setVisible(not compact)
        self.metadata_widget.setMaximumWidth(165 if compact else 230)
        self.volume_slider.setFixedWidth(72 if compact else 100)

    def _request_play_pause(self) -> None:
        (self.pause_requested if self._playing else self.play_requested).emit()

    def _seek(self) -> None:
        self.seek_requested.emit(self.position_slider.value())

    def _volume_changed(self, value: int) -> None:
        if not self._updating_volume:
            self.volume_changed.emit(value)

    def _toggle_mute(self) -> None:
        self._muted = not self._muted
        self.mute_button.set_symbol("mute" if self._muted else "volume")
        self.mute_button.setToolTip("Unmute" if self._muted else "Mute")
        self.mute_button.setAccessibleName(self.mute_button.toolTip())
        self.mute_toggled.emit(self._muted)


__all__ = ["PlayerBar"]
