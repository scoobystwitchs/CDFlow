#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ROOT="$PROJECT_ROOT/build"
APPDIR="$BUILD_ROOT/CDFlow.AppDir"
DIST_DIR="$PROJECT_ROOT/dist"
BUILD_PYTHON="${BUILD_PYTHON:-$PROJECT_ROOT/.venv/bin/python}"
APPIMAGETOOL="${APPIMAGETOOL:-}"

if [[ ! -x "$BUILD_PYTHON" ]]; then
    printf '%s\n' "No build Python found at: $BUILD_PYTHON" >&2
    printf '%s\n' "Create .venv and install the appimage extra first (see README.md)." >&2
    exit 1
fi

if ! "$BUILD_PYTHON" -c 'import sys; raise SystemExit(sys.version_info < (3, 12))'; then
    printf '%s\n' "CDFlow requires Python 3.12 or newer." >&2
    exit 1
fi

if ! "$BUILD_PYTHON" -c 'import PyInstaller' >/dev/null 2>&1; then
    printf '%s\n' "PyInstaller is missing. Install the appimage extra (see README.md)." >&2
    exit 1
fi

if [[ -z "$APPIMAGETOOL" ]]; then
    APPIMAGETOOL="$(command -v appimagetool || true)"
fi
if [[ -z "$APPIMAGETOOL" || ! -x "$APPIMAGETOOL" ]]; then
    printf '%s\n' "appimagetool was not found." >&2
    printf '%s\n' "Set APPIMAGETOOL=/absolute/path/to/appimagetool and retry." >&2
    exit 1
fi

case "$(uname -m)" in
    x86_64) APPIMAGE_ARCH=x86_64 ;;
    aarch64) APPIMAGE_ARCH=aarch64 ;;
    *)
        printf 'Unsupported AppImage build architecture: %s\n' "$(uname -m)" >&2
        exit 1
        ;;
esac

if [[ "$APPDIR" != "$PROJECT_ROOT/build/CDFlow.AppDir" ]]; then
    printf '%s\n' "Refusing to clear an unexpected AppDir path." >&2
    exit 1
fi

cd "$PROJECT_ROOT"
"$BUILD_PYTHON" -m PyInstaller --noconfirm --clean packaging/cdflow.spec

rm -rf -- "$APPDIR"
mkdir -p \
    "$APPDIR/usr/bin" \
    "$APPDIR/usr/share/doc/cdflow" \
    "$APPDIR/usr/lib/cdflow" \
    "$APPDIR/usr/share/applications" \
    "$APPDIR/usr/share/icons/hicolor/scalable/apps" \
    "$APPDIR/usr/share/metainfo" \
    "$DIST_DIR"

cp -a "$DIST_DIR/cdflow/." "$APPDIR/usr/lib/cdflow/"
cp packaging/appimage/AppRun "$APPDIR/AppRun"
cp packaging/io.github.cdflow.CDFlow.desktop "$APPDIR/io.github.cdflow.CDFlow.desktop"
cp packaging/io.github.cdflow.CDFlow.desktop "$APPDIR/usr/share/applications/"
cp packaging/io.github.cdflow.CDFlow.metainfo.xml "$APPDIR/usr/share/metainfo/"
cp src/cdflow/assets/io.github.cdflow.CDFlow.svg "$APPDIR/io.github.cdflow.CDFlow.svg"
cp src/cdflow/assets/io.github.cdflow.CDFlow.svg "$APPDIR/usr/share/icons/hicolor/scalable/apps/"
cp LICENSE THIRD_PARTY_NOTICES.md "$APPDIR/usr/share/doc/cdflow/"
ln -s ../lib/cdflow/cdflow "$APPDIR/usr/bin/cdflow"
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/lib/cdflow/cdflow"

APP_VERSION="$(PYTHONPATH="$PROJECT_ROOT/src" "$BUILD_PYTHON" -c 'from cdflow import __version__; print(__version__)')"
OUTPUT="$DIST_DIR/CDFlow-$APP_VERSION-$APPIMAGE_ARCH.AppImage"
TEMP_OUTPUT="$DIST_DIR/.CDFlow-$APP_VERSION-$APPIMAGE_ARCH.tmp.AppImage"

cleanup_output() {
    rm -f -- "$TEMP_OUTPUT"
}
trap cleanup_output EXIT
cleanup_output
ARCH="$APPIMAGE_ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$APPIMAGETOOL" "$APPDIR" "$TEMP_OUTPUT"
chmod +x "$TEMP_OUTPUT"
mv -f -- "$TEMP_OUTPUT" "$OUTPUT"
trap - EXIT
printf 'Created %s\n' "$OUTPUT"
