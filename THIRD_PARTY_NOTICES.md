# Third-party notices

CDFlow is MIT-licensed. Its standalone Linux bundle also contains or loads
components from these projects:

- Python — Python Software Foundation License 2.0.
- Qt for Python (PySide6 and Shiboken6) and Qt 6 — distributed under the
  LGPL-3.0-only option (alternative upstream terms are also available).
- dbus-next — MIT License.
- PyInstaller bootloader/runtime — GPL-2.0-or-later with the PyInstaller
  bootloader exception.
- AppImageKit runtime — MIT License.
- GStreamer core and the base/good plug-ins — LGPL-2.1-or-later; the PipeWire
  GStreamer plug-in is MIT-licensed.

The corresponding upstream source and license texts are available from:

- https://www.python.org/downloads/source/
- https://code.qt.io/cgit/pyside/pyside-setup.git/
- https://code.qt.io/cgit/qt/
- https://github.com/altdesktop/python-dbus-next
- https://github.com/pyinstaller/pyinstaller
- https://github.com/AppImage/AppImageKit
- https://gstreamer.freedesktop.org/src/
- https://gitlab.freedesktop.org/pipewire/pipewire

An AppImage uses additional system components—including UDisks2, GLib,
PipeWire, filesystem drivers, and external extraction/encoding programs—from
the host rather than redistributing them. The exact binary inventory can vary
with the build host; release builders should retain its package manifest and
review any additional libraries collected by PyInstaller.
