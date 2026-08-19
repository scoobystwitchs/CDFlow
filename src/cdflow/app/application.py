"""Qt application bootstrap and coordination between the view and services."""

from __future__ import annotations

import base64
import logging
import random
import sqlite3
import threading
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import QApplication, QFileDialog

from cdflow.app.constants import APP_ID, APP_NAME, ORGANIZATION_NAME, VERSION
from cdflow.app.demo import demo_audio_disc, demo_data_disc
from cdflow.app.settings import Preferences, SettingsStore
from cdflow.app.state import ApplicationState, AppStatus
from cdflow.models import Disc, DiscKind, Drive
from cdflow.services.artwork import ArtworkResult, ArtworkService
from cdflow.services.audio_player import AudioPlayer, PlaybackState
from cdflow.services.dependencies import DependencyDetector, DependencyReport
from cdflow.services.disc_reader import DiscInspection, DiscReader
from cdflow.services.drive_monitor import DriveMonitor
from cdflow.services.library import LibraryRepository
from cdflow.services.metadata import MetadataLookup, MetadataService
from cdflow.services.ripper import RipFormat, RipJob, RipOptions, Ripper, RipResult
from cdflow.ui.main_window import MainWindow
from cdflow.ui.theme import apply_theme

LOGGER = logging.getLogger(__name__)


class ApplicationController(QObject):
    """Own services and reduce their events into the central state model."""

    dependency_report_ready = Signal(object)

    def __init__(
        self,
        app: QApplication,
        window: MainWindow,
        settings: SettingsStore,
        preferences: Preferences,
        *,
        demo_mode: str | None = None,
    ) -> None:
        super().__init__(app)
        self.app = app
        self.window = window
        self.settings = settings
        self.preferences = preferences
        self.demo_mode = demo_mode
        self.state = ApplicationState()
        self._active_inspection: DiscInspection | None = None
        self._disc_before_eject: Disc | None = None
        self._pending_eject_path = ""
        self._active_rip_job: RipJob | None = None
        self._mount_attempted = False
        self._request_generation = 0
        self._active_metadata_request: tuple[int, str, bool] | None = None
        self._active_artwork_request: tuple[int, str, str] | None = None
        self._shutting_down = False
        self._library_warning = ""
        self.dependency_report: DependencyReport | None = None

        try:
            self.library = LibraryRepository()
        except (OSError, RuntimeError, sqlite3.Error) as error:
            if LOGGER.isEnabledFor(logging.DEBUG):
                LOGGER.exception("Could not open the local collection")
            else:
                LOGGER.warning("Could not open the local collection; using a temporary in-memory store")
            self.library = LibraryRepository(":memory:")
            self._library_warning = f"The local collection could not be opened: {error}"

        self.monitor = DriveMonitor(self)
        self.reader = DiscReader(self.library, self)
        self.player = AudioPlayer(self)
        self.ripper = Ripper(self.library, self)
        self.metadata = MetadataService(
            self.library,
            contact=self.preferences.musicbrainz_contact,
            parent=self,
        )
        self.artwork = ArtworkService(contact=self.preferences.musicbrainz_contact, parent=self)

        self._rip_started_at = 0.0
        self._rip_view: dict[str, Any] = {
            "current_track": "Preparing extraction",
            "track_progress": 0.0,
            "overall_progress": 0.0,
            "destination": "",
            "message": "",
        }
        self._rip_timer = QTimer(self)
        self._rip_timer.setInterval(500)
        self._rip_timer.timeout.connect(self._refresh_rip_elapsed)

        self._volume_save_timer = QTimer(self)
        self._volume_save_timer.setSingleShot(True)
        self._volume_save_timer.setInterval(600)
        self._volume_save_timer.timeout.connect(self._save_remembered_volume)

        self._demo_timer = QTimer(self)
        self._demo_timer.setInterval(1000)
        self._demo_timer.timeout.connect(self._advance_demo_playback)
        self._demo_track_number = 0
        self._demo_position = 0
        self._shuffle = False
        self._repeat = False

        self._connect_signals()
        self.state.subscribe(self.window.set_state)
        self.window.set_preferences(self.preferences)
        self._restore_geometry()

    def start(self) -> None:
        self._refresh_collection()
        self.window.show()
        threading.Thread(
            target=self._probe_dependencies,
            daemon=True,
            name="cdflow-capability-probe",
        ).start()
        if self._library_warning:
            self.window.show_message(self._library_warning, level="warning", timeout_ms=0)
        if self.demo_mode:
            self._start_demo(self.demo_mode)
        else:
            self.monitor.start()

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        self._demo_timer.stop()
        self._rip_timer.stop()
        self._volume_save_timer.stop()
        if self.preferences.remember_volume:
            try:
                self.settings.save()
            except OSError:
                LOGGER.exception("Could not save remembered volume during shutdown")
        self.ripper.cancel()
        self.reader.cancel()
        self.metadata.cancel()
        self.artwork.cancel()
        self._active_metadata_request = None
        self._active_artwork_request = None
        self.player.shutdown()
        self.monitor.stop(wait=True)
        ripper_stopped = self.ripper.wait(5.0)
        self.reader.shutdown(wait=True)
        self.metadata.shutdown(wait=True)
        self.artwork.shutdown(wait=True)
        if ripper_stopped:
            try:
                self.library.close()
            except sqlite3.Error:
                LOGGER.exception("Could not close the local collection cleanly")
        else:
            # The worker retains the repository reference. Leaving it open is
            # safer than closing SQLite beneath a final filesystem operation;
            # process teardown will reclaim it.
            LOGGER.warning("Ripping worker did not stop within five seconds during shutdown")

    def _connect_signals(self) -> None:
        self.app.aboutToQuit.connect(self.shutdown)
        self.dependency_report_ready.connect(self._on_dependency_report)

        self.monitor.drives_changed.connect(self._on_drives_changed)
        self.monitor.media_inserted.connect(self._on_media_inserted)
        self.monitor.media_removed.connect(self._on_media_removed)
        self.monitor.error_occurred.connect(self._on_monitor_error)
        self.monitor.operation_finished.connect(self._on_drive_operation_finished)

        self.reader.inspection_ready.connect(self._on_inspection_ready)
        self.reader.inspection_failed.connect(self._on_inspection_failed)
        self.metadata.lookup_ready.connect(self._on_metadata_ready)
        self.metadata.lookup_failed.connect(self._on_metadata_failed)
        self.metadata.lookup_cancelled.connect(self._on_metadata_cancelled)
        self.artwork.artwork_ready.connect(self._on_artwork_ready)
        self.artwork.artwork_not_found.connect(self._on_artwork_not_found)
        self.artwork.artwork_failed.connect(self._on_artwork_failed)
        self.artwork.artwork_cancelled.connect(self._on_artwork_cancelled)

        self.player.state_changed.connect(self._on_playback_state)
        self.player.track_changed.connect(self._on_playback_track)
        self.player.position_changed.connect(self._on_playback_position)
        self.player.seekability_changed.connect(lambda seekable: self.window.set_playback_state(seekable=seekable))
        self.player.volume_changed.connect(
            lambda value: self.window.set_playback_state(volume=round(float(value) * 100))
        )
        self.player.muted_changed.connect(lambda muted: self.window.set_playback_state(muted=muted))
        self.player.track_finished.connect(self._on_track_finished)
        self.player.error_occurred.connect(
            lambda message: self.window.show_message(message, level="error", timeout_ms=8000)
        )

        self.ripper.track_started.connect(self._on_rip_track_started)
        self.ripper.track_progress.connect(self._on_rip_track_progress)
        self.ripper.overall_progress.connect(self._on_rip_overall_progress)
        self.ripper.warning_occurred.connect(
            lambda message: self.window.show_message(message, level="warning", timeout_ms=8000)
        )
        self.ripper.completed.connect(self._on_rip_completed)
        self.ripper.cancelled.connect(self._on_rip_cancelled)
        self.ripper.failed.connect(self._on_rip_failed)

        self.window.drive_selected.connect(self._select_drive)
        self.window.eject_requested.connect(self._eject)
        self.window.retry_requested.connect(self._retry)
        self.window.play_requested.connect(self._play)
        self.window.pause_requested.connect(self._pause)
        self.window.stop_requested.connect(self._stop)
        self.window.previous_requested.connect(self._previous)
        self.window.next_requested.connect(self._next)
        self.window.track_activated.connect(self._play_track)
        self.window.seek_requested.connect(self._seek)
        self.window.volume_changed.connect(self._set_volume)
        self.window.mute_toggled.connect(self._set_muted)
        self.window.shuffle_toggled.connect(self._set_shuffle)
        self.window.repeat_toggled.connect(self._set_repeat)
        self.window.rip_requested.connect(self._start_rip)
        self.window.cancel_rip_requested.connect(self.ripper.cancel)
        self.window.rip_track_requested.connect(self._prepare_single_track_rip)
        self.window.track_info_requested.connect(self._show_track_info)
        self.window.rip_destination_requested.connect(self._choose_rip_destination)
        self.window.settings_destination_requested.connect(self._choose_settings_destination)
        self.window.open_path_requested.connect(self._open_data_path)
        self.window.metadata_refresh_requested.connect(lambda: self._start_metadata(force=True, manual=True))
        self.window.collection_album_selected.connect(self._show_cached_album)
        self.window.settings_changed.connect(self._update_settings)
        self.window.window_geometry_changed.connect(self._save_geometry)

    def _probe_dependencies(self) -> None:
        try:
            report = DependencyDetector.detect()
            self.dependency_report_ready.emit(report)
        except Exception:
            LOGGER.exception("Could not complete the runtime capability check")

    @Slot(object)
    def _on_dependency_report(self, report: DependencyReport) -> None:
        if self._shutting_down:
            return
        self.dependency_report = report
        for dependency in report.dependencies:
            LOGGER.debug(
                "Runtime dependency %s: %s (%s)",
                dependency.name,
                "available" if dependency.available else "missing",
                "required" if dependency.required else "optional",
            )
        if report.missing_required:
            names = ", ".join(item.name for item in report.missing_required)
            self.window.show_message(
                f"Required runtime support is missing: {names}. Run cdflow --diagnose for details.",
                level="error",
                timeout_ms=0,
            )

    @Slot(object)
    def _on_drives_changed(self, drives: object) -> None:
        if self._shutting_down:
            return
        previous_disc = self.state.snapshot.disc
        drive_list = list(drives) if isinstance(drives, (list, tuple)) else []
        self.state.set_drives(drive_list)
        if not drive_list:
            self._active_inspection = None
            self._clear_media_services()
            self.state.transition(AppStatus.NO_DRIVE, message="No optical drive found")
            return
        selected = self._selected_drive()
        if selected is None:
            return
        previous_drive = (
            next(
                (item for item in drive_list if item.object_path == previous_disc.drive.object_path),
                None,
            )
            if previous_disc
            else None
        )
        previous_disc_is_valid = bool(previous_drive and previous_drive.media_available)
        if previous_disc and not previous_disc_is_valid:
            self._active_inspection = None
            self._clear_media_services(previous_disc.drive)
            previous_disc = None
        is_current_disc = bool(
            previous_disc and previous_disc.drive.object_path == selected.object_path and previous_disc_is_valid
        )
        status = self.state.snapshot.status
        waiting_for_selected_eject = status == AppStatus.EJECTING and selected.object_path == self._pending_eject_path
        if not selected.media_available and not waiting_for_selected_eject:
            if status != AppStatus.EMPTY_DRIVE or self.state.snapshot.disc is not None:
                self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")
            return
        if selected.media_available and not is_current_disc and status != AppStatus.LOADING_DISC:
            if waiting_for_selected_eject:
                return
            if self.preferences.auto_load_disc:
                self._load_drive(selected)
            else:
                self.state.transition(
                    AppStatus.EMPTY_DRIVE,
                    message="Disc detected. Use Try Again to read it.",
                )

    @Slot(object)
    def _on_media_inserted(self, drive: Drive) -> None:
        if self._shutting_down:
            return
        self._mount_attempted = False
        if drive.object_path == self._pending_eject_path:
            self._pending_eject_path = ""
            self._disc_before_eject = None
        snapshot = self.state.snapshot
        keep_current = bool(
            snapshot.selected_drive_path
            and snapshot.selected_drive_path != drive.object_path
            and snapshot.status
            in {
                AppStatus.LOADING_DISC,
                AppStatus.AUDIO_CD,
                AppStatus.DATA_CD,
                AppStatus.RIPPING,
                AppStatus.EJECTING,
            }
        )
        selected_path = snapshot.selected_drive_path if keep_current else drive.object_path
        self.state.set_drives(list(self.monitor.drives), selected_path=selected_path)
        if keep_current:
            self.window.show_message(f"Disc detected in {drive.display_name}.", timeout_ms=5000)
            return
        if self.preferences.auto_load_disc:
            self._load_drive(drive)
        else:
            self.state.transition(
                AppStatus.EMPTY_DRIVE,
                message="Disc detected. Use Try Again to read it.",
            )

    @Slot(object)
    def _on_media_removed(self, drive: Drive) -> None:
        if self._shutting_down:
            return
        current_disc = self.state.snapshot.disc
        relevant_paths = {
            self.state.snapshot.selected_drive_path,
            self._pending_eject_path,
            current_disc.drive.object_path if current_disc else "",
        }
        if drive.object_path not in relevant_paths:
            return
        self._mount_attempted = False
        self._active_inspection = None
        self._clear_media_services(drive)
        if drive.object_path == self._pending_eject_path:
            self._pending_eject_path = ""
            self._disc_before_eject = None
        if drive.object_path == self.state.snapshot.selected_drive_path:
            self.state.transition(AppStatus.EMPTY_DRIVE, message="Disc removed")

    @Slot(str)
    def _select_drive(self, object_path: str) -> None:
        try:
            self.state.select_drive(object_path)
        except ValueError:
            return
        drive = self._selected_drive()
        if drive is None:
            return
        if drive.media_available:
            self._load_drive(drive)
        else:
            self._clear_media_services()
            self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")

    def _load_drive(self, drive: Drive) -> None:
        if not drive.media_available:
            self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")
            return
        self.reader.cancel()
        self.metadata.cancel()
        self.artwork.cancel()
        self._active_metadata_request = None
        self._active_artwork_request = None
        self.player.clear_disc()
        if self.ripper.is_running:
            self.ripper.cancel()
        self._active_inspection = None
        status = self.state.snapshot.status
        if status == AppStatus.RIPPING:
            fallback = AppStatus.AUDIO_CD if self.state.snapshot.disc else AppStatus.EMPTY_DRIVE
            self.state.transition(
                fallback,
                message="Cancelling the current rip…",
                disc=self.state.snapshot.disc,
            )
        elif status == AppStatus.EJECTING:
            self._pending_eject_path = ""
            self._disc_before_eject = None
            self.state.transition(AppStatus.EMPTY_DRIVE, message="A disc was detected")
        snapshot = self.state.transition(
            AppStatus.LOADING_DISC,
            message=f"Reading {drive.display_name}…",
        )
        self.reader.inspect_async(drive, generation=snapshot.generation)

    @Slot(object, int)
    def _on_inspection_ready(self, inspection: DiscInspection, generation: int) -> None:
        if self._shutting_down or not self.state.accepts(generation):
            return
        self._active_inspection = inspection
        disc = inspection.disc
        if disc.kind == DiscKind.NONE:
            self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")
            return
        if disc.kind in {DiscKind.AUDIO, DiscKind.MIXED} and disc.album:
            status = AppStatus.AUDIO_CD
            message = "Audio CD ready" if disc.kind == DiscKind.AUDIO else "Mixed-mode CD ready"
            self.state.transition(status, message=message, disc=disc)
            try:
                self.player.set_disc(disc.drive.device, disc.album.tracks)
            except ValueError as error:
                self.state.transition(AppStatus.ERROR, message=str(error), disc=disc)
                self.window.show_message(str(error), level="error", timeout_ms=9000)
                return
            self.player.set_volume(self.preferences.default_volume / 100)
            if disc.warnings:
                self.window.show_message(disc.warnings[0], level="warning", timeout_ms=8000)
            self._refresh_collection()
            if self.preferences.metadata_enabled and self.preferences.auto_metadata:
                self._start_metadata()
            if disc.kind == DiscKind.MIXED:
                self._prepare_data_access(disc)
            return
        if disc.kind == DiscKind.DATA:
            self.state.transition(AppStatus.DATA_CD, message="Data CD ready", disc=disc)
            self._prepare_data_access(disc)
            return
        if disc.kind in {DiscKind.AUDIO, DiscKind.MIXED}:
            message = disc.warnings[0] if disc.warnings else "The audio CD table of contents could not be read."
            self.state.transition(AppStatus.ERROR, message=message, disc=disc)
            self.window.show_message(message, level="error", timeout_ms=9000)
            return
        self.state.transition(
            AppStatus.ERROR,
            message="This optical disc type is not supported.",
            disc=disc,
        )

    @Slot(str, int)
    def _on_inspection_failed(self, message: str, generation: int) -> None:
        if not self._shutting_down and self.state.accepts(generation):
            self.state.transition(AppStatus.ERROR, message=message)
            self.window.show_message(message, level="error", timeout_ms=9000)

    @Slot(str)
    def _on_monitor_error(self, message: str) -> None:
        if self._shutting_down:
            return
        LOGGER.warning("Drive monitor: %s", message)
        self.window.show_message(message, level="warning", timeout_ms=9000)
        if not self.state.snapshot.drives:
            self.state.transition(AppStatus.NO_DRIVE, message="Optical-drive monitoring is unavailable")

    @Slot(str, str, bool, str)
    def _on_drive_operation_finished(
        self,
        operation: str,
        object_path: str,
        success: bool,
        message: str,
    ) -> None:
        if self._shutting_down:
            return
        disc = self.state.snapshot.disc
        if operation == "mount":
            if disc is None or object_path not in {disc.drive.object_path, disc.drive.block_path}:
                return
            if not success:
                self._mount_attempted = False
        elif operation == "eject" and object_path != self._pending_eject_path:
            return
        if not success:
            self.window.show_message(message, level="error", timeout_ms=9000)
            if operation == "eject" and self.state.snapshot.status == AppStatus.EJECTING:
                self.state.transition(
                    AppStatus.ERROR, message=f"Could not eject the disc: {message}", disc=self._disc_before_eject
                )
                self._pending_eject_path = ""
                self._disc_before_eject = None
            return
        if operation == "mount" and disc and message.startswith("/"):
            mounted_disc = replace(disc, mount_points=(message,))
            self._replace_active_disc(mounted_disc, message="Data CD mounted read-only")
            self.window.set_browse_root(message)
        elif operation == "eject":
            self.window.show_message("Disc ejected")

    def _start_metadata(self, *, force: bool = False, manual: bool = False) -> None:
        inspection = self._active_inspection
        if not inspection or not inspection.toc or not inspection.disc.album or not inspection.disc.disc_id:
            if manual:
                self.window.show_message("Metadata lookup is available for a loaded audio CD.", level="warning")
            return
        if not self.preferences.metadata_enabled:
            if manual:
                self.window.show_message("Enable metadata lookup in Settings first.", level="warning")
            return
        if not self.preferences.musicbrainz_contact:
            if manual:
                self.window.show_message(
                    "Add a contact email or URL in Settings before using MusicBrainz.",
                    level="warning",
                )
            return
        active_request = self._active_metadata_request
        if active_request is not None and active_request[1] == inspection.disc.disc_id:
            LOGGER.debug("Coalesced duplicate metadata start for disc %s", inspection.disc.disc_id)
            if manual:
                self.window.show_message("Metadata lookup is already in progress.", timeout_ms=3000)
            return
        generation = self._next_request_generation()
        self._active_metadata_request = (generation, inspection.disc.disc_id, manual)
        if manual:
            self.window.show_message("Looking up MusicBrainz metadata…", timeout_ms=3000)
        self.metadata.lookup_async(
            inspection.disc.disc_id,
            inspection.toc,
            inspection.disc.album,
            generation=generation,
            force=force,
        )

    @Slot(object, int)
    def _on_metadata_ready(self, lookup: MetadataLookup, generation: int) -> None:
        request = self._active_metadata_request
        if self._shutting_down or request is None or request[0] != generation or request[1] != lookup.disc_id:
            return
        self._active_metadata_request = None
        manual = request[2]
        disc = self.state.snapshot.disc
        if disc is None or disc.disc_id != lookup.disc_id:
            return
        candidate = lookup.selected
        if candidate is None:
            if manual:
                message = (
                    "Multiple plausible releases were found; cached generic track names were kept."
                    if lookup.candidates
                    else "No MusicBrainz release matched this disc."
                )
                self.window.show_message(message, level="warning", timeout_ms=8000)
            return
        updated = replace(disc, album=candidate.album)
        self._replace_active_disc(updated, message="Metadata loaded")
        self._refresh_collection()
        if self.preferences.artwork_enabled and candidate.release_id:
            artwork_generation = self._next_request_generation()
            self._active_artwork_request = (
                artwork_generation,
                updated.disc_id,
                candidate.release_id,
            )
            self.artwork.fetch_async(candidate.release_id, generation=artwork_generation)

    @Slot(str, int)
    def _on_metadata_failed(self, message: str, generation: int) -> None:
        request = self._active_metadata_request
        if self._shutting_down or request is None or request[0] != generation:
            return
        self._active_metadata_request = None
        LOGGER.info("Optional metadata lookup failed: %s", message)
        if message == "Metadata service is temporarily unavailable.":
            self.window.show_message(message, level="warning", timeout_ms=6000)
        elif request[2]:
            self.window.show_message(message, level="warning", timeout_ms=8000)

    @Slot(int)
    def _on_metadata_cancelled(self, generation: int) -> None:
        request = self._active_metadata_request
        if request is not None and request[0] == generation:
            self._active_metadata_request = None

    @Slot(object, int)
    def _on_artwork_ready(self, result: ArtworkResult, generation: int) -> None:
        request = self._active_artwork_request
        if (
            self._shutting_down
            or request is None
            or request[0] != generation
            or request[2].casefold() != result.release_id.casefold()
            or result.path is None
        ):
            return
        self._active_artwork_request = None
        disc = self.state.snapshot.disc
        if disc is None or disc.album is None or disc.disc_id != request[1]:
            return
        album = replace(disc.album, artwork_path=str(result.path))
        updated = replace(disc, album=album)
        try:
            if not self.library.set_artwork(album.disc_id, result.path):
                self.library.upsert_album(album)
        except (OSError, RuntimeError, sqlite3.Error):
            LOGGER.exception("Could not cache downloaded album artwork")
        self._replace_active_disc(updated, message="Album artwork loaded")
        self._refresh_collection()

    @Slot(str, int)
    def _on_artwork_not_found(self, release_id: str, generation: int) -> None:
        request = self._active_artwork_request
        if request is not None and request[0] == generation and request[2].casefold() == release_id.casefold():
            self._active_artwork_request = None

    @Slot(str, int)
    def _on_artwork_failed(self, message: str, generation: int) -> None:
        request = self._active_artwork_request
        if self._shutting_down or request is None or request[0] != generation:
            return
        self._active_artwork_request = None
        LOGGER.info("Optional artwork lookup failed: %s", message)

    @Slot(int)
    def _on_artwork_cancelled(self, generation: int) -> None:
        request = self._active_artwork_request
        if request is not None and request[0] == generation:
            self._active_artwork_request = None

    def _replace_active_disc(self, disc: Disc, *, message: str) -> None:
        if self._active_inspection:
            self._active_inspection = replace(self._active_inspection, disc=disc)
        status = self.state.snapshot.status
        self.state.transition(status, message=message, disc=disc)

    def _prepare_data_access(self, disc: Disc) -> None:
        if disc.primary_mount_point:
            self.window.set_browse_root(disc.primary_mount_point)
        elif not self.demo_mode and not self._mount_attempted:
            self._mount_attempted = True
            self.window.show_message("Mounting the data CD read-only…", timeout_ms=3000)
            self.monitor.mount(disc.drive.object_path, read_only=True)

    def _next_request_generation(self) -> int:
        self._request_generation += 1
        return self._request_generation

    @Slot()
    def _eject(self) -> None:
        if self.state.snapshot.status == AppStatus.EJECTING:
            return
        drive = self._selected_drive()
        if drive is None:
            self.window.show_message("No optical drive is selected.", level="warning")
            return
        self._disc_before_eject = self.state.snapshot.disc
        self._pending_eject_path = drive.object_path
        self._clear_media_services(drive)
        status = self.state.snapshot.status
        if status == AppStatus.RIPPING:
            fallback = AppStatus.AUDIO_CD if self.state.snapshot.disc else AppStatus.EMPTY_DRIVE
            self.state.transition(
                fallback,
                message="Cancelling the current rip…",
                disc=self.state.snapshot.disc,
            )
        elif status in {AppStatus.LOADING_DISC, AppStatus.NO_DRIVE}:
            self.state.transition(AppStatus.EMPTY_DRIVE, message="Preparing to eject…")
        self.state.transition(AppStatus.EJECTING, message="Ejecting disc…")
        if self.demo_mode:
            empty_drive = replace(drive, media_available=False, audio_tracks=0, data_tracks=0)
            self.state.set_drives([empty_drive], selected_path=empty_drive.object_path)
            self._pending_eject_path = ""
            self._disc_before_eject = None
            self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")
        else:
            self.monitor.eject(drive.object_path)

    @Slot()
    def _retry(self) -> None:
        self._mount_attempted = False
        drive = self._selected_drive()
        if drive and drive.media_available:
            self._load_drive(drive)
        elif drive:
            self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")
        else:
            self.state.transition(AppStatus.NO_DRIVE, message="No optical drive found")

    def _clear_media_services(self, drive: Drive | None = None) -> None:
        self._active_inspection = None
        self.reader.cancel()
        self.metadata.cancel()
        self.artwork.cancel()
        self._active_metadata_request = None
        self._active_artwork_request = None
        if drive:
            self.player.on_media_removed(drive)
            self.ripper.on_media_removed(drive)
        else:
            self.player.clear_disc()
            self.ripper.cancel()
        self._demo_timer.stop()
        self._rip_timer.stop()
        self.window.set_playback_state(
            track=None,
            track_number=0,
            playing=False,
            position_seconds=0,
            duration_seconds=0,
            seekable=False,
        )

    def _selected_drive(self) -> Drive | None:
        selected = self.state.snapshot.selected_drive_path
        return next((drive for drive in self.state.snapshot.drives if drive.object_path == selected), None)

    @Slot()
    def _play(self) -> None:
        if self._playback_blocked_by_rip():
            return
        if self.demo_mode:
            self._demo_play()
        else:
            self.player.play()

    @Slot()
    def _pause(self) -> None:
        if self.demo_mode:
            self._demo_timer.stop()
            self.window.set_playback_state(playing=False)
        else:
            self.player.pause()

    @Slot()
    def _stop(self) -> None:
        if self.demo_mode:
            self._demo_timer.stop()
            self._demo_position = 0
            self.window.set_playback_state(playing=False, position_seconds=0)
        else:
            self.player.stop()

    @Slot()
    def _previous(self) -> None:
        if self._playback_blocked_by_rip():
            return
        if self.demo_mode:
            self._demo_step(-1)
        else:
            self.player.previous_track()

    @Slot()
    def _next(self) -> None:
        if self._playback_blocked_by_rip():
            return
        if self.demo_mode:
            self._demo_step(1)
        elif self._shuffle:
            self._play_random_track()
        else:
            self.player.next_track()

    @Slot(int)
    def _play_track(self, track_number: int) -> None:
        if self._playback_blocked_by_rip():
            return
        if self.demo_mode:
            self._demo_track_number = track_number
            self._demo_position = 0
            self._demo_play()
        else:
            self.player.play_track(track_number)

    @Slot(int)
    def _seek(self, seconds: int) -> None:
        if self.demo_mode:
            self._demo_position = max(0, int(seconds))
            self.window.set_playback_state(position_seconds=self._demo_position)
        else:
            self.player.seek(int(seconds) * 1000)

    @Slot(int)
    def _set_volume(self, value: int) -> None:
        volume = max(0, min(100, int(value)))
        if not self.demo_mode:
            self.player.set_volume(volume / 100)
        self.window.set_playback_state(volume=volume)
        self.preferences.default_volume = volume
        if self.preferences.remember_volume:
            self._volume_save_timer.start()

    @Slot(bool)
    def _set_muted(self, muted: bool) -> None:
        if not self.demo_mode:
            self.player.set_muted(muted)
        self.window.set_playback_state(muted=muted)

    @Slot(bool)
    def _set_shuffle(self, enabled: bool) -> None:
        self._shuffle = bool(enabled)
        self.player.auto_advance = not (self._shuffle or self._repeat)
        self.window.set_playback_state(shuffle=self._shuffle)

    @Slot(bool)
    def _set_repeat(self, enabled: bool) -> None:
        self._repeat = bool(enabled)
        self.player.auto_advance = not (self._shuffle or self._repeat)
        self.window.set_playback_state(repeat=self._repeat)

    @Slot(str)
    def _on_playback_state(self, state: str) -> None:
        self.window.set_playback_state(playing=state == PlaybackState.PLAYING.value)

    @Slot(int)
    def _on_playback_track(self, track_number: int) -> None:
        self.window.set_playback_state(track_number=track_number, position_seconds=0)

    @Slot(int, int)
    def _on_playback_position(self, position_ms: int, duration_ms: int) -> None:
        self.window.set_playback_state(
            position_seconds=position_ms / 1000,
            duration_seconds=duration_ms / 1000,
        )

    @Slot(int)
    def _on_track_finished(self, track_number: int) -> None:
        if self._repeat:
            QTimer.singleShot(0, lambda: self.player.play_track(track_number))
        elif self._shuffle:
            QTimer.singleShot(0, self._play_random_track)

    def _playback_blocked_by_rip(self) -> bool:
        if self.state.snapshot.status != AppStatus.RIPPING and not self.ripper.is_running:
            return False
        self.window.show_message(
            "Playback is unavailable while the optical drive is ripping.",
            level="warning",
            timeout_ms=5000,
        )
        return True

    def _play_random_track(self) -> None:
        disc = self.state.snapshot.disc
        tracks = disc.album.tracks if disc and disc.album else []
        candidates = [track.number for track in tracks if track.number != self.player.current_track]
        if candidates:
            self.player.play_track(random.choice(candidates))  # noqa: S311 - entertainment shuffle

    def _start_demo(self, mode: str) -> None:
        if mode == "data":
            disc = demo_data_disc()
            self.state.set_drives([disc.drive], selected_path=disc.drive.object_path)
            self._active_inspection = DiscInspection(disc)
            self.state.transition(AppStatus.LOADING_DISC, message="Reading demo disc…")
            self.state.transition(AppStatus.DATA_CD, message="Data CD ready", disc=disc)
            return
        disc = demo_audio_disc()
        if mode == "empty":
            drive = replace(disc.drive, media_available=False, audio_tracks=0)
            self.state.set_drives([drive], selected_path=drive.object_path)
            self.state.transition(AppStatus.EMPTY_DRIVE, message="No disc inserted")
            return
        self.state.set_drives([disc.drive], selected_path=disc.drive.object_path)
        self._active_inspection = DiscInspection(disc)
        self.state.transition(AppStatus.LOADING_DISC, message="Reading demo disc…")
        self.state.transition(AppStatus.AUDIO_CD, message="Audio CD ready", disc=disc)
        self._demo_track_number = disc.album.tracks[0].number if disc.album else 0
        self.window.set_playback_state(
            track_number=self._demo_track_number,
            volume=self.preferences.default_volume,
            seekable=True,
        )

    def _demo_play(self) -> None:
        album = self.state.snapshot.disc.album if self.state.snapshot.disc else None
        if not album or not album.tracks:
            return
        if not any(track.number == self._demo_track_number for track in album.tracks):
            self._demo_track_number = album.tracks[0].number
        track = next(track for track in album.tracks if track.number == self._demo_track_number)
        self.window.set_playback_state(
            track=track,
            track_number=track.number,
            playing=True,
            position_seconds=self._demo_position,
            duration_seconds=track.duration_seconds,
        )
        self._demo_timer.start()

    def _advance_demo_playback(self) -> None:
        album = self.state.snapshot.disc.album if self.state.snapshot.disc else None
        if not album:
            return
        track = next((item for item in album.tracks if item.number == self._demo_track_number), None)
        if not track:
            return
        self._demo_position += 1
        if self._demo_position >= track.duration_seconds:
            if self._repeat:
                self._demo_position = 0
            else:
                self._demo_step(1)
                return
        self.window.set_playback_state(position_seconds=self._demo_position)

    def _demo_step(self, direction: int) -> None:
        disc = self.state.snapshot.disc
        tracks = disc.album.tracks if disc and disc.album else []
        if not tracks:
            return
        numbers = [track.number for track in tracks]
        if self._shuffle and len(numbers) > 1:
            next_number = random.choice([number for number in numbers if number != self._demo_track_number])
        else:
            try:
                current = numbers.index(self._demo_track_number)
            except ValueError:
                current = 0
            next_number = numbers[(current + direction) % len(numbers)]
        self._demo_track_number = next_number
        self._demo_position = 0
        self._demo_play()

    @Slot(dict)
    def _start_rip(self, configuration: dict[str, Any]) -> None:
        disc = self.state.snapshot.disc
        if (
            self.state.snapshot.status != AppStatus.AUDIO_CD
            or not disc
            or not disc.album
            or disc.kind not in {DiscKind.AUDIO, DiscKind.MIXED}
        ):
            self.window.show_message("Insert an audio CD before ripping.", level="warning")
            return
        if self.demo_mode:
            self.window.show_message("Ripping is disabled in demo mode.", level="warning")
            return
        if self._active_rip_job is not None or self.ripper.is_running:
            self.window.show_message("A ripping job is already finishing.", level="warning")
            return
        try:
            selected_numbers = {int(value) for value in configuration.get("tracks", [])}
            tracks = tuple(
                replace(track, selected_for_ripping=track.number in selected_numbers) for track in disc.album.tracks
            )
            options = RipOptions(
                output_directory=Path(str(configuration.get("destination") or self.preferences.output_directory)),
                format=RipFormat(str(configuration.get("format") or self.preferences.rip_format).lower()),
                quality=str(configuration.get("quality") or self.preferences.rip_quality),
                filename_pattern=str(configuration.get("filename_pattern") or self.preferences.filename_pattern),
                organize_by_album=bool(configuration.get("organize_folders", True)),
                embed_metadata=bool(configuration.get("embed_metadata", self.preferences.embed_metadata)),
                embed_artwork=bool(configuration.get("embed_artwork", self.preferences.embed_artwork)),
                artwork_path=Path(disc.album.artwork_path) if disc.album.artwork_path else None,
            )
            job = RipJob(device=disc.drive.device, album=disc.album, tracks=tracks, options=options)
            if not job.selected_tracks:
                raise ValueError("select at least one track to rip")
            self.player.stop()
            self._active_rip_job = job
            self.ripper.start(job)
        except (OSError, RuntimeError, TypeError, ValueError) as error:
            self._active_rip_job = None
            self.window.show_message(str(error), level="error", timeout_ms=9000)
            return
        self._rip_started_at = time.monotonic()
        self._rip_view.update(
            current_track="Preparing extraction",
            track_progress=0.0,
            overall_progress=0.0,
            destination=str(options.output_directory),
            message="Preparing secure extraction…",
        )
        self.state.transition(AppStatus.RIPPING, message="Ripping selected tracks", disc=disc)
        self.window.show_page("rip_cd")
        self._refresh_rip_elapsed()
        self._rip_timer.start()

    @Slot(int, str)
    def _on_rip_track_started(self, track_number: int, destination: str) -> None:
        if self._shutting_down or self._active_rip_job is None or self.state.snapshot.status != AppStatus.RIPPING:
            return
        disc = self.state.snapshot.disc
        track = next(
            (item for item in (disc.album.tracks if disc and disc.album else []) if item.number == track_number),
            None,
        )
        self._rip_view.update(
            current_track=f"Track {track_number:02d} — {track.title if track else 'Audio track'}",
            track_progress=0.0,
            destination=str(Path(destination).parent),
            message="Reading audio with error correction…",
        )
        self._refresh_rip_elapsed()

    @Slot(int, int)
    def _on_rip_track_progress(self, track_number: int, percent: int) -> None:
        if self._shutting_down or self._active_rip_job is None or self.state.snapshot.status != AppStatus.RIPPING:
            return
        del track_number
        self._rip_view["track_progress"] = percent / 100
        self._refresh_rip_elapsed()

    @Slot(int)
    def _on_rip_overall_progress(self, percent: int) -> None:
        if self._shutting_down or self._active_rip_job is None or self.state.snapshot.status != AppStatus.RIPPING:
            return
        self._rip_view["overall_progress"] = percent / 100
        self._refresh_rip_elapsed()

    @Slot(object)
    def _on_rip_completed(self, result: RipResult) -> None:
        if self._shutting_down or result.job is not self._active_rip_job:
            return
        self._active_rip_job = None
        self._rip_timer.stop()
        count = len(result.paths)
        self.window.set_rip_progress(
            **(
                self._rip_view
                | {
                    "elapsed_seconds": result.elapsed_seconds,
                    "track_progress": 1.0,
                    "overall_progress": 1.0,
                    "message": f"{count} {'track' if count == 1 else 'tracks'} saved successfully.",
                    "active": False,
                    "completed": True,
                }
            )
        )
        self._finish_rip_state("Ripping complete")
        self._refresh_collection()

    @Slot(object)
    def _on_rip_cancelled(self, result: RipResult) -> None:
        if self._shutting_down or result.job is not self._active_rip_job:
            return
        self._active_rip_job = None
        self._rip_timer.stop()
        self.window.set_rip_progress(
            **(
                self._rip_view
                | {
                    "elapsed_seconds": result.elapsed_seconds,
                    "message": "Ripping was cancelled. Completed files were kept.",
                    "active": False,
                }
            )
        )
        self._finish_rip_state("Ripping cancelled")

    @Slot(str)
    def _on_rip_failed(self, message: str) -> None:
        if self._shutting_down or self._active_rip_job is None:
            return
        self._active_rip_job = None
        self._rip_timer.stop()
        self.window.set_rip_progress(
            **self._rip_view,
            elapsed_seconds=max(0.0, time.monotonic() - self._rip_started_at),
            active=False,
            error=message,
        )
        self.window.show_message(message, level="error", timeout_ms=9000)
        self._finish_rip_state("Ripping failed")

    def _refresh_rip_elapsed(self) -> None:
        if not self._rip_started_at:
            return
        self.window.set_rip_progress(
            **self._rip_view,
            elapsed_seconds=max(0.0, time.monotonic() - self._rip_started_at),
            active=True,
        )

    def _finish_rip_state(self, message: str) -> None:
        disc = self.state.snapshot.disc
        if self.state.snapshot.status == AppStatus.RIPPING and disc:
            try:
                cached = self.library.get_album(disc.disc_id) if disc.disc_id else None
            except (OSError, RuntimeError, sqlite3.Error):
                cached = None
            if cached is not None:
                disc = replace(disc, album=cached)
                if self._active_inspection:
                    self._active_inspection = replace(self._active_inspection, disc=disc)
            self.state.transition(AppStatus.AUDIO_CD, message=message, disc=disc)

    @Slot(int)
    def _prepare_single_track_rip(self, track_number: int) -> None:
        page = self.window.page_widget("rip_cd")
        track_table = getattr(page, "track_table", None)
        if track_table is not None:
            track_table.set_all_checked(False)
            for row, track in enumerate(track_table.track_model.tracks):
                if track.number == track_number:
                    index = track_table.track_model.index(row, 0)
                    from PySide6.QtCore import Qt

                    track_table.track_model.setData(
                        index,
                        Qt.CheckState.Checked,
                        Qt.ItemDataRole.CheckStateRole,
                    )
                    break
        self.window.show_page("rip_cd")

    @Slot(int)
    def _show_track_info(self, track_number: int) -> None:
        disc = self.state.snapshot.disc
        track = next(
            (item for item in (disc.album.tracks if disc and disc.album else []) if item.number == track_number),
            None,
        )
        if track:
            self.window.show_message(
                f"Track {track.number:02d}: {track.title} — {track.artist} — {track.duration_text}",
                timeout_ms=8000,
            )

    @Slot(str)
    def _choose_rip_destination(self, initial: str) -> None:
        selected = QFileDialog.getExistingDirectory(self.window, "Choose Rip Destination", initial)
        if selected:
            self.window.set_rip_destination(selected)

    @Slot(str)
    def _choose_settings_destination(self, initial: str) -> None:
        selected = QFileDialog.getExistingDirectory(self.window, "Choose Default Rip Destination", initial)
        if selected:
            self.window.set_settings_destination(selected)

    @Slot(str)
    def _open_data_path(self, raw_path: str) -> None:
        disc = self.state.snapshot.disc
        if not disc or not disc.primary_mount_point:
            return
        try:
            root = Path(disc.primary_mount_point).resolve(strict=True)
            target = Path(raw_path).resolve(strict=True)
            target.relative_to(root)
        except (OSError, ValueError):
            self.window.show_message("That path is outside the mounted data CD.", level="error")
            return
        if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(target))):
            self.window.show_message("No desktop application could open that file.", level="error")

    @Slot(str)
    def _show_cached_album(self, disc_id: str) -> None:
        try:
            album = self.library.get_album(disc_id)
        except (OSError, RuntimeError, sqlite3.Error) as error:
            LOGGER.exception("Could not read a cached album")
            self.window.show_message(f"Could not open the cached album: {error}", level="error")
            return
        if album is None:
            self.window.show_message("That cached album is no longer available.", level="warning")
            return
        page = self.window.page_widget("disc_info")
        setter = getattr(page, "set_cached_album", None)
        if callable(setter):
            setter(album)
            self.window.show_page("disc_info")
        else:
            self.window.show_message(
                f"{album.title} — {album.artist} — {len(album.tracks)} tracks — {album.total_duration_text}",
                timeout_ms=9000,
            )

    @Slot(dict)
    def _update_settings(self, changes: dict[str, Any]) -> None:
        try:
            self.preferences = self.settings.update(**changes)
        except (KeyError, OSError, TypeError, ValueError) as error:
            self.window.show_message(f"Could not save settings: {error}", level="error")
            return
        self.window.set_preferences(self.preferences)
        self.metadata.set_contact(self.preferences.musicbrainz_contact)
        self.artwork.set_contact(self.preferences.musicbrainz_contact)
        if not self.preferences.metadata_enabled:
            self.metadata.cancel()
            self._active_metadata_request = None
        if not self.preferences.artwork_enabled or not self.preferences.metadata_enabled:
            self.artwork.cancel()
            self._active_artwork_request = None
        self.player.set_volume(self.preferences.default_volume / 100)

    def _save_remembered_volume(self) -> None:
        if not self.preferences.remember_volume:
            return
        try:
            self.settings.save()
        except OSError as error:
            self.window.show_message(f"Could not save volume: {error}", level="error")

    @Slot(bytes)
    def _save_geometry(self, geometry: bytes) -> None:
        if not self.preferences.remember_window_geometry:
            return
        try:
            self.settings.update(window_geometry=base64.b64encode(geometry).decode("ascii"))
        except OSError as error:
            LOGGER.warning("Could not save window geometry: %s", error)

    def _restore_geometry(self) -> None:
        encoded = self.preferences.window_geometry
        if not self.preferences.remember_window_geometry or not encoded:
            return
        try:
            geometry = base64.b64decode(encoded, validate=True)
        except (ValueError, base64.binascii.Error):
            LOGGER.warning("Ignoring invalid saved window geometry")
            return
        self.window.restore_geometry_data(geometry)

    def _refresh_collection(self) -> None:
        try:
            self.window.set_collection(self.library.list_albums())
        except (OSError, RuntimeError, sqlite3.Error):
            LOGGER.exception("Could not refresh the local collection")


def run_application(*, demo_mode: str | None = None, debug: bool = False) -> int:
    """Create and run the Qt application; called by :mod:`cdflow.cli`."""

    del debug  # Logging was configured before Qt imports.
    app = QApplication.instance() or QApplication([APP_NAME])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setOrganizationName(ORGANIZATION_NAME)
    app.setDesktopFileName(APP_ID)
    app.setQuitOnLastWindowClosed(True)

    settings = SettingsStore()
    preferences = settings.load()
    apply_theme(app, preferences.accent)
    icon_path = Path(__file__).resolve().parents[1] / "assets" / f"{APP_ID}.svg"
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    window = MainWindow()
    controller = ApplicationController(
        app,
        window,
        settings,
        preferences,
        demo_mode=demo_mode,
    )
    # QObject parenting owns the controller, but a Python reference prevents
    # wrapper collection before the event loop has started.
    app.setProperty("cdflowController", controller)
    controller.start()
    return app.exec()


__all__ = ["ApplicationController", "run_application"]
