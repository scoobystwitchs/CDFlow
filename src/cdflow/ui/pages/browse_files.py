"""Read-only, mount-root constrained browser for data CDs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QDir, QModelIndex, Qt, Signal
from PySide6.QtWidgets import QFileSystemModel, QHBoxLayout, QLineEdit, QPushButton, QTreeView, QVBoxLayout, QWidget

from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.disc import DiscKind

from ..icons import symbolic_icon
from ..widgets.common import Card, IconButton, PageHeader
from .base import StatefulPage


class BrowseFilesPage(StatefulPage):
    open_path_requested = Signal(str)
    available_statuses = {AppStatus.DATA_CD}
    available_disc_kinds = {DiscKind.MIXED}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAccessibleName("Browse Data CD Files")
        self._disc_root = Path()
        self._current_path = Path()
        self.header = PageHeader("Browse Files", "Data CDs are always opened read-only.")
        self.content_layout.addWidget(self.header)
        card = Card()
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(0, 0, 0, 0)
        card_layout.setSpacing(0)
        location = QHBoxLayout()
        location.setContentsMargins(10, 8, 10, 8)
        location.setSpacing(6)
        self.back_button = IconButton("chevron-left", "Go to parent folder")
        self.back_button.clicked.connect(self.go_up)
        location.addWidget(self.back_button)
        self.root_button = QPushButton("Disc Root")
        self.root_button.setIcon(symbolic_icon("disc"))
        self.root_button.clicked.connect(self.go_root)
        self.root_button.setToolTip("Return to the root of the mounted disc")
        location.addWidget(self.root_button)
        self.path_display = QLineEdit()
        self.path_display.setReadOnly(True)
        self.path_display.setAccessibleName("Current data CD path")
        location.addWidget(self.path_display, 1)
        card_layout.addLayout(location)
        self.model = QFileSystemModel(self)
        self.model.setReadOnly(True)
        self.model.setFilter(QDir.Filter.AllEntries | QDir.Filter.NoDotAndDotDot)
        self.model.setOption(QFileSystemModel.Option.DontUseCustomDirectoryIcons, True)
        self.tree = QTreeView()
        self.tree.setModel(self.model)
        self.tree.setRootIsDecorated(False)
        self.tree.setItemsExpandable(False)
        self.tree.setAlternatingRowColors(False)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.SortOrder.AscendingOrder)
        self.tree.setUniformRowHeights(True)
        self.tree.setEditTriggers(QTreeView.EditTrigger.NoEditTriggers)
        self.tree.setDragEnabled(False)
        self.tree.setAcceptDrops(False)
        self.tree.setAccessibleName("Files on data CD")
        self.tree.setToolTip("Double-click a folder to browse it or a file to open it")
        self.tree.doubleClicked.connect(self._activate)
        header = self.tree.header()
        header.setStretchLastSection(False)
        header.setSectionResizeMode(0, header.ResizeMode.Stretch)
        header.setSectionResizeMode(1, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, header.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(3, header.ResizeMode.ResizeToContents)
        card_layout.addWidget(self.tree, 1)
        self.content_layout.addWidget(card, 1)

    @property
    def root_path(self) -> str:
        return str(self._disc_root) if str(self._disc_root) != "." else ""

    def set_root_path(self, path: str) -> None:
        if not path:
            self._disc_root = Path()
            self._current_path = Path()
            self.path_display.clear()
            return
        candidate = Path(path).resolve()
        self._disc_root = candidate
        self.model.setRootPath(str(candidate))
        self._show_directory(candidate)

    def go_root(self) -> None:
        if self.root_path:
            self._show_directory(self._disc_root)

    def go_up(self) -> None:
        if not self.root_path or self._current_path == self._disc_root:
            return
        parent = self._current_path.parent
        if self._within_root(parent):
            self._show_directory(parent)

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        disc = snapshot.disc
        if snapshot.status != AppStatus.DATA_CD or disc is None:
            return
        if not disc.primary_mount_point:
            self.show_empty_message(
                "Data CD Is Not Mounted",
                snapshot.message or "The filesystem must be mounted before its files can be shown.",
                icon="folder",
                action="Try Again",
            )
            return
        if disc.primary_mount_point != self.root_path:
            self.set_root_path(disc.primary_mount_point)
        self.show_content()
        details = [disc.label or "Data CD"]
        if disc.filesystem_type:
            details.append(disc.filesystem_type.upper())
        self.header.set_subtitle(" · ".join(details) + " · Read-only")

    def _activate(self, index: QModelIndex) -> None:
        path = Path(self.model.filePath(index)).resolve()
        if not self._within_root(path):
            return
        if path.is_dir():
            self._show_directory(path)
        elif path.is_file():
            self.open_path_requested.emit(str(path))

    def _show_directory(self, path: Path) -> None:
        if not self._within_root(path):
            return
        self._current_path = path
        self.tree.setRootIndex(self.model.index(str(path)))
        try:
            relative = path.relative_to(self._disc_root)
            display = "/" if str(relative) == "." else f"/{relative}"
        except ValueError:
            display = "/"
        self.path_display.setText(display)
        self.back_button.setEnabled(path != self._disc_root)

    def _within_root(self, path: Path) -> bool:
        if not self.root_path:
            return False
        try:
            path.relative_to(self._disc_root)
            return True
        except ValueError:
            return False


__all__ = ["BrowseFilesPage"]
