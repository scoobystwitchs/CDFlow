from __future__ import annotations

from collections.abc import Callable

import pytest

from cdflow.app.state import ApplicationState, AppStatus, InvalidTransition
from cdflow.models.disc import Disc, DiscKind, Drive


def make_drive(path: str, *, vendor: str, model: str, device: str) -> Drive:
    return Drive(object_path=path, vendor=vendor, model=model, device=device)


def test_state_starts_idle_without_a_drive() -> None:
    state = ApplicationState()

    assert state.snapshot.status is AppStatus.NO_DRIVE
    assert state.snapshot.drives == ()
    assert state.snapshot.selected_drive_path == ""
    assert state.snapshot.generation == 0


def test_drive_list_is_stable_and_preserves_an_available_selection() -> None:
    state = ApplicationState()
    zeta = make_drive("/drive/z", vendor="Zeta", model="Drive", device="/dev/sr1")
    alpha = make_drive("/drive/a", vendor="Alpha", model="Drive", device="/dev/sr0")

    first = state.set_drives([zeta, alpha])
    assert first.drives == (alpha, zeta)
    assert first.selected_drive_path == alpha.object_path

    state.select_drive(zeta.object_path)
    updated = state.set_drives([alpha, zeta])
    assert updated.selected_drive_path == zeta.object_path


def test_removed_selected_drive_falls_back_then_clears() -> None:
    state = ApplicationState()
    first = make_drive("/drive/1", vendor="A", model="Drive", device="/dev/sr0")
    second = make_drive("/drive/2", vendor="B", model="Drive", device="/dev/sr1")
    state.set_drives([first, second], selected_path=second.object_path)

    assert state.set_drives([first]).selected_drive_path == first.object_path
    assert state.set_drives([]).selected_drive_path == ""


def test_unknown_drive_cannot_be_selected() -> None:
    state = ApplicationState()

    with pytest.raises(ValueError, match="unknown optical drive"):
        state.select_drive("/drive/missing")


def test_valid_disc_loading_sequence_increments_generation() -> None:
    state = ApplicationState()
    drive = make_drive("/drive/1", vendor="A", model="Drive", device="/dev/sr0")
    disc = Disc(kind=DiscKind.AUDIO, drive=drive, disc_id="disc-1")
    state.set_drives([drive])

    loading = state.transition(AppStatus.LOADING_DISC, message="Reading disc")
    ready = state.transition(AppStatus.AUDIO_CD, message="Audio CD", disc=disc)

    assert loading.generation == 1
    assert ready.generation == 2
    assert ready.disc is disc
    assert state.accepts(ready.generation)
    assert not state.accepts(loading.generation)


def test_invalid_state_transition_is_rejected_without_mutation() -> None:
    state = ApplicationState()
    before = state.snapshot

    with pytest.raises(InvalidTransition, match="no_drive to ripping"):
        state.transition(AppStatus.RIPPING)

    assert state.snapshot is before


def test_listener_gets_initial_and_future_snapshots_then_can_unsubscribe() -> None:
    state = ApplicationState()
    seen = []

    unsubscribe = state.subscribe(seen.append)
    state.transition(AppStatus.EMPTY_DRIVE, message="No media")
    unsubscribe()
    state.transition(AppStatus.LOADING_DISC)

    assert [snapshot.status for snapshot in seen] == [AppStatus.NO_DRIVE, AppStatus.EMPTY_DRIVE]


def test_listener_can_unsubscribe_itself_during_notification() -> None:
    state = ApplicationState()
    calls = 0
    unsubscribe_callbacks: list[Callable[[], None]] = []

    def listener(_snapshot: object) -> None:
        nonlocal calls
        calls += 1
        if calls > 1:
            unsubscribe_callbacks[0]()

    unsubscribe_callbacks.append(state.subscribe(listener))
    state.transition(AppStatus.EMPTY_DRIVE)
    state.transition(AppStatus.LOADING_DISC)

    assert calls == 2
