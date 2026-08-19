"""Small import shim for Qt signals used by backend services.

PySide6 is a required application dependency, but keeping the non-visual service
modules importable without it makes dependency diagnostics and headless tests
useful.  The fallback implements only the tiny signal/timer surface used here;
it is not a replacement for Qt and is never selected in a packaged build.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any, TypeVar

QT_AVAILABLE = True

try:  # pragma: no cover - exercised by the application runtime
    from PySide6.QtCore import QObject, QTimer, Signal, Slot
except ImportError:  # pragma: no cover - behavior is covered through consumers
    QT_AVAILABLE = False

    _T = TypeVar("_T", bound=Callable[..., Any])

    class _BoundSignal:
        def __init__(self) -> None:
            self._callbacks: list[Callable[..., Any]] = []
            self._lock = threading.RLock()

        def connect(self, callback: Callable[..., Any]) -> None:
            with self._lock:
                if callback not in self._callbacks:
                    self._callbacks.append(callback)

        def disconnect(self, callback: Callable[..., Any] | None = None) -> None:
            with self._lock:
                if callback is None:
                    self._callbacks.clear()
                elif callback in self._callbacks:
                    self._callbacks.remove(callback)

        def emit(self, *args: Any) -> None:
            with self._lock:
                callbacks = tuple(self._callbacks)
            for callback in callbacks:
                callback(*args)

    class Signal:
        """Descriptor matching the subset of ``PySide6.QtCore.Signal`` used here."""

        def __init__(self, *_types: object) -> None:
            self._name = ""

        def __set_name__(self, _owner: type[object], name: str) -> None:
            self._name = f"__signal_{name}"

        def __get__(self, instance: object | None, _owner: type[object]) -> Signal | _BoundSignal:
            if instance is None:
                return self
            signal = instance.__dict__.get(self._name)
            if signal is None:
                signal = _BoundSignal()
                instance.__dict__[self._name] = signal
            return signal

    class QObject:
        def __init__(self, parent: object | None = None) -> None:
            self._qt_fallback_parent = parent

    class QTimer(QObject):
        timeout = Signal()

        def __init__(self, parent: object | None = None) -> None:
            super().__init__(parent)
            self._interval_seconds = 0.25
            self._stop_event = threading.Event()
            self._thread: threading.Thread | None = None

        def setInterval(self, milliseconds: int) -> None:
            self._interval_seconds = max(milliseconds, 1) / 1000

        def isActive(self) -> bool:
            return self._thread is not None and self._thread.is_alive()

        def start(self, milliseconds: int | None = None) -> None:
            if milliseconds is not None:
                self.setInterval(milliseconds)
            if self.isActive():
                return
            self._stop_event.clear()
            self._thread = threading.Thread(target=self._run, daemon=True, name="cdflow-fallback-timer")
            self._thread.start()

        def stop(self) -> None:
            self._stop_event.set()

        def _run(self) -> None:
            while not self._stop_event.wait(self._interval_seconds):
                self.timeout.emit()

    def Slot(*_types: object, **_kwargs: object) -> Callable[[_T], _T]:
        def decorator(function: _T) -> _T:
            return function

        return decorator


__all__ = ["QObject", "QTimer", "QT_AVAILABLE", "Signal", "Slot"]
