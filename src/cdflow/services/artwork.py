"""Optional Cover Art Archive lookup and bounded local image cache."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.error
import urllib.request
import uuid
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cdflow.app.constants import COVER_ART_BASE_URL, network_user_agent

from ._qt import QObject, Signal

MAX_ARTWORK_BYTES = 15 * 1024 * 1024
MAX_ARTWORK_INDEX_BYTES = 2 * 1024 * 1024


class ArtworkError(RuntimeError):
    pass


class ArtworkCancelled(ArtworkError):
    pass


@dataclass(frozen=True, slots=True)
class ArtworkResult:
    release_id: str
    path: Path | None
    from_cache: bool = False


def default_artwork_cache_directory() -> Path:
    cache_home = os.environ.get("XDG_CACHE_HOME")
    root = Path(cache_home).expanduser() if cache_home else Path.home() / ".cache"
    return root / "cdflow" / "artwork"


class ArtworkService(QObject):
    artwork_started = Signal(str, int)
    artwork_ready = Signal(object, int)
    artwork_not_found = Signal(str, int)
    artwork_failed = Signal(str, int)
    artwork_cancelled = Signal(int)

    def __init__(
        self,
        cache_directory: str | Path | None = None,
        *,
        request_timeout: float = 15.0,
        minimum_request_interval: float = 1.0,
        contact: str = "",
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.cache_directory = Path(cache_directory or default_artwork_cache_directory()).expanduser()
        self._timeout = max(request_timeout, 1.0)
        self._minimum_interval = max(minimum_request_interval, 1.0)
        self._contact = contact
        self._request_lock = threading.Lock()
        self._last_request_at = 0.0
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cdflow-artwork")
        self._lock = threading.RLock()
        self._cancel_event = threading.Event()
        self._future: Future[ArtworkResult] | None = None

    def fetch(
        self,
        release_id: str,
        *,
        force: bool = False,
        cancel_event: threading.Event | None = None,
    ) -> ArtworkResult:
        normalized_id = _normalize_release_id(release_id)
        cancelled = cancel_event or threading.Event()
        cached = self._cached_path(normalized_id)
        if cached and not force:
            return ArtworkResult(normalized_id, cached, True)
        if cancelled.is_set():
            raise ArtworkCancelled("artwork lookup was cancelled")
        index_url = f"{COVER_ART_BASE_URL}/release/{normalized_id}"
        try:
            raw, _content_type = self._download(
                index_url, MAX_ARTWORK_INDEX_BYTES, cancelled, accept="application/json"
            )
        except _ArtworkNotFound:
            return ArtworkResult(normalized_id, None)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ArtworkError("Cover Art Archive returned invalid JSON") from error
        image_url = _front_image_url(payload)
        if not image_url:
            return ArtworkResult(normalized_id, None)
        try:
            image, content_type = self._download(image_url, MAX_ARTWORK_BYTES, cancelled, accept="image/*")
        except _ArtworkNotFound:
            return ArtworkResult(normalized_id, None)
        extension = _image_extension(image, content_type)
        self.cache_directory.mkdir(parents=True, exist_ok=True)
        target = self.cache_directory / f"{normalized_id}{extension}"
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{normalized_id}-", suffix=".part", dir=self.cache_directory
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(image)
                handle.flush()
                os.fsync(handle.fileno())
            if cancelled.is_set():
                raise ArtworkCancelled("artwork lookup was cancelled")
            os.replace(temporary, target)
            for stale_extension in (".jpg", ".png", ".webp"):
                stale = self.cache_directory / f"{normalized_id}{stale_extension}"
                if stale != target:
                    stale.unlink(missing_ok=True)
        finally:
            temporary.unlink(missing_ok=True)
        return ArtworkResult(normalized_id, target)

    def fetch_async(self, release_id: str, *, generation: int = 0, force: bool = False) -> None:
        self.cancel()
        cancel_event = threading.Event()
        with self._lock:
            self._cancel_event = cancel_event
        self.artwork_started.emit(release_id, generation)
        future = self._executor.submit(self.fetch, release_id, force=force, cancel_event=cancel_event)
        with self._lock:
            self._future = future

        def completed(result: Future[ArtworkResult]) -> None:
            try:
                artwork = result.result()
            except (CancelledError, ArtworkCancelled):
                self.artwork_cancelled.emit(generation)
            except Exception as error:
                self.artwork_failed.emit(str(error), generation)
            else:
                if artwork.path:
                    self.artwork_ready.emit(artwork, generation)
                else:
                    self.artwork_not_found.emit(artwork.release_id, generation)

        future.add_done_callback(completed)

    def cancel(self) -> None:
        with self._lock:
            self._cancel_event.set()
            future = self._future
        if future:
            future.cancel()

    def shutdown(self, *, wait: bool = False) -> None:
        self.cancel()
        self._executor.shutdown(wait=wait, cancel_futures=True)

    def set_contact(self, contact: str) -> None:
        self._contact = " ".join(str(contact).split())[:256]

    def _cached_path(self, release_id: str) -> Path | None:
        for extension in (".jpg", ".png", ".webp"):
            candidate = self.cache_directory / f"{release_id}{extension}"
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    return candidate
            except OSError:
                continue
        return None

    def _download(
        self,
        url: str,
        maximum_bytes: int,
        cancel_event: threading.Event,
        *,
        accept: str,
    ) -> tuple[bytes, str]:
        try:
            user_agent = network_user_agent(self._contact)
        except ValueError as error:
            raise ArtworkError("A MusicBrainz contact email or URL is required for artwork lookup") from error
        request = urllib.request.Request(url, headers={"Accept": accept, "User-Agent": user_agent})
        with self._request_lock:
            delay = self._minimum_interval - (time.monotonic() - self._last_request_at)
            if delay > 0 and cancel_event.wait(delay):
                raise ArtworkCancelled("artwork lookup was cancelled")
            try:
                with urllib.request.urlopen(request, timeout=self._timeout) as response:
                    content_length = int(response.headers.get("Content-Length") or 0)
                    if content_length > maximum_bytes:
                        raise ArtworkError("artwork response exceeds the cache size limit")
                    chunks: list[bytes] = []
                    received = 0
                    while True:
                        if cancel_event.is_set():
                            raise ArtworkCancelled("artwork lookup was cancelled")
                        chunk = response.read(min(64 * 1024, maximum_bytes - received + 1))
                        if not chunk:
                            break
                        received += len(chunk)
                        if received > maximum_bytes:
                            raise ArtworkError("artwork response exceeds the cache size limit")
                        chunks.append(chunk)
                    content_type = str(response.headers.get_content_type() or "")
            except urllib.error.HTTPError as error:
                if error.code == 404:
                    raise _ArtworkNotFound from error
                raise ArtworkError(f"Cover Art Archive returned HTTP {error.code}") from error
            except (urllib.error.URLError, TimeoutError, OSError) as error:
                raise ArtworkError(f"Cover Art Archive is unavailable: {error}") from error
            finally:
                self._last_request_at = time.monotonic()
        return b"".join(chunks), content_type


class _ArtworkNotFound(Exception):
    pass


def _normalize_release_id(release_id: str) -> str:
    try:
        parsed = uuid.UUID(release_id)
    except (ValueError, AttributeError) as error:
        raise ValueError("release ID must be a MusicBrainz UUID") from error
    return str(parsed)


def _front_image_url(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    images = payload.get("images")
    if not isinstance(images, list):
        return ""
    front_images = [item for item in images if isinstance(item, dict) and item.get("front")]
    front_images.sort(key=lambda item: not bool(item.get("approved", False)))
    for item in front_images:
        thumbnails = item.get("thumbnails")
        thumbnails = thumbnails if isinstance(thumbnails, dict) else {}
        for key in ("500", "large", "1200", "small"):
            url = thumbnails.get(key)
            if isinstance(url, str) and url.startswith(("https://", "http://")):
                return url
        url = item.get("image")
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            return url
    return ""


def _image_extension(data: bytes, content_type: str) -> str:
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return ".webp"
    raise ArtworkError(f"unsupported artwork image type: {content_type or 'unknown'}")


__all__ = [
    "ArtworkCancelled",
    "ArtworkError",
    "ArtworkResult",
    "ArtworkService",
    "default_artwork_cache_directory",
]
