"""Qt-safe direct CDDA playback through GStreamer."""

from __future__ import annotations

from contextlib import suppress
from enum import StrEnum
from typing import Any

from cdflow.models.disc import Drive
from cdflow.models.track import Track

from ._qt import QObject, QTimer, Signal, Slot


class PlaybackState(StrEnum):
    UNAVAILABLE = "unavailable"
    STOPPED = "stopped"
    PLAYING = "playing"
    PAUSED = "paused"
    BUFFERING = "buffering"
    ERROR = "error"


class AudioBackendUnavailable(RuntimeError):
    pass


_GST: Any = None
_GST_IMPORT_ERROR = ""


def _load_gstreamer() -> Any:
    global _GST, _GST_IMPORT_ERROR
    if _GST is not None:
        return _GST
    if _GST_IMPORT_ERROR:
        raise AudioBackendUnavailable(_GST_IMPORT_ERROR)
    try:
        import gi

        gi.require_version("Gst", "1.0")
        from gi.repository import Gst

        Gst.init(None)
    except (ImportError, ValueError, RuntimeError) as error:
        _GST_IMPORT_ERROR = f"GStreamer Python bindings are unavailable: {error}"
        raise AudioBackendUnavailable(_GST_IMPORT_ERROR) from error
    _GST = Gst
    return Gst


class AudioPlayer(QObject):
    """Play audio tracks directly from an optical device.

    GStreamer performs decoding and device I/O in its own streaming threads. A
    Qt timer is active only during playback to drain the bus and report position,
    so an idle CDFlow instance does no playback polling.
    """

    availability_changed = Signal(bool, str)
    state_changed = Signal(str)
    track_changed = Signal(int)
    position_changed = Signal(int, int)
    seekability_changed = Signal(bool)
    volume_changed = Signal(float)
    muted_changed = Signal(bool)
    track_finished = Signal(int)
    finished = Signal()
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._gst: Any = None
        self._pipeline: Any = None
        self._bus: Any = None
        self._device = ""
        self._tracks: tuple[Track, ...] = ()
        self._current_track = 0
        self._expected_duration_ms = 0
        self._state = PlaybackState.STOPPED
        self._seekable = False
        self._volume = 0.8
        self._muted = False
        self.auto_advance = True
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._tick)

    @property
    def state(self) -> PlaybackState:
        return self._state

    @property
    def current_track(self) -> int:
        return self._current_track

    @property
    def device(self) -> str:
        return self._device

    @property
    def tracks(self) -> tuple[Track, ...]:
        return self._tracks

    @property
    def available(self) -> bool:
        try:
            self._ensure_pipeline()
        except AudioBackendUnavailable:
            return False
        return True

    def set_disc(self, device: str, tracks: list[Track] | tuple[Track, ...]) -> None:
        if not device:
            raise ValueError("an optical device path is required for playback")
        ordered = tuple(sorted(tracks, key=lambda track: track.number))
        if not ordered:
            raise ValueError("an audio disc must contain at least one track")
        if device != self._device or ordered != self._tracks:
            self.stop()
            self._device = device
            self._tracks = ordered
            self._current_track = 0
            self.position_changed.emit(0, 0)

    def clear_disc(self) -> None:
        self.stop()
        self._device = ""
        self._tracks = ()
        self._current_track = 0

    @Slot(object)
    def on_media_removed(self, drive: Drive) -> None:
        if not self._device or not drive.device or drive.device == self._device:
            self.clear_disc()

    @Slot()
    def play(self, track_number: int | None = None) -> None:
        if not self._device or not self._tracks:
            self._fail("No audio CD is ready for playback")
            return
        if track_number is None and self._state == PlaybackState.PAUSED and self._pipeline is not None:
            self._set_pipeline_state("PLAYING")
            self._set_state(PlaybackState.PLAYING)
            self._timer.start()
            return
        selected = track_number or self._current_track or self._tracks[0].number
        if not self._track_by_number(selected):
            self._fail(f"Track {selected} is not present on this disc")
            return
        try:
            self._start_track(selected)
        except AudioBackendUnavailable as error:
            self.availability_changed.emit(False, str(error))
            self._fail(str(error))

    def play_track(self, track_number: int) -> None:
        self.play(track_number)

    @Slot()
    def pause(self) -> None:
        if self._pipeline is None or self._state != PlaybackState.PLAYING:
            return
        self._set_pipeline_state("PAUSED")
        self._timer.stop()
        self._drain_bus()
        self._set_state(PlaybackState.PAUSED)

    @Slot()
    def stop(self) -> None:
        self._timer.stop()
        if self._pipeline is not None and self._gst is not None:
            self._pipeline.set_state(self._gst.State.NULL)
        self._set_state(PlaybackState.STOPPED)
        if self._current_track:
            self.position_changed.emit(0, self._expected_duration_ms)

    @Slot()
    def next_track(self) -> None:
        index = self._current_index()
        if index is None:
            self.play()
        elif index + 1 < len(self._tracks):
            self.play(self._tracks[index + 1].number)

    @Slot()
    def previous_track(self) -> None:
        index = self._current_index()
        if index is None:
            self.play()
        elif index > 0:
            self.play(self._tracks[index - 1].number)
        elif self._seekable:
            self.seek(0)

    def seek(self, milliseconds: int) -> bool:
        if self._pipeline is None or self._gst is None or not self._seekable:
            return False
        target = max(0, min(int(milliseconds), self._expected_duration_ms))
        success = bool(
            self._pipeline.seek_simple(
                self._gst.Format.TIME,
                self._gst.SeekFlags.FLUSH | self._gst.SeekFlags.KEY_UNIT,
                target * self._gst.MSECOND,
            )
        )
        if success:
            self.position_changed.emit(target, self._expected_duration_ms)
        return success

    def set_volume(self, volume: float) -> None:
        value = max(0.0, min(float(volume), 1.0))
        self._volume = value
        if self._pipeline is not None:
            self._pipeline.set_property("volume", value)
        self.volume_changed.emit(value)

    def set_muted(self, muted: bool) -> None:
        self._muted = bool(muted)
        if self._pipeline is not None:
            self._pipeline.set_property("mute", self._muted)
        self.muted_changed.emit(self._muted)

    def toggle_muted(self) -> None:
        self.set_muted(not self._muted)

    def shutdown(self) -> None:
        self.clear_disc()
        self._pipeline = None
        self._bus = None

    def _ensure_pipeline(self) -> None:
        if self._pipeline is not None:
            return
        gst = _load_gstreamer()
        if gst.ElementFactory.find("cdparanoiasrc") is None and gst.ElementFactory.find("cdiocddasrc") is None:
            raise AudioBackendUnavailable(
                "No GStreamer CDDA source is installed (cdparanoiasrc or cdiocddasrc is required)"
            )
        if not any(gst.ElementFactory.find(name) is not None for name in ("pipewiresink", "pulsesink", "alsasink")):
            raise AudioBackendUnavailable("No supported GStreamer audio output is installed")
        pipeline = gst.ElementFactory.make("playbin3", "cdflow-player") or gst.ElementFactory.make(
            "playbin", "cdflow-player"
        )
        if pipeline is None:
            raise AudioBackendUnavailable("GStreamer could not create a playbin audio pipeline")
        try:
            pipeline.connect("source-setup", self._configure_source)
        except TypeError:
            pipeline.connect("notify::source", self._configure_source)
        pipeline.set_property("volume", self._volume)
        pipeline.set_property("mute", self._muted)
        self._gst = gst
        self._pipeline = pipeline
        self._bus = pipeline.get_bus()
        self.availability_changed.emit(True, "")

    def _configure_source(self, pipeline: Any, source_or_spec: Any) -> None:
        source = source_or_spec
        if not hasattr(source, "find_property"):
            try:
                source = pipeline.get_property("source")
            except (AttributeError, TypeError):
                return
        if source is None:
            return
        if source.find_property("device") is not None and self._device:
            source.set_property("device", self._device)
        if source.find_property("automatic-eos") is not None:
            source.set_property("automatic-eos", True)
        for signal_name in ("transport-error", "uncorrected-error"):
            with suppress(TypeError):
                source.connect(signal_name, self._source_read_error)

    def _source_read_error(self, _source: Any, sector: int) -> None:
        self.error_occurred.emit(f"The CD drive reported an unreadable sector near {sector}")

    def _start_track(self, track_number: int) -> None:
        self._ensure_pipeline()
        assert self._pipeline is not None and self._gst is not None
        changed_track = track_number != self._current_track
        reused_source = False
        if (
            self._current_track
            and changed_track
            and self._state
            in {
                PlaybackState.PLAYING,
                PlaybackState.PAUSED,
            }
        ):
            # GstAudioCdSrc documents TRACK-format seeks as the efficient way to
            # switch tracks without closing and reopening the optical device.
            try:
                track_format = self._gst.Format.get_by_nick("track")
                reused_source = bool(
                    self._pipeline.seek_simple(
                        track_format,
                        self._gst.SeekFlags.FLUSH,
                        track_number,
                    )
                )
            except (AttributeError, TypeError, ValueError):
                reused_source = False
        if not reused_source:
            self._pipeline.set_state(self._gst.State.READY)
            self._pipeline.set_property("uri", f"cdda://{track_number}")
        track = self._track_by_number(track_number)
        self._current_track = track_number
        self._expected_duration_ms = track.duration_milliseconds if track else 0
        self._set_pipeline_state("PLAYING")
        if changed_track:
            self.track_changed.emit(track_number)
        self.position_changed.emit(0, self._expected_duration_ms)
        self._set_state(PlaybackState.PLAYING)
        self._timer.start()

    def _set_pipeline_state(self, name: str) -> None:
        assert self._pipeline is not None and self._gst is not None
        result = self._pipeline.set_state(getattr(self._gst.State, name))
        if result == self._gst.StateChangeReturn.FAILURE:
            raise AudioBackendUnavailable(f"GStreamer could not enter the {name.casefold()} state")

    @Slot()
    def _tick(self) -> None:
        self._drain_bus()
        if self._state != PlaybackState.PLAYING or self._pipeline is None or self._gst is None:
            return
        try:
            success, position = self._pipeline.query_position(self._gst.Format.TIME)
        except (AttributeError, TypeError):
            success, position = False, 0
        if success:
            position_ms = max(0, int(position // self._gst.MSECOND))
            if self._expected_duration_ms:
                position_ms = min(position_ms, self._expected_duration_ms)
            self.position_changed.emit(position_ms, self._expected_duration_ms)
        self._update_seekability()

    def _drain_bus(self) -> None:
        if self._bus is None or self._gst is None:
            return
        mask = (
            self._gst.MessageType.ERROR
            | self._gst.MessageType.EOS
            | self._gst.MessageType.BUFFERING
            | self._gst.MessageType.STATE_CHANGED
        )
        while True:
            message = self._bus.timed_pop_filtered(0, mask)
            if message is None:
                break
            if message.type == self._gst.MessageType.ERROR:
                error, debug = message.parse_error()
                detail = str(error)
                if debug:
                    detail = f"{detail} ({debug})"
                self._timer.stop()
                self._set_state(PlaybackState.ERROR)
                self.error_occurred.emit(detail)
            elif message.type == self._gst.MessageType.EOS:
                completed_track = self._current_track
                self.track_finished.emit(completed_track)
                index = self._current_index()
                if self.auto_advance and index is not None and index + 1 < len(self._tracks):
                    self._start_track(self._tracks[index + 1].number)
                else:
                    self.stop()
                    self.finished.emit()
            elif message.type == self._gst.MessageType.BUFFERING:
                percent = message.parse_buffering()
                if percent < 100 and self._state == PlaybackState.PLAYING:
                    self._set_state(PlaybackState.BUFFERING)
                elif percent >= 100 and self._state == PlaybackState.BUFFERING:
                    self._set_state(PlaybackState.PLAYING)

    def _update_seekability(self) -> None:
        if self._pipeline is None or self._gst is None:
            return
        try:
            success, seekable, _start, _end = self._pipeline.query_seeking(self._gst.Format.TIME)
            value = bool(success and seekable)
        except (AttributeError, TypeError):
            value = False
        if value != self._seekable:
            self._seekable = value
            self.seekability_changed.emit(value)

    def _track_by_number(self, number: int) -> Track | None:
        return next((track for track in self._tracks if track.number == number), None)

    def _current_index(self) -> int | None:
        return next(
            (index for index, track in enumerate(self._tracks) if track.number == self._current_track),
            None,
        )

    def _set_state(self, state: PlaybackState) -> None:
        if state != self._state:
            self._state = state
            self.state_changed.emit(state.value)

    def _fail(self, message: str) -> None:
        self._set_state(PlaybackState.ERROR)
        self.error_occurred.emit(message)


__all__ = ["AudioBackendUnavailable", "AudioPlayer", "PlaybackState"]
