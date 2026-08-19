"""State-aware base class for lazily-created content pages."""

from __future__ import annotations

from collections.abc import Collection

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QStackedLayout, QVBoxLayout, QWidget

from cdflow.app.state import AppStatus, StateSnapshot
from cdflow.models.disc import DiscKind

from ..widgets.common import EmptyState


class StatefulPage(QWidget):
    """Switch between page content and a consistent unavailable state."""

    retry_requested = Signal()
    available_statuses: Collection[AppStatus] = ()
    available_disc_kinds: Collection[DiscKind] = ()
    always_available = False

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("pageRoot")
        self._snapshot = StateSnapshot()
        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.content = QWidget()
        self.content.setObjectName("pageRoot")
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 16, 18, 12)
        self.content_layout.setSpacing(12)
        self.empty_state = EmptyState()
        self.empty_state.action_requested.connect(self.retry_requested)
        self.stack.addWidget(self.content)
        self.stack.addWidget(self.empty_state)

    @property
    def snapshot(self) -> StateSnapshot:
        return self._snapshot

    def set_state(self, snapshot: StateSnapshot) -> None:
        self._snapshot = snapshot
        available = (
            self.always_available
            or snapshot.status in self.available_statuses
            or bool(snapshot.disc and snapshot.disc.kind in self.available_disc_kinds)
        )
        self.stack.setCurrentWidget(self.content if available else self.empty_state)
        if not available:
            self._set_unavailable_state(snapshot)
        self.update_from_state(snapshot)

    def update_from_state(self, snapshot: StateSnapshot) -> None:
        """Subclasses update their content here without querying services."""

    def show_content(self) -> None:
        self.stack.setCurrentWidget(self.content)

    def show_empty_message(self, title: str, body: str, *, icon: str = "disc", action: str = "") -> None:
        self.empty_state.set_message(title, body, icon=icon, action=action)
        self.stack.setCurrentWidget(self.empty_state)

    def _set_unavailable_state(self, snapshot: StateSnapshot) -> None:
        if snapshot.status == AppStatus.DATA_CD:
            self.empty_state.set_message(
                "Data CD Inserted",
                "This page is available for Audio CDs.\nOpen Browse Files to view this disc.",
                icon="folder",
            )
        else:
            self.empty_state.set_state(snapshot.status, snapshot.message)


__all__ = ["StatefulPage"]
