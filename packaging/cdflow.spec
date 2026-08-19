# -*- mode: python ; coding: utf-8 -*-
from pathlib import Path
from importlib.util import find_spec

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

PROJECT_ROOT = Path(SPECPATH).parent
SRC_ROOT = PROJECT_ROOT / "src"

datas = collect_data_files("cdflow")
hiddenimports = collect_submodules("dbus_next")
if find_spec("gi") is None:
    raise RuntimeError(
        "PyGObject is required for an AppImage build. Install python3-gobject "
        "and create the build venv with --system-site-packages."
    )

# Playback imports Gst lazily so source installations can still start without
# it. A release bundle must include the real playback backend and its typelib.
import gi

try:
    gi.require_version("Gst", "1.0")
    from gi.repository import Gst

    Gst.init(None)
except (ImportError, ValueError, RuntimeError) as error:
    raise RuntimeError("GStreamer introspection bindings are required for an AppImage build") from error
if Gst.ElementFactory.find("cdparanoiasrc") is None:
    raise RuntimeError("The GStreamer cdparanoiasrc plugin is required for an AppImage build")
if not any(Gst.ElementFactory.find(name) is not None for name in ("pipewiresink", "pulsesink", "alsasink")):
    raise RuntimeError("A GStreamer PipeWire, PulseAudio, or ALSA output plugin is required for an AppImage build")

hiddenimports += ["gi", "gi.repository.Gst"]

# The Gst hook otherwise copies every plugin installed on the build host. CDDA
# is already raw PCM, so playback only needs the source, core/playback plumbing,
# format conversion, volume, and common Fedora audio sinks.
hooksconfig = {
    "gi": {"languages": []},
    "gstreamer": {
        "include_plugins": [
            "alsa",
            "audioconvert",
            "audiorate",
            "audioresample",
            "autodetect",
            "cdparanoia",
            "coreelements",
            "pipewire",
            "playback",
            "pulseaudio",
            "typefindfunctions",
            "volume",
        ]
    },
}

analysis = Analysis(
    [str(PROJECT_ROOT / "packaging" / "pyinstaller_entry.py")],
    pathex=[str(SRC_ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig=hooksconfig,
    runtime_hooks=[],
    excludes=["tkinter", "unittest"],
    noarchive=False,
)
pyz = PYZ(analysis.pure)

executable = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="cdflow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="cdflow",
)
