"""Track list model and reusable table view."""

from __future__ import annotations

from collections.abc import Iterable

from PySide6.QtCore import QAbstractTableModel, QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QAbstractItemView, QApplication, QHeaderView, QMenu, QTableView, QWidget

from cdflow.models.track import Track

from ..icons import symbolic_icon
from ..theme import DEFAULT_THEME

_ROOT_INDEX = QModelIndex()


class TrackListModel(QAbstractTableModel):
    rip_selection_changed = Signal(int, bool)

    def __init__(self, parent: QWidget | None = None, *, checkable: bool = False, show_status: bool = True) -> None:
        super().__init__(parent)
        self._tracks: list[Track] = []
        self._checked: dict[int, bool] = {}
        self._checkable = checkable
        self._show_status = show_status
        self._current_track = 0

    @property
    def tracks(self) -> tuple[Track, ...]:
        return tuple(self._tracks)

    def set_tracks(self, tracks: Iterable[Track], *, preserve_checks: bool = True) -> None:
        self.beginResetModel()
        self._tracks = list(tracks)
        previous = self._checked if preserve_checks else {}
        self._checked = {track.number: previous.get(track.number, track.selected_for_ripping) for track in self._tracks}
        self.endResetModel()

    def clear(self) -> None:
        self.set_tracks(())

    def set_current_track(self, number: int) -> None:
        if number == self._current_track:
            return
        previous = self._current_track
        self._current_track = number
        for track_number in (previous, number):
            row = next((i for i, track in enumerate(self._tracks) if track.number == track_number), -1)
            if row >= 0:
                self.dataChanged.emit(self.index(row, 0), self.index(row, self.columnCount() - 1))

    def set_all_checked(self, checked: bool) -> None:
        if not self._checkable or not self._tracks:
            return
        for track in self._tracks:
            self._checked[track.number] = checked
        self.dataChanged.emit(
            self.index(0, 0),
            self.index(len(self._tracks) - 1, 0),
            [Qt.ItemDataRole.CheckStateRole],
        )
        for track in self._tracks:
            self.rip_selection_changed.emit(track.number, checked)

    def checked_track_numbers(self) -> list[int]:
        return [track.number for track in self._tracks if self._checked.get(track.number, False)]

    def track_at(self, row: int) -> Track | None:
        return self._tracks[row] if 0 <= row < len(self._tracks) else None

    def _columns(self) -> list[str]:
        columns = ["SELECT"] if self._checkable else []
        columns.extend(["#", "TITLE", "ARTIST", "LENGTH"])
        if self._show_status:
            columns.append("STATUS")
        return columns

    def rowCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._tracks)

    def columnCount(self, parent: QModelIndex = _ROOT_INDEX) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._columns())

    def headerData(self, section: int, orientation: Qt.Orientation, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        if role != Qt.ItemDataRole.DisplayRole:
            return None
        if orientation != Qt.Orientation.Horizontal:
            return section + 1
        label = self._columns()[section]
        return "" if label == "SELECT" else label

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self._tracks):
            return None
        track = self._tracks[index.row()]
        column = self._columns()[index.column()]
        if role == Qt.ItemDataRole.DisplayRole:
            return {
                "SELECT": "",
                "#": str(track.number),
                "TITLE": track.title,
                "ARTIST": track.artist,
                "LENGTH": track.duration_text,
                "STATUS": "Ripped" if track.ripped else "—",
            }[column]
        if role == Qt.ItemDataRole.CheckStateRole and column == "SELECT":
            return Qt.CheckState.Checked if self._checked.get(track.number, False) else Qt.CheckState.Unchecked
        if role == Qt.ItemDataRole.TextAlignmentRole and column in {"SELECT", "#", "LENGTH", "STATUS"}:
            return Qt.AlignmentFlag.AlignCenter
        if role == Qt.ItemDataRole.ForegroundRole:
            if track.number == self._current_track and column in {"#", "TITLE"}:
                return QApplication.palette().highlight().color()
            if column in {"#", "ARTIST", "LENGTH", "STATUS"}:
                return QColor(DEFAULT_THEME.text_muted)
        if role == Qt.ItemDataRole.BackgroundRole and track.number == self._current_track:
            highlight = QApplication.palette().highlight().color()
            highlight.setAlpha(40)
            return highlight
        if role == Qt.ItemDataRole.UserRole:
            return track.number
        if role == Qt.ItemDataRole.ToolTipRole:
            return f"Track {track.number}: {track.title} — {track.artist} ({track.duration_text})"
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:
        flags = Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable
        if index.isValid() and self._columns()[index.column()] == "SELECT":
            flags |= Qt.ItemFlag.ItemIsUserCheckable
        return flags

    def setData(self, index: QModelIndex, value, role: int = Qt.ItemDataRole.EditRole) -> bool:  # noqa: N802
        if not index.isValid() or role != Qt.ItemDataRole.CheckStateRole:
            return False
        if self._columns()[index.column()] != "SELECT":
            return False
        track = self._tracks[index.row()]
        checked = value == Qt.CheckState.Checked.value or value == Qt.CheckState.Checked
        self._checked[track.number] = checked
        self.dataChanged.emit(index, index, [Qt.ItemDataRole.CheckStateRole])
        self.rip_selection_changed.emit(track.number, checked)
        return True


class TrackFilterProxyModel(QSortFilterProxyModel):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFilterCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setSortCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.setDynamicSortFilter(True)

    def filterAcceptsRow(self, source_row: int, source_parent: QModelIndex) -> bool:  # noqa: N802
        pattern = self.filterRegularExpression()
        if pattern.pattern() == "":
            return True
        model = self.sourceModel()
        if not isinstance(model, TrackListModel):
            return True
        track = model.track_at(source_row)
        if track is None:
            return False
        needle = pattern.pattern().casefold()
        return needle in track.title.casefold() or needle in track.artist.casefold() or needle == str(track.number)

    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:  # noqa: N802
        model = self.sourceModel()
        if not isinstance(model, TrackListModel):
            return super().lessThan(left, right)
        left_track = model.track_at(left.row())
        right_track = model.track_at(right.row())
        if left_track is None or right_track is None:
            return super().lessThan(left, right)
        column = model._columns()[left.column()]
        if column in {"SELECT", "#"}:
            return left_track.number < right_track.number
        if column == "LENGTH":
            return left_track.duration_seconds < right_track.duration_seconds
        if column == "TITLE":
            return left_track.title.casefold() < right_track.title.casefold()
        if column == "ARTIST":
            return left_track.artist.casefold() < right_track.artist.casefold()
        return left_track.ripped < right_track.ripped


class TrackTable(QTableView):
    """Track table emitting domain identifiers instead of QModelIndexes."""

    track_activated = Signal(int)
    rip_track_requested = Signal(int)
    track_info_requested = Signal(int)
    rip_selection_changed = Signal(int, bool)

    def __init__(self, parent: QWidget | None = None, *, checkable: bool = False, show_status: bool = True) -> None:
        super().__init__(parent)
        self.track_model = TrackListModel(self, checkable=checkable, show_status=show_status)
        self.proxy_model = TrackFilterProxyModel(self)
        self.proxy_model.setSourceModel(self.track_model)
        self.setModel(self.proxy_model)
        self.setAlternatingRowColors(False)
        self.setShowGrid(False)
        self.setSortingEnabled(True)
        self.sortByColumn(1 if checkable else 0, Qt.SortOrder.AscendingOrder)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(36)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.setAccessibleName("Audio CD tracks")
        self.setToolTip("Double-click a track to play it")
        self.doubleClicked.connect(self._activate_index)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self.track_model.rip_selection_changed.connect(self.rip_selection_changed)
        self._configure_columns()

    def set_tracks(self, tracks: Iterable[Track], *, preserve_checks: bool = True) -> None:
        self.track_model.set_tracks(tracks, preserve_checks=preserve_checks)
        self._configure_columns()

    def set_current_track(self, track_number: int) -> None:
        self.track_model.set_current_track(track_number)

    def set_filter_text(self, text: str) -> None:
        from PySide6.QtCore import QRegularExpression

        self.proxy_model.setFilterRegularExpression(QRegularExpression.escape(text.strip()))

    def checked_track_numbers(self) -> list[int]:
        return self.track_model.checked_track_numbers()

    def set_all_checked(self, checked: bool) -> None:
        self.track_model.set_all_checked(checked)

    def _track_number(self, proxy_index: QModelIndex) -> int:
        if not proxy_index.isValid():
            return 0
        source = self.proxy_model.mapToSource(proxy_index)
        track = self.track_model.track_at(source.row())
        return track.number if track else 0

    def _activate_index(self, index: QModelIndex) -> None:
        number = self._track_number(index)
        if number:
            self.track_activated.emit(number)

    def _show_context_menu(self, point) -> None:
        index = self.indexAt(point)
        number = self._track_number(index)
        if not number:
            return
        menu = QMenu(self)
        play = menu.addAction(symbolic_icon("play"), "Play")
        rip = menu.addAction(symbolic_icon("rip"), "Rip this track")
        info = menu.addAction(symbolic_icon("info"), "Track information")
        chosen = menu.exec(self.viewport().mapToGlobal(point))
        if chosen is play:
            self.track_activated.emit(number)
        elif chosen is rip:
            self.rip_track_requested.emit(number)
        elif chosen is info:
            self.track_info_requested.emit(number)

    def _configure_columns(self) -> None:
        headers = self.track_model._columns()
        header = self.horizontalHeader()
        header.setStretchLastSection(False)
        for column, name in enumerate(headers):
            if name == "TITLE" or name == "ARTIST":
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(column, QHeaderView.ResizeMode.Fixed)
                self.setColumnWidth(column, {"SELECT": 42, "#": 44, "LENGTH": 78, "STATUS": 82}.get(name, 80))


__all__ = ["TrackFilterProxyModel", "TrackListModel", "TrackTable"]
