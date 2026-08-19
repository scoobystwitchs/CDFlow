"""The central state machine consumed by services and the Qt interface."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from enum import StrEnum

from cdflow.models.disc import Disc, Drive


class AppStatus(StrEnum):
    NO_DRIVE = "no_drive"
    EMPTY_DRIVE = "empty_drive"
    LOADING_DISC = "loading_disc"
    AUDIO_CD = "audio_cd"
    DATA_CD = "data_cd"
    RIPPING = "ripping"
    EJECTING = "ejecting"
    ERROR = "error"


@dataclass(slots=True, frozen=True)
class StateSnapshot:
    status: AppStatus = AppStatus.NO_DRIVE
    drives: tuple[Drive, ...] = ()
    selected_drive_path: str = ""
    disc: Disc | None = None
    message: str = "No optical drive found"
    generation: int = 0


class InvalidTransition(RuntimeError):
    pass


class ApplicationState:
    """Small observable state store with generation-based stale-result rejection."""

    _ALLOWED: dict[AppStatus, frozenset[AppStatus]] = {
        AppStatus.NO_DRIVE: frozenset(
            {AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE, AppStatus.LOADING_DISC, AppStatus.ERROR}
        ),
        AppStatus.EMPTY_DRIVE: frozenset(
            {AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE, AppStatus.LOADING_DISC, AppStatus.EJECTING, AppStatus.ERROR}
        ),
        AppStatus.LOADING_DISC: frozenset(
            {AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE, AppStatus.AUDIO_CD, AppStatus.DATA_CD, AppStatus.ERROR}
        ),
        AppStatus.AUDIO_CD: frozenset(
            {
                AppStatus.NO_DRIVE,
                AppStatus.EMPTY_DRIVE,
                AppStatus.LOADING_DISC,
                AppStatus.RIPPING,
                AppStatus.EJECTING,
                AppStatus.ERROR,
            }
        ),
        AppStatus.DATA_CD: frozenset(
            {AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE, AppStatus.LOADING_DISC, AppStatus.EJECTING, AppStatus.ERROR}
        ),
        AppStatus.RIPPING: frozenset({AppStatus.AUDIO_CD, AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE, AppStatus.ERROR}),
        AppStatus.EJECTING: frozenset({AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE, AppStatus.ERROR}),
        AppStatus.ERROR: frozenset(set(AppStatus)),
    }

    def __init__(self) -> None:
        self._snapshot = StateSnapshot()
        self._listeners: list[Callable[[StateSnapshot], None]] = []

    @property
    def snapshot(self) -> StateSnapshot:
        return self._snapshot

    def subscribe(self, listener: Callable[[StateSnapshot], None], *, emit_current: bool = True) -> Callable[[], None]:
        self._listeners.append(listener)
        if emit_current:
            listener(self._snapshot)

        def unsubscribe() -> None:
            if listener in self._listeners:
                self._listeners.remove(listener)

        return unsubscribe

    def transition(self, status: AppStatus, *, message: str | None = None, disc: Disc | None = None) -> StateSnapshot:
        current = self._snapshot.status
        # Same-state updates are intentional: metadata and artwork can enrich
        # the active disc without changing its lifecycle status.
        if status != current and status not in self._ALLOWED[current]:
            raise InvalidTransition(f"cannot transition from {current.value} to {status.value}")
        self._snapshot = replace(
            self._snapshot,
            status=status,
            disc=disc,
            message=message if message is not None else self._snapshot.message,
            generation=self._snapshot.generation + 1,
        )
        self._emit()
        return self._snapshot

    def set_drives(self, drives: list[Drive] | tuple[Drive, ...], selected_path: str = "") -> StateSnapshot:
        ordered = tuple(sorted(drives, key=lambda item: (item.display_name.casefold(), item.device)))
        available_paths = {drive.object_path for drive in ordered}
        selected = selected_path or self._snapshot.selected_drive_path
        if selected not in available_paths:
            selected = ordered[0].object_path if ordered else ""
        self._snapshot = replace(self._snapshot, drives=ordered, selected_drive_path=selected)
        self._emit()
        return self._snapshot

    def select_drive(self, object_path: str) -> None:
        if object_path not in {drive.object_path for drive in self._snapshot.drives}:
            raise ValueError("unknown optical drive")
        self._snapshot = replace(self._snapshot, selected_drive_path=object_path)
        self._emit()

    def accepts(self, generation: int) -> bool:
        return generation == self._snapshot.generation

    def _emit(self) -> None:
        for listener in tuple(self._listeners):
            listener(self._snapshot)
