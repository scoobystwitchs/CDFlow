"""Lazily constructed application pages."""

from .browse_files import BrowseFilesPage
from .collection import CollectionPage
from .disc_info import DiscInfoPage
from .now_playing import NowPlayingPage
from .rip_cd import RipCDPage
from .settings import SettingsPage
from .tracks import TracksPage

__all__ = [
    "BrowseFilesPage",
    "CollectionPage",
    "DiscInfoPage",
    "NowPlayingPage",
    "RipCDPage",
    "SettingsPage",
    "TracksPage",
]
