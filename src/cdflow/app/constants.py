"""Central constants; visual and product values live here, not in widgets."""

from __future__ import annotations

from pathlib import Path

from cdflow import __version__

APP_NAME = "CDFlow"
APP_ID = "io.github.cdflow.CDFlow"
ORGANIZATION_NAME = "CDFlow"
VERSION = __version__

DEFAULT_ACCENT = "#F43F86"
DEFAULT_THEME = "dark"
DEFAULT_RIP_FORMAT = "flac"
DEFAULT_RIP_QUALITY = "Lossless"
DEFAULT_FILENAME_PATTERN = "{track:02d} - {title}"
DEFAULT_MUSIC_DIR = Path.home() / "Music" / APP_NAME

UDISKS_SERVICE = "org.freedesktop.UDisks2"
UDISKS_ROOT = "/org/freedesktop/UDisks2"
UDISKS_OBJECT_MANAGER = "org.freedesktop.DBus.ObjectManager"
UDISKS_DRIVE_INTERFACE = "org.freedesktop.UDisks2.Drive"
UDISKS_BLOCK_INTERFACE = "org.freedesktop.UDisks2.Block"
UDISKS_FILESYSTEM_INTERFACE = "org.freedesktop.UDisks2.Filesystem"

MUSICBRAINZ_BASE_URL = "https://musicbrainz.org/ws/2"
COVER_ART_BASE_URL = "https://coverartarchive.org"
NETWORK_USER_AGENT = f"{APP_NAME}/{VERSION}"


def network_user_agent(contact: str) -> str:
    """Build the identifying User-Agent required by the metadata providers."""

    normalized = " ".join(str(contact).split())[:256]
    if not normalized:
        raise ValueError("a MusicBrainz maintainer contact is required")
    is_url = normalized.startswith(("https://", "http://")) and len(normalized.partition("://")[2]) > 3
    is_email = "@" in normalized and not normalized.startswith("@") and not normalized.endswith("@")
    if " " in normalized or not (is_url or is_email):
        raise ValueError("the MusicBrainz contact must be an email address or HTTP(S) URL")
    return f"{NETWORK_USER_AGENT} ({normalized})"
