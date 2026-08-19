# CDFlow

CDFlow is a lightweight, local-first Linux desktop companion for physical
compact discs. It is designed for Fedora KDE Plasma and Wayland, with a Qt 6
interface and event-driven UDisks2 integration. There is no account, web view,
local server, or required cloud service.

> **Development status:** CDFlow is an early development release. The UI can be
> exercised with deterministic demo discs, and pure application logic has an
> automated test suite. Real-drive behavior, playback, eject, and ripping still
> need to be checked on each target hardware/software combination; see the
> manual checklist below.

## What CDFlow is designed to do

- React to optical-drive and media changes through UDisks2 D-Bus events.
- Classify audio, data, mixed-mode, and unsupported optical media where the
  drive exposes enough information.
- Show audio-CD tracks, disc and drive details, and playback controls.
- Extract selected CDDA tracks outside the GUI thread and encode FLAC, WAV, or
  MP3 using local command-line tools.
- Browse a mounted data CD read-only and open files with the desktop default.
- Optionally fetch MusicBrainz/Cover Art Archive information, then use a local
  cache so the core application remains useful offline.

The exact feature that is available at runtime depends on the inserted media,
drive permissions, and installed helper programs. CDFlow never assumes that an
optical drive is `/dev/sr0`.

## Fedora KDE setup

CDFlow requires Python 3.12 or newer. A normal Fedora KDE installation already
provides D-Bus, PipeWire, and the Qt Wayland support needed by the desktop. Add
the optical-disc helpers with:

```bash
sudo dnf install \
    python3 python3-pip python3-gobject \
    udisks2 libcdio cdparanoia ffmpeg-free \
    gstreamer1 gstreamer1-plugins-base gstreamer1-plugins-good
```

`udisks2` supplies the system D-Bus service and `udisksctl`; `libcdio` supplies
`cd-info`; `cdparanoia` provides accurate CDDA reads; GStreamer/PyGObject
provide the direct playback path; and `ffmpeg-free` provides local encoders
used when conversion is required. WAV extraction does not need a lossy encoder.

Create an isolated Python environment and install CDFlow:

```bash
python3 --version
python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -e .
```

PySide6 is installed from its Python wheel. This keeps the project independent
of Fedora's Python Qt-binding package version. `--system-site-packages` makes
Fedora's ABI-matched PyGObject/GStreamer binding visible in the environment;
installing PyGObject into a sealed venv would otherwise require its native build
dependencies. The wheel does not replace the host's UDisks2 daemon or
CDDA/encoding tools.

## Run from source

```bash
./run.sh
```

Useful development modes do not touch an optical drive:

```bash
./run.sh --demo audio
./run.sh --demo data
./run.sh --demo empty
./run.sh --debug
./run.sh --diagnose
```

`--diagnose` prints which required and optional local components were found,
including the real GStreamer CDDA backend, without opening the GUI.

If `.venv/bin/python` exists, `run.sh` uses it. Otherwise it uses `python3` (or
the executable in `PYTHON`). It also adds `src/` to `PYTHONPATH` when the
package has not been installed.

Qt normally selects Wayland automatically in a Plasma Wayland session. To
diagnose a platform-selection problem, compare:

```bash
QT_QPA_PLATFORM=wayland ./run.sh --debug
QT_QPA_PLATFORM=xcb ./run.sh --debug
```

The second command is an XWayland fallback, not the preferred configuration.

## Tests and development checks

```bash
.venv/bin/python -m pip install -e '.[dev]'
.venv/bin/python -m pytest
.venv/bin/python -m ruff check src tests
```

The automated suite deliberately focuses on deterministic logic such as model
duration conversion, central-state transitions, settings validation, metadata
parsing, filename safety, and job planning. It does not claim to emulate an
optical drive or certify physical-media behavior.

## Build an AppImage

The AppImage is assembled in two stages: PyInstaller creates a self-contained
Python/Qt directory, then AppImageKit's `appimagetool` wraps that directory.
Build on the oldest glibc-based distribution you intend to support; an AppImage
built on a newer Fedora release may not run on older Linux systems.

Install build dependencies and the project build extra:

```bash
sudo dnf install binutils patchelf
.venv/bin/python -m pip install -e '.[appimage]'
```

Download the x86_64 `appimagetool` from the official
[AppImageKit releases](https://github.com/AppImage/AppImageKit/releases), mark
it executable, and pass its absolute path to the build:

```bash
chmod +x /path/to/appimagetool-x86_64.AppImage
APPIMAGETOOL=/path/to/appimagetool-x86_64.AppImage ./build-appimage.sh
```

To build and inspect only the self-contained PyInstaller directory (useful
before `appimagetool` is available), run:

```bash
.venv/bin/python -m PyInstaller --noconfirm --clean packaging/cdflow.spec
./dist/cdflow/cdflow --diagnose
```

The result is written to `dist/CDFlow-0.1.0-x86_64.AppImage`. The build script
does not download tools or install packages, and it refuses to clear any path
other than its fixed `build/CDFlow.AppDir` staging directory.

On systems without FUSE 2 compatibility, either install Fedora's `fuse-libs`
package or launch the completed image with:

```bash
./dist/CDFlow-0.1.0-x86_64.AppImage --appimage-extract-and-run
```

### AppImage boundary

The image bundles CDFlow's Python and Qt libraries. It intentionally uses the
host session's D-Bus, UDisks2/polkit policy, audio service, default application
associations, and optical-device access. External extraction/encoding programs
may also be resolved from the host. Consequently, “AppImage” does not mean the
application can bypass host permissions or supply missing kernel/drive support.

## Local data and privacy

CDFlow follows the XDG base-directory convention:

| Purpose | Default location |
| --- | --- |
| Preferences | `~/.config/cdflow/` |
| Metadata/artwork cache | `~/.cache/cdflow/` |
| Remembered collection | `~/.local/share/cdflow/` |
| Ripped music | `~/Music/CDFlow/` |

Set `XDG_CONFIG_HOME`, `XDG_CACHE_HOME`, or `XDG_DATA_HOME` before launch to
relocate the first three. Metadata and artwork lookup are optional. Disabling
them leaves drive detection, locally available disc information, playback, data
browsing, and ripping independent of the network.

MusicBrainz requires API clients to provide a maintainer contact in their
User-Agent. Enter an email address or project URL in **Settings → Metadata**;
CDFlow sends it only in MusicBrainz and Cover Art Archive requests and does not
start an online lookup while it is blank. See the official
[MusicBrainz rate-limit policy](https://musicbrainz.org/doc/MusicBrainz_API/Rate_Limiting).

## Optical-drive permissions

In a normal local Plasma session, udev logind ACLs and UDisks2/polkit should
grant the active user appropriate access. Do **not** work around a problem with
`chmod 666 /dev/sr*` or by running CDFlow as root.

Diagnose the actual device reported by CDFlow:

```bash
udisksctl status
getfacl /dev/sr0
cdparanoia -d /dev/sr0 -Q
```

Replace `/dev/sr0` with the path shown by CDFlow/UDisks2. If `cdparanoia -Q`
also fails, the issue is below CDFlow: check the desktop session ACL, cable,
drive firmware, media condition, and system journal. Some systems use a `cdrom`
group, but group membership is distribution and policy dependent; prefer fixing
the session ACL/polkit configuration rather than granting broad permanent raw
device access.

## Manual hardware checklist

Run this checklist on Fedora KDE/Wayland with `./run.sh --debug`. Record the
Fedora version, kernel, drive make/model, connection type, and disc used so a
failure can be reproduced.

- [ ] Launch with no drive attached: the app remains responsive and shows no
  drive, without repeated log output or noticeable idle CPU use.
- [ ] Attach a USB optical drive after launch: it appears once; disconnecting it
  clears the selection without a crash.
- [ ] Start with an empty internal drive: opening/closing the tray produces the
  expected empty state.
- [ ] Insert a pressed audio CD: track count and per-track/album durations match
  a known player or `cdparanoia -Q`.
- [ ] Play, pause, stop, previous, next, volume, and mute work through the active
  PipeWire output; seeking is enabled only if the selected playback path can do
  it reliably.
- [ ] Remove/eject during playback: audio stops, stale background results are
  ignored, and the UI returns to an empty-drive state.
- [ ] Rip one short track to WAV, FLAC, and MP3; verify audio, tags, filename,
  output location, and that an existing file is never overwritten silently.
- [ ] Cancel a rip; confirm the worker stops promptly and partial output is
  clearly handled.
- [ ] Remove the disc during a rip; confirm cancellation and a useful in-window
  error without a frozen GUI.
- [ ] Insert a scratched/read-error disc and a non-audio DVD; errors remain
  non-blocking and the app stays usable.
- [ ] Insert ISO9660 and UDF data CDs: mount if authorized, navigate only inside
  the mount, open a file through KDE, and confirm no write operation is offered.
- [ ] Exercise two optical drives and verify actions target the selected device,
  not a hard-coded `/dev/sr0`.
- [ ] Disable networking and clear DNS: generic audio track data still loads,
  cached albums remain visible, and metadata failure never blocks local work.
- [ ] Reinsert a recognized disc: cached metadata is used without unnecessary
  requests; eject and rapid remove/reinsert do not apply stale results.
- [ ] Log out/in after changing any device-access policy, then repeat launch and
  rip checks as an unprivileged user.
- [ ] Run the AppImage and the source checkout through the same checklist.

## Troubleshooting

### No optical drive appears

```bash
systemctl status udisks2.service
udisksctl status
lsblk -o NAME,TYPE,RM,RO,MODEL,FSTYPE,LABEL,MOUNTPOINTS
```

Use `journalctl --user` for desktop-session issues and
`journalctl -u udisks2.service` for daemon events. CDFlow listens to UDisks2; it
does not repeatedly scan `/dev/sr*` as a fallback.

### A data CD is visible but not browsable

KDE may not have mounted it yet, or polkit may require user authorization. Try
mounting the exact block device once with `udisksctl mount -b /dev/sr0` and read
the resulting error. Browsing is intentionally limited to a mounted, resolved
disc path.

### Ripping or encoding is unavailable

```bash
command -v cdparanoia
command -v ffmpeg
cdparanoia --version
ffmpeg -version
```

WAV extraction requires CDDA access. FLAC/MP3 availability also depends on the
encoder support in the installed FFmpeg build. CDFlow should report a missing
tool before starting a job; it should not fail halfway through silently.

### Qt reports that no platform plugin can initialize

Run with `QT_DEBUG_PLUGINS=1` and inspect the first missing shared library. A
Fedora KDE host should normally already contain the Wayland/XKB/graphics stack.
Do not copy random Qt plugins from a different Qt version into the environment.

## Project layout

```text
src/cdflow/
  app/        central state, application controller, settings
  models/     drive, disc, album, and track data
  services/   UDisks2, TOC, playback, ripping, metadata, cache
  ui/         Qt pages, reusable widgets, and styles
  assets/     application artwork/icons
packaging/    desktop metadata and AppImage/PyInstaller inputs
tests/        deterministic unit tests
```

## License

CDFlow is available under the [MIT License](LICENSE).
