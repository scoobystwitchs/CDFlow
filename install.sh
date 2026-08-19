#!/usr/bin/env bash
set -euo pipefail

APP_NAME="CDFlow"
APP_ID="io.github.cdflow.CDFlow"
REPO="scoobystwitchs/CDFlow"

BIN_DIR="$HOME/.local/bin"
APP_DIR="$HOME/.local/share/applications"

mkdir -p "$BIN_DIR" "$APP_DIR"

echo "Finding latest CDFlow release..."

DOWNLOAD_URL="$(
  curl -fsSL "https://api.github.com/repos/$REPO/releases/latest" \
  | grep '"browser_download_url"' \
  | grep 'x86_64.AppImage' \
  | cut -d '"' -f 4 \
  | head -n 1
)"

if [[ -z "$DOWNLOAD_URL" ]]; then
  echo "No CDFlow AppImage found in the latest GitHub release."
  exit 1
fi

echo "Downloading CDFlow..."

curl -fL "$DOWNLOAD_URL" \
  -o "$BIN_DIR/CDFlow.AppImage"

chmod +x "$BIN_DIR/CDFlow.AppImage"

cat > "$APP_DIR/$APP_ID.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=CDFlow
GenericName=CD Player and Ripper
Comment=Play, inspect, browse, and rip compact discs
Exec=$BIN_DIR/CDFlow.AppImage
Icon=$APP_ID
Terminal=false
Categories=AudioVideo;Audio;Player;Qt;
Keywords=CD;Audio;Ripper;Disc;Music;
StartupNotify=true
StartupWMClass=$APP_ID
EOF

update-desktop-database "$APP_DIR" 2>/dev/null || true

echo
echo "CDFlow installed successfully."
echo "Open CDFlow from your application launcher."
