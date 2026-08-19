"""Runtime dependency and capability detection.

Checks are deliberately lazy: importing CDFlow never launches a command, loads
GStreamer, or connects to D-Bus.  The settings UI can run :meth:`detect` when it
needs a diagnostic report.
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import threading
from dataclasses import dataclass
from enum import StrEnum
from functools import lru_cache

from .subprocess_env import host_process_environment


class DependencyKind(StrEnum):
    PYTHON = "python"
    EXECUTABLE = "executable"
    GSTREAMER_PLUGIN = "gstreamer-plugin"


@dataclass(frozen=True, slots=True)
class DependencyStatus:
    name: str
    kind: DependencyKind
    available: bool
    purpose: str
    required: bool = False
    location: str = ""
    detail: str = ""
    install_hint: str = ""


@dataclass(frozen=True, slots=True)
class DependencyReport:
    dependencies: tuple[DependencyStatus, ...]

    def by_name(self, name: str) -> DependencyStatus | None:
        return next((item for item in self.dependencies if item.name == name), None)

    @property
    def missing_required(self) -> tuple[DependencyStatus, ...]:
        return tuple(item for item in self.dependencies if item.required and not item.available)

    @property
    def can_monitor_drives(self) -> bool:
        dependency = self.by_name("dbus-next")
        return bool(dependency and dependency.available)

    @property
    def can_read_audio_discs(self) -> bool:
        return any(bool(item and item.available) for item in (self.by_name("cd-info"), self.by_name("cdparanoia")))

    @property
    def can_play_audio_discs(self) -> bool:
        gi = self.by_name("PyGObject")
        source = self.by_name("cdparanoiasrc")
        return bool(gi and gi.available and source and source.available)

    @property
    def can_rip_wav(self) -> bool:
        cdparanoia = self.by_name("cdparanoia")
        gst_launch = self.by_name("gst-launch-1.0")
        gst_source = self.by_name("cdparanoiasrc")
        gst_wav = self.by_name("wavenc")
        return bool(
            (cdparanoia and cdparanoia.available)
            or (
                gst_launch
                and gst_launch.available
                and gst_source
                and gst_source.available
                and gst_wav
                and gst_wav.available
            )
        )

    @property
    def can_encode_compressed_audio(self) -> bool:
        dependency = self.by_name("ffmpeg")
        return self.can_rip_wav and bool(dependency and dependency.available)


class DependencyDetector:
    """Detect executable, Python, and GStreamer requirements with short timeouts."""

    _lock = threading.Lock()

    @classmethod
    def detect(cls, *, refresh: bool = False) -> DependencyReport:
        if refresh:
            cls._detect_cached.cache_clear()
        with cls._lock:
            return cls._detect_cached()

    @staticmethod
    @lru_cache(maxsize=1)
    def _detect_cached() -> DependencyReport:
        dependencies = [
            _python_dependency(
                "PySide6",
                "PySide6",
                "Qt desktop interface and service signals",
                required=True,
                hint="Install the python3-pyside6 package or the project's Python dependencies.",
            ),
            _python_dependency(
                "dbus-next",
                "dbus_next",
                "event-driven UDisks2 integration",
                required=True,
                hint="Install the python3-dbus-next package.",
            ),
            _python_dependency(
                "PyGObject",
                "gi",
                "Python bindings for GStreamer playback",
                required=False,
                hint="Install python3-gobject and GStreamer introspection packages.",
            ),
            _executable_dependency(
                "cd-info",
                "Read and classify CD table-of-contents data",
                required=False,
                hint="On Fedora, install the libcdio package.",
            ),
            _executable_dependency(
                "cdparanoia",
                "Fallback secure CDDA extraction",
                required=False,
                hint="Install cdparanoia.",
            ),
            _executable_dependency(
                "gst-launch-1.0",
                "GStreamer CDDA extraction fallback",
                required=False,
                hint="Install GStreamer tools.",
            ),
            _gstreamer_plugin(
                "cdparanoiasrc",
                "Direct, error-corrected CDDA playback and extraction",
                hint="Install the GStreamer base plug-ins package.",
            ),
            _gstreamer_plugin(
                "wavenc",
                "Write extracted CDDA audio as a WAV stream",
                hint="Install the GStreamer base plug-ins package.",
            ),
            _executable_dependency(
                "ffmpeg",
                "FLAC/MP3 encoding and metadata embedding",
                required=False,
                hint="Install ffmpeg.",
            ),
            _executable_dependency(
                "lsblk",
                "Data-disc filesystem information",
                required=False,
                hint="Install util-linux.",
            ),
            _executable_dependency(
                "gio",
                "Open data-disc files with desktop applications",
                required=False,
                hint="Install glib2 tools.",
            ),
        ]
        return DependencyReport(tuple(dependencies))


def _python_dependency(
    name: str,
    module: str,
    purpose: str,
    *,
    required: bool,
    hint: str,
) -> DependencyStatus:
    try:
        spec = importlib.util.find_spec(module)
    except (ImportError, ModuleNotFoundError, ValueError) as error:
        return DependencyStatus(
            name, DependencyKind.PYTHON, False, purpose, required, detail=str(error), install_hint=hint
        )
    location = str(spec.origin or "") if spec else ""
    return DependencyStatus(
        name, DependencyKind.PYTHON, spec is not None, purpose, required, location, install_hint=hint
    )


def _executable_dependency(
    name: str,
    purpose: str,
    *,
    required: bool,
    hint: str,
) -> DependencyStatus:
    location = shutil.which(name) or ""
    return DependencyStatus(
        name, DependencyKind.EXECUTABLE, bool(location), purpose, required, location, install_hint=hint
    )


def _gstreamer_plugin(name: str, purpose: str, *, hint: str) -> DependencyStatus:
    inspector = shutil.which("gst-inspect-1.0")
    if not inspector:
        return DependencyStatus(
            name,
            DependencyKind.GSTREAMER_PLUGIN,
            False,
            purpose,
            detail="gst-inspect-1.0 was not found",
            install_hint=hint,
        )
    try:
        result = subprocess.run(
            [inspector, "--exists", name],
            check=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=3,
            env=host_process_environment(gstreamer=True),
        )
    except (OSError, subprocess.SubprocessError) as error:
        return DependencyStatus(
            name, DependencyKind.GSTREAMER_PLUGIN, False, purpose, detail=str(error), install_hint=hint
        )
    return DependencyStatus(
        name,
        DependencyKind.GSTREAMER_PLUGIN,
        result.returncode == 0,
        purpose,
        location=inspector,
        install_hint=hint,
    )


__all__ = [
    "DependencyDetector",
    "DependencyKind",
    "DependencyReport",
    "DependencyStatus",
]
