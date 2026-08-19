"""Native top-level window and controller-facing UI facade for CDFlow."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from PySide6.QtCore import QByteArray, Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QResizeEvent, QShortcut
from PySide6.QtWidgets import QApplication, QHBoxLayout, QMainWindow, QStackedWidget, QVBoxLayout, QWidget

from cdflow.app.constants import APP_NAME, DEFAULT_ACCENT
from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.album import Album
from cdflow.models.track import Track

from .pages import (
    BrowseFilesPage,
    CollectionPage,
    DiscInfoPage,
    NowPlayingPage,
    RipCDPage,
    SettingsPage,
    TracksPage,
)
from .pages.base import StatefulPage
from .theme import apply_theme
from .widgets import InlineNotice, PlayerBar, Sidebar

PAGE_IDS = (
    "now_playing",
    "tracks",
    "rip_cd",
    "browse_files",
    "disc_info",
    "collection",
    "settings",
)


class MainWindow(QMainWindow):
    """Polished view layer with stable, domain-oriented signals and update methods.

    The window never invokes hardware or service code.  A controller connects to
    these signals and feeds results back through :meth:`set_state` and the other
    ``set_*`` methods.
    """

    page_requested = Signal(str)
    page_changed = Signal(str)
    drive_selected = Signal(str)
    eject_requested = Signal()
    retry_requested = Signal()

    play_requested = Signal()
    pause_requested = Signal()
    stop_requested = Signal()
    previous_requested = Signal()
    next_requested = Signal()
    track_activated = Signal(int)
    seek_requested = Signal(int)
    volume_changed = Signal(int)
    mute_toggled = Signal(bool)
    shuffle_toggled = Signal(bool)
    repeat_toggled = Signal(bool)

    rip_requested = Signal(dict)
    cancel_rip_requested = Signal()
    rip_track_requested = Signal(int)
    track_info_requested = Signal(int)
    rip_destination_requested = Signal(str)

    open_path_requested = Signal(str)
    metadata_refresh_requested = Signal()
    collection_album_selected = Signal(str)
    settings_changed = Signal(dict)
    settings_destination_requested = Signal(str)
    accent_changed = Signal(str)
    window_geometry_changed = Signal(bytes)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(APP_NAME)
        self.setMinimumSize(960, 620)
        self.resize(1280, 800)
        self.setAccessibleName(f"{APP_NAME} main window")
        app = QApplication.instance()
        if app is not None and not app.property("cdflowAccent"):
            apply_theme(app, DEFAULT_ACCENT)

        self._snapshot = StateSnapshot()
        self._pages: dict[str, StatefulPage] = {}
        self._current_page_id = "now_playing"
        self._collection: tuple[Album, ...] = ()
        self._preferences: Mapping[str, Any] | object | None = None
        self._disc_id = ""
        self._playback: dict[str, Any] = {
            "track": None,
            "track_number": 0,
            "album": None,
            "playing": False,
            "position_seconds": 0,
            "duration_seconds": 0,
            "volume": 72,
            "muted": False,
            "shuffle": False,
            "repeat": False,
            "seekable": True,
        }
        self._message_serial = 0
        self._factories = {
            "now_playing": NowPlayingPage,
            "tracks": TracksPage,
            "rip_cd": RipCDPage,
            "browse_files": BrowseFilesPage,
            "disc_info": DiscInfoPage,
            "collection": CollectionPage,
            "settings": SettingsPage,
        }
        self._build_ui()
        self._install_shortcuts()
        self.show_page("now_playing", emit=False)
        self.set_state(self._snapshot)

    @property
    def current_page_id(self) -> str:
        return self._current_page_id

    @property
    def snapshot(self) -> StateSnapshot:
        return self._snapshot

    @property
    def created_pages(self) -> Mapping[str, StatefulPage]:
        """Read-only-by-convention view of pages already instantiated."""

        return dict(self._pages)

    def page_widget(self, page_id: str, *, create: bool = True) -> StatefulPage | None:
        """Return a page by stable ID, constructing it only when requested."""

        if page_id not in PAGE_IDS:
            raise ValueError(f"unknown page: {page_id}")
        if page_id not in self._pages and create:
            return self._create_page(page_id)
        return self._pages.get(page_id)

    def show_page(self, page_id: str, *, emit: bool = True) -> None:
        page = self.page_widget(page_id)
        assert page is not None
        changed = page_id != self._current_page_id or self.page_stack.currentWidget() is not page
        self._current_page_id = page_id
        self.page_stack.setCurrentWidget(page)
        self.sidebar.set_current_page(page_id)
        if emit:
            self.page_requested.emit(page_id)
        if changed:
            self.page_changed.emit(page_id)

    def set_state(self, snapshot: StateSnapshot) -> None:
        """Primary render entry point for drive/disc/application state."""

        previous_disc_id = self._disc_id
        self._snapshot = snapshot
        self._disc_id = snapshot.disc.disc_id if snapshot.disc else ""
        self.sidebar.set_state(snapshot)
        has_audio = snapshot.status in {AppStatus.AUDIO_CD, AppStatus.RIPPING}
        self.player_bar.set_audio_enabled(snapshot.status == AppStatus.AUDIO_CD)
        album = snapshot.disc.album if snapshot.disc else None
        self._playback["album"] = album
        if not has_audio or self._disc_id != previous_disc_id:
            self._playback.update(track=None, track_number=0, playing=False, position_seconds=0, duration_seconds=0)
        if not has_audio:
            self.player_bar.set_track(None, None)
        elif self._playback.get("track") is None:
            self.player_bar.set_track(None, album)
        elif album and self._playback.get("track_number"):
            number = int(self._playback["track_number"])
            refreshed_track = next((track for track in album.tracks if track.number == number), None)
            if refreshed_track is not None:
                self._playback["track"] = refreshed_track
                self._playback["duration_seconds"] = refreshed_track.duration_seconds
        for page in tuple(self._pages.values()):
            page.set_state(snapshot)
        self._render_playback()

    def set_collection(self, albums: Iterable[Album]) -> None:
        self._collection = tuple(albums)
        page = self._pages.get("collection")
        if isinstance(page, CollectionPage):
            page.set_albums(self._collection)

    def set_preferences(self, preferences: Mapping[str, Any] | object) -> None:
        """Update Settings and Rip defaults from a mapping or Preferences object."""

        self._preferences = preferences
        settings = self._pages.get("settings")
        if isinstance(settings, SettingsPage):
            settings.set_values(preferences)
        rip = self._pages.get("rip_cd")
        if isinstance(rip, RipCDPage):
            rip.set_configuration(self._rip_preferences(preferences))
        volume = self._value(preferences, "default_volume", 72)
        self._playback["volume"] = int(volume)
        self.player_bar.set_volume(int(volume), bool(self._value(preferences, "muted", False)))

    def set_playback_state(self, state: Mapping[str, Any] | object | None = None, **changes: Any) -> None:
        """Render playback values; accepts a mapping/object plus keyword overrides.

        Recognized keys are ``track``/``track_number``, ``album``, ``playing``,
        ``position_seconds``, ``duration_seconds``, ``volume``, ``muted``,
        ``shuffle``, ``repeat`` and ``seekable``.
        """

        if state is not None:
            if isinstance(state, Mapping):
                changes = {**state, **changes}
            else:
                for key in tuple(self._playback):
                    if hasattr(state, key):
                        changes.setdefault(key, getattr(state, key))
        changed_keys = set(changes)
        if "current_track" in changes and "track" not in changes:
            changes["track"] = changes.pop("current_track")
        if "position" in changes and "position_seconds" not in changes:
            changes["position_seconds"] = changes.pop("position")
        if "duration" in changes and "duration_seconds" not in changes:
            changes["duration_seconds"] = changes.pop("duration")
        if "track" in changes and changes["track"] is None and "track_number" not in changes:
            changes["track_number"] = 0
        if "track_number" in changes and "track" not in changes:
            changes["track"] = None
        self._playback.update({key: value for key, value in changes.items() if key in self._playback})
        album = self._playback.get("album") or (self._snapshot.disc.album if self._snapshot.disc else None)
        track = self._playback.get("track")
        number = int(self._playback.get("track_number") or 0)
        if isinstance(track, int):
            number = track
            track = None
            self._playback["track"] = None
            self._playback["track_number"] = number
        if track is None and number and album:
            track = next((item for item in album.tracks if item.number == number), None)
        if isinstance(track, Track):
            self._playback["track"] = track
            self._playback["track_number"] = track.number
            if "duration_seconds" not in changed_keys and "duration" not in changed_keys:
                self._playback["duration_seconds"] = track.duration_seconds
        self._playback["album"] = album
        self._render_playback()

    def set_rip_progress(self, **progress: Any) -> None:
        page = self.page_widget("rip_cd")
        assert isinstance(page, RipCDPage)
        page.set_rip_progress(**progress)

    def reset_rip_progress(self) -> None:
        page = self._pages.get("rip_cd")
        if isinstance(page, RipCDPage):
            page.reset_progress()

    def set_browse_root(self, path: str) -> None:
        page = self.page_widget("browse_files")
        assert isinstance(page, BrowseFilesPage)
        page.set_root_path(path)

    def set_rip_destination(self, path: str) -> None:
        page = self.page_widget("rip_cd")
        assert isinstance(page, RipCDPage)
        page.set_destination(path)

    def set_settings_destination(self, path: str) -> None:
        page = self.page_widget("settings")
        assert isinstance(page, SettingsPage)
        page.set_destination(path)

    def show_message(self, text: str, *, level: str = "info", timeout_ms: int = 5000) -> None:
        """Show a non-modal application message; zero timeout keeps it visible."""

        self._message_serial += 1
        serial = self._message_serial
        self.notice.show_message(text, level=level)
        if timeout_ms > 0:
            QTimer.singleShot(timeout_ms, lambda: self._hide_message(serial))

    def restore_geometry_data(self, data: bytes | QByteArray) -> bool:
        return self.restoreGeometry(QByteArray(data))

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        compact = event.size().width() < 1120
        self.sidebar.set_compact(compact)
        self.player_bar.set_compact(compact)
        now_playing = self._pages.get("now_playing")
        if isinstance(now_playing, NowPlayingPage):
            now_playing.set_compact(compact)

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        self.window_geometry_changed.emit(bytes(self.saveGeometry()))
        super().closeEvent(event)

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("appRoot")
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.sidebar = Sidebar()
        self.sidebar.page_requested.connect(self.show_page)
        self.sidebar.drive_selected.connect(self.drive_selected)
        self.sidebar.eject_requested.connect(self.eject_requested)
        layout.addWidget(self.sidebar)

        content = QWidget()
        content.setObjectName("appRoot")
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(0, 0, 12, 12)
        content_layout.setSpacing(8)
        self.notice = InlineNotice()
        self.notice.setContentsMargins(6, 2, 6, 0)
        content_layout.addWidget(self.notice)
        self.page_stack = QStackedWidget()
        content_layout.addWidget(self.page_stack, 1)
        self.player_bar = PlayerBar()
        content_layout.addWidget(self.player_bar)
        layout.addWidget(content, 1)
        self.setCentralWidget(root)

        self.player_bar.play_requested.connect(self.play_requested)
        self.player_bar.pause_requested.connect(self.pause_requested)
        self.player_bar.stop_requested.connect(self.stop_requested)
        self.player_bar.previous_requested.connect(self.previous_requested)
        self.player_bar.next_requested.connect(self.next_requested)
        self.player_bar.seek_requested.connect(self.seek_requested)
        self.player_bar.volume_changed.connect(self.volume_changed)
        self.player_bar.mute_toggled.connect(self.mute_toggled)
        self.player_bar.shuffle_toggled.connect(self.shuffle_toggled)
        self.player_bar.repeat_toggled.connect(self.repeat_toggled)

    def _create_page(self, page_id: str) -> StatefulPage:
        page = self._factories[page_id]()
        self._pages[page_id] = page
        self.page_stack.addWidget(page)
        page.retry_requested.connect(self.retry_requested)
        self._connect_page(page_id, page)
        page.set_state(self._snapshot)
        if isinstance(page, CollectionPage):
            page.set_albums(self._collection)
        elif isinstance(page, SettingsPage) and self._preferences is not None:
            page.set_values(self._preferences)
        elif isinstance(page, RipCDPage) and self._preferences is not None:
            page.set_configuration(self._rip_preferences(self._preferences))
        if isinstance(page, NowPlayingPage):
            page.set_compact(self.width() < 1120)
        return page

    def _connect_page(self, page_id: str, page: StatefulPage) -> None:
        del page_id
        if isinstance(page, NowPlayingPage):
            page.track_activated.connect(self.track_activated)
            page.rip_clicked.connect(lambda: self.show_page("rip_cd"))
            page.disc_info_clicked.connect(lambda: self.show_page("disc_info"))
        elif isinstance(page, TracksPage):
            page.track_activated.connect(self.track_activated)
            page.rip_track_requested.connect(self.rip_track_requested)
            page.track_info_requested.connect(self.track_info_requested)
        elif isinstance(page, RipCDPage):
            page.rip_requested.connect(self.rip_requested)
            page.cancel_rip_requested.connect(self.cancel_rip_requested)
            page.destination_requested.connect(self.rip_destination_requested)
        elif isinstance(page, BrowseFilesPage):
            page.open_path_requested.connect(self.open_path_requested)
        elif isinstance(page, DiscInfoPage):
            page.metadata_refresh_requested.connect(self.metadata_refresh_requested)
        elif isinstance(page, CollectionPage):
            page.album_selected.connect(self.collection_album_selected)
        elif isinstance(page, SettingsPage):
            page.settings_changed.connect(self.settings_changed)
            page.destination_requested.connect(self.settings_destination_requested)
            page.accent_changed.connect(self._preview_accent)

    def _render_playback(self) -> None:
        track = self._playback.get("track")
        album = self._playback.get("album")
        self.player_bar.set_track(
            track if isinstance(track, Track) else None, album if isinstance(album, Album) else None
        )
        self.player_bar.set_playing(bool(self._playback.get("playing")))
        self.player_bar.set_position(
            float(self._playback.get("position_seconds") or 0),
            float(self._playback.get("duration_seconds") or 0),
            seekable=bool(self._playback.get("seekable", True)),
        )
        self.player_bar.set_volume(
            int(self._playback.get("volume") or 0),
            bool(self._playback.get("muted")),
        )
        self.player_bar.set_modes(
            shuffle=bool(self._playback.get("shuffle")),
            repeat=bool(self._playback.get("repeat")),
        )
        track_number = int(self._playback.get("track_number") or 0)
        for page in self._pages.values():
            if isinstance(page, (NowPlayingPage, TracksPage)):
                page.set_current_track(track_number)

    def _preview_accent(self, accent: str) -> None:
        app = QApplication.instance()
        if app is not None:
            apply_theme(app, accent)
        self.accent_changed.emit(accent)

    def _hide_message(self, serial: int) -> None:
        if serial == self._message_serial:
            self.notice.hide()

    def _install_shortcuts(self) -> None:
        shortcuts = (
            ("Ctrl+Space", self._shortcut_play_pause),
            ("Ctrl+Left", lambda: self._emit_audio_action(self.previous_requested)),
            ("Ctrl+Right", lambda: self._emit_audio_action(self.next_requested)),
            ("Ctrl+E", self._shortcut_eject),
        )
        self._shortcuts: list[QShortcut] = []
        for sequence, callback in shortcuts:
            shortcut = QShortcut(QKeySequence(sequence), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(callback)
            self._shortcuts.append(shortcut)
        for index, page_id in enumerate(PAGE_IDS, start=1):
            shortcut = QShortcut(QKeySequence(f"Ctrl+{index}"), self)
            shortcut.setContext(Qt.ShortcutContext.WindowShortcut)
            shortcut.activated.connect(lambda key=page_id: self.show_page(key))
            self._shortcuts.append(shortcut)

    def _shortcut_play_pause(self) -> None:
        if self._snapshot.status != AppStatus.AUDIO_CD:
            return
        (self.pause_requested if self._playback.get("playing") else self.play_requested).emit()

    def _emit_audio_action(self, signal: Signal) -> None:
        if self._snapshot.status == AppStatus.AUDIO_CD:
            signal.emit()

    def _shortcut_eject(self) -> None:
        if self.sidebar.eject_button.isVisible() and self.sidebar.eject_button.isEnabled():
            self.eject_requested.emit()

    @staticmethod
    def _value(source: Mapping[str, Any] | object, key: str, default: Any) -> Any:
        return source.get(key, default) if isinstance(source, Mapping) else getattr(source, key, default)

    @classmethod
    def _rip_preferences(cls, source: Mapping[str, Any] | object) -> dict:
        return {
            "format": cls._value(source, "rip_format", "flac"),
            "quality": cls._value(source, "rip_quality", "Lossless"),
            "destination": cls._value(source, "output_directory", ""),
            "filename_pattern": cls._value(source, "filename_pattern", ""),
            "embed_metadata": cls._value(source, "embed_metadata", True),
            "embed_artwork": cls._value(source, "embed_artwork", True),
        }


__all__ = ["MainWindow", "PAGE_IDS"]
